"""Unit tests for the agent-side :class:`WorkerClient` (A2).

Spawns real ``python -m agent.worker.server`` subprocesses through the
client and exercises the request/response correlation, crash handling, and
cleanup paths. Pure Python — no FreeCAD import.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CADAGENT_DIR = REPO_ROOT / "src" / "Mod" / "CADAgent"


@pytest.fixture
def worker_client_module(monkeypatch):
    """Import the client module fresh with src/Mod/CADAgent on sys.path."""
    monkeypatch.syspath_prepend(str(CADAGENT_DIR))
    for name in list(sys.modules):
        if name in ("agent", "agent.cli") or name.startswith("agent.cli."):
            if name in (
                "agent.cli.worker_client",
                "agent.cli.worker_singleton",
            ):
                del sys.modules[name]
    import agent.cli.worker_client as wc  # type: ignore
    return wc


def _run(coro):
    return asyncio.run(coro)


def test_ping_roundtrip(worker_client_module):
    wc = worker_client_module

    async def _go():
        client = wc.WorkerClient()
        await client.start()
        try:
            result = await client.call("ping", {})
            assert result["pong"] is True
            assert isinstance(result["pid"], int)
            assert await client.ping() is True
        finally:
            await client.close()
        assert not client.is_alive

    _run(_go())


def test_concurrent_calls_correlate(worker_client_module):
    wc = worker_client_module

    async def _go():
        client = wc.WorkerClient()
        await client.start()
        try:
            r1, r2, r3 = await asyncio.gather(
                client.call("ping", {}),
                client.call("ping", {}),
                client.call("ping", {}),
            )
            assert r1["pong"] is True
            assert r2["pong"] is True
            assert r3["pong"] is True
        finally:
            await client.close()

    _run(_go())


def test_unknown_method_raises_worker_error(worker_client_module):
    wc = worker_client_module

    async def _go():
        client = wc.WorkerClient()
        await client.start()
        try:
            with pytest.raises(wc.WorkerError) as ei:
                await client.call("nonexistent", {})
            assert "unknown method" in str(ei.value)
            # Client stays usable after a handler-level error.
            assert await client.ping() is True
        finally:
            await client.close()

    _run(_go())


def test_kill_midflight_rejects_pending(worker_client_module):
    wc = worker_client_module

    async def _go():
        client = wc.WorkerClient()
        await client.start()
        try:
            # Issue a call for a slow method that doesn't exist *and* kill the
            # worker before it has a chance to respond. We start the call, then
            # kill the proc; the reader sees EOF and should reject the future.
            async def _call_and_expect_crash():
                with pytest.raises(wc.WorkerCrashedError):
                    await client.call("ping", {}, timeout=5.0)

            task = asyncio.create_task(_call_and_expect_crash())
            # Give the call a moment to register its pending future and write.
            await asyncio.sleep(0.05)
            assert client._proc is not None
            try:
                client._proc.send_signal(signal.SIGKILL)
            except ProcessLookupError:
                pass
            await asyncio.wait_for(task, timeout=5.0)
            assert not client.is_alive
        finally:
            await client.close()

    _run(_go())


def test_close_without_start_is_noop(worker_client_module):
    wc = worker_client_module

    async def _go():
        client = wc.WorkerClient()
        await client.close()  # must not raise
        assert not client.is_alive

    _run(_go())


def test_ensure_alive_restarts_dead_worker(worker_client_module):
    wc = worker_client_module

    async def _go():
        client = wc.WorkerClient()
        await client.start()
        proc = client._proc
        assert proc is not None
        try:
            proc.send_signal(signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        # Give the reader task a moment to flip _alive to False.
        for _ in range(20):
            if not client.is_alive:
                break
            await asyncio.sleep(0.05)
        assert not client.is_alive

        await client.ensure_alive()
        assert client.is_alive
        assert await client.ping() is True
        await client.close()

    _run(_go())
