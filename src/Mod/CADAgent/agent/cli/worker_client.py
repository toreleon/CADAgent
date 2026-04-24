# SPDX-License-Identifier: LGPL-2.1-or-later
"""Agent-side async client for the ``agent.worker.server`` subprocess.

Spawns the worker as ``python -m agent.worker.server`` and talks to it via
newline-delimited JSON over stdio (see :mod:`agent.worker.protocol`).

Usage::

    client = WorkerClient()
    await client.start()
    result = await client.call("ping", {})
    await client.close()

The client owns request/response correlation (auto-incrementing int ids) and
a background reader task that resolves matching ``asyncio.Future``\\ s. It
does not implement any verb-tool semantics — those live on top of ``call()``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# Repo path so the worker's ``import agent.worker.server`` resolves even when
# ``src/Mod/CADAgent`` isn't on ``PYTHONPATH``. This file lives at
# ``src/Mod/CADAgent/agent/cli/worker_client.py`` → parents[2] is the package.
_CADAGENT_DIR = Path(__file__).resolve().parents[2]


class WorkerCrashedError(RuntimeError):
    """Raised when the worker exits while a call is in flight."""


class WorkerClient:
    """Async JSON-RPC client for the CAD worker subprocess."""

    def __init__(
        self,
        *,
        python: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self._python = python or sys.executable
        self._env = env
        self._cwd = cwd
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id: int = 1
        self._write_lock = asyncio.Lock()
        self._alive: bool = False

    # --- lifecycle -----------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self._alive and self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        if self.is_alive:
            return
        env = dict(self._env) if self._env is not None else dict(os.environ)
        # Make ``agent.worker.server`` importable without requiring the caller
        # to pre-configure ``PYTHONPATH``.
        existing = env.get("PYTHONPATH", "")
        cadagent_dir = str(_CADAGENT_DIR)
        if cadagent_dir not in existing.split(os.pathsep):
            env["PYTHONPATH"] = (
                cadagent_dir + os.pathsep + existing if existing else cadagent_dir
            )

        self._proc = await asyncio.create_subprocess_exec(
            self._python,
            "-m",
            "agent.worker.server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self._cwd,
        )
        self._alive = True
        self._reader_task = asyncio.create_task(
            self._read_loop(), name="cad-worker-reader"
        )

    async def ensure_alive(self) -> None:
        """Restart the worker if it has died."""
        if not self.is_alive:
            await self._cleanup_dead_state()
            await self.start()

    async def close(self) -> None:
        proc = self._proc
        self._alive = False
        if proc is None:
            return
        # Close stdin to signal EOF → worker shuts down cleanly.
        try:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        # Cancel reader task (it will have hit EOF by now, but be safe).
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        self._reader_task = None
        self._fail_pending(WorkerCrashedError("worker shut down"))
        self._proc = None

    # --- request/response ---------------------------------------------

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> Any:
        """Send a request and await its response. Returns ``result`` on success."""
        if not self.is_alive or self._proc is None or self._proc.stdin is None:
            raise WorkerCrashedError("worker is not running")

        req_id = self._next_id
        self._next_id += 1
        payload = {"id": req_id, "method": method, "params": params or {}}
        line = (json.dumps(payload) + "\n").encode("utf-8")

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req_id] = future

        try:
            async with self._write_lock:
                self._proc.stdin.write(line)
                await self._proc.stdin.drain()
        except (ConnectionError, BrokenPipeError) as exc:
            self._pending.pop(req_id, None)
            raise WorkerCrashedError(f"write failed: {exc}") from exc

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise
        except asyncio.CancelledError:
            self._pending.pop(req_id, None)
            raise

        if "error" in response and response.get("error") is not None:
            raise WorkerError(str(response["error"]))
        return response.get("result")

    async def ping(self) -> bool:
        try:
            result = await self.call("ping", {}, timeout=5.0)
        except Exception as exc:
            log.debug("worker ping failed: %s", exc)
            return False
        return bool(isinstance(result, dict) and result.get("pong"))

    # --- internals -----------------------------------------------------

    async def _read_loop(self) -> None:
        assert self._proc is not None
        assert self._proc.stdout is not None
        stdout = self._proc.stdout
        try:
            while True:
                raw = await stdout.readline()
                if not raw:
                    break  # EOF
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    log.warning("worker produced unparseable line: %s (%s)", raw, exc)
                    continue
                if not isinstance(obj, dict) or "id" not in obj:
                    log.warning("worker response missing id: %s", obj)
                    continue
                rid = obj.get("id")
                fut = self._pending.pop(rid, None) if isinstance(rid, int) else None
                if fut is None:
                    log.warning("worker response with no pending id: %s", rid)
                    continue
                if not fut.done():
                    fut.set_result(obj)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("worker reader crashed: %s", exc)
        finally:
            # EOF or reader crash → worker is effectively dead.
            self._alive = False
            self._fail_pending(WorkerCrashedError("worker exited"))

    def _fail_pending(self, exc: BaseException) -> None:
        pending = self._pending
        self._pending = {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(exc)

    async def _cleanup_dead_state(self) -> None:
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        self._reader_task = None
        self._fail_pending(WorkerCrashedError("worker died"))
        self._proc = None


class WorkerError(RuntimeError):
    """Raised when the worker returns an ``error`` envelope for a call."""
