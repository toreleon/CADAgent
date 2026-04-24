# SPDX-License-Identifier: LGPL-2.1-or-later
"""Async client for the long-lived CAD worker subprocess.

Owns a child process that runs :mod:`agent.worker.server` (either under
``FreeCADCmd`` for real FreeCAD handlers, or plain ``python`` for tests
that only exercise transport). Serializes requests behind an
``asyncio.Lock`` so the strict request/response protocol stays in
lockstep.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


_MOD_ROOT = Path(__file__).resolve().parents[2]  # .../src/Mod/CADAgent

_BOOTSTRAP_HEAD = (
    "import sys; "
    "sys.path.insert(0, {mod_root!r}); "
)
_BOOTSTRAP_HANDLERS = (
    "import importlib; importlib.import_module({handlers!r}); "
)
_BOOTSTRAP_TAIL = (
    "from agent.worker.server import main; "
    "raise SystemExit(main())"
)


def default_freecadcmd() -> str:
    """Best-effort default path to ``FreeCADCmd`` for this repo."""
    env = os.environ.get("CADAGENT_FREECADCMD")
    if env:
        return env
    # Repo root == three levels above src/Mod/CADAgent
    candidate = _MOD_ROOT.parents[2] / "build" / "debug" / "bin" / "FreeCADCmd"
    if candidate.exists():
        return str(candidate)
    return "FreeCADCmd"


class WorkerError(RuntimeError):
    """Raised when the worker returns a structured error response."""


class WorkerClient:
    """A single long-lived worker subprocess driven over stdio JSON.

    ``executable`` defaults to ``FreeCADCmd`` so handlers that import
    FreeCAD work out of the box. Tests can pass ``sys.executable`` and
    the client will run the same bootstrap against CPython, giving
    transport-level coverage without a FreeCAD dependency.
    """

    def __init__(
        self,
        executable: str | None = None,
        *,
        env: dict[str, str] | None = None,
        mod_root: str | None = None,
        handlers_module: str | None = "agent.worker.handlers",
    ):
        self._executable = executable or default_freecadcmd()
        self._extra_env = env or {}
        self._mod_root = mod_root or str(_MOD_ROOT)
        self._handlers_module = handlers_module
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._next_id = 0

    # --- lifecycle ---------------------------------------------------

    async def start(self) -> None:
        async with self._start_lock:
            if self._proc is not None and self._proc.returncode is None:
                return
            bootstrap = _BOOTSTRAP_HEAD.format(mod_root=self._mod_root)
            if self._handlers_module:
                bootstrap += _BOOTSTRAP_HANDLERS.format(handlers=self._handlers_module)
            bootstrap += _BOOTSTRAP_TAIL
            env = {**os.environ, **self._extra_env}
            self._proc = await asyncio.create_subprocess_exec(
                self._executable,
                "-c",
                bootstrap,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

    async def close(self, *, timeout: float = 5.0) -> int | None:
        proc = self._proc
        if proc is None:
            return None
        self._proc = None
        try:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
            return await asyncio.wait_for(proc.wait(), timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            try:
                proc.kill()
                return await proc.wait()
            except ProcessLookupError:
                return None

    async def __aenter__(self) -> "WorkerClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # --- RPC ---------------------------------------------------------

    async def call(self, method: str, **params: Any) -> Any:
        """Send one request, return the parsed result, or raise.

        Raises :class:`WorkerError` for protocol-level errors (unknown
        method, bad params, handler exception). Raises
        :class:`RuntimeError` if the worker process has exited.
        """
        if self._proc is None or self._proc.returncode is not None:
            await self.start()
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None

        async with self._lock:
            self._next_id += 1
            req = {"id": self._next_id, "method": method, "params": params}
            line = (json.dumps(req) + "\n").encode("utf-8")
            try:
                proc.stdin.write(line)
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise RuntimeError(f"worker stdin closed: {exc}") from exc

            raw = await proc.stdout.readline()
            if not raw:
                rc = await proc.wait()
                stderr = b""
                if proc.stderr is not None:
                    try:
                        stderr = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass
                raise RuntimeError(
                    f"worker exited before responding (rc={rc}): "
                    f"{stderr.decode('utf-8', errors='replace').strip()}"
                )
            resp = json.loads(raw.decode("utf-8"))

        if "error" in resp and resp["error"] is not None:
            raise WorkerError(resp["error"])
        return resp.get("result")


# ---------------------------------------------------------------------------
# Process-wide singleton for MCP tool use
# ---------------------------------------------------------------------------

_SINGLETON: WorkerClient | None = None
_SINGLETON_LOCK = asyncio.Lock()


async def get_shared() -> WorkerClient:
    """Return (and lazily start) a process-wide :class:`WorkerClient`.

    Used by dock MCP tools that want live introspection without the
    caller having to manage the subprocess lifecycle.
    """
    global _SINGLETON
    async with _SINGLETON_LOCK:
        if _SINGLETON is None or (
            _SINGLETON._proc is not None and _SINGLETON._proc.returncode is not None
        ):
            _SINGLETON = WorkerClient()
            await _SINGLETON.start()
        return _SINGLETON


async def close_shared() -> None:
    global _SINGLETON
    async with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            await _SINGLETON.close()
            _SINGLETON = None
