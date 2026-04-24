"""Tests for :class:`agent.worker.client.WorkerClient` (A2).

Uses plain ``sys.executable`` as the child interpreter and
``handlers_module=None`` so we can exercise the transport layer without
touching FreeCAD. Only the built-in ``ping`` handler is available.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CADAGENT_DIR = REPO_ROOT / "src" / "Mod" / "CADAgent"


@pytest.fixture
def client_module(monkeypatch):
    monkeypatch.syspath_prepend(str(CADAGENT_DIR))
    for name in list(sys.modules):
        if name == "agent" or name.startswith("agent."):
            if name in ("agent", "agent.worker") or name.startswith("agent.worker."):
                del sys.modules[name]
    import agent.worker.client as client  # type: ignore
    yield client


def _run(coro):
    return asyncio.run(coro)


def _make_client(client_module):
    return client_module.WorkerClient(sys.executable, handlers_module=None)


def test_client_ping_roundtrip(client_module):
    async def go():
        c = _make_client(client_module)
        try:
            result = await c.call("ping")
            assert result["pong"] is True
            assert isinstance(result["pid"], int)
            result2 = await c.call("ping")
            assert result2["pid"] == result["pid"]  # same process
        finally:
            rc = await c.close()
        assert rc == 0

    _run(go())


def test_client_unknown_method_raises_worker_error(client_module):
    async def go():
        c = _make_client(client_module)
        try:
            with pytest.raises(client_module.WorkerError) as ei:
                await c.call("no_such_method")
            assert "unknown method" in str(ei.value)
        finally:
            await c.close()

    _run(go())


def test_client_serializes_concurrent_calls(client_module):
    async def go():
        c = _make_client(client_module)
        try:
            r1, r2, r3 = await asyncio.gather(
                c.call("ping"), c.call("ping"), c.call("ping")
            )
            assert r1["pong"] and r2["pong"] and r3["pong"]
            assert r1["pid"] == r2["pid"] == r3["pid"]
        finally:
            await c.close()

    _run(go())


def test_client_start_is_idempotent(client_module):
    async def go():
        c = _make_client(client_module)
        try:
            await c.start()
            pid_first = c._proc.pid  # type: ignore[union-attr]
            await c.start()
            assert c._proc is not None and c._proc.pid == pid_first
        finally:
            await c.close()

    _run(go())
