"""Unit tests for the worker IPC skeleton (A1).

Covers the wire protocol, the handler registry, the dispatch logic, and a
subprocess smoke test that spawns ``python -m agent.worker.server`` and
drives it through stdio. No FreeCAD import is required — A1 is pure Python.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CADAGENT_DIR = REPO_ROOT / "src" / "Mod" / "CADAgent"


@pytest.fixture
def worker_modules(monkeypatch):
    """Import the worker modules fresh with src/Mod/CADAgent on sys.path."""
    monkeypatch.syspath_prepend(str(CADAGENT_DIR))
    for name in list(sys.modules):
        if name == "agent" or name.startswith("agent."):
            # Only drop the worker subpackage to avoid nuking agent.memory et al.
            if name in ("agent", "agent.worker") or name.startswith("agent.worker."):
                del sys.modules[name]
    import agent.worker.protocol as protocol  # type: ignore
    import agent.worker.registry as registry  # type: ignore
    import agent.worker.server as server  # type: ignore
    yield protocol, registry, server


# --- protocol --------------------------------------------------------------


def test_request_from_json_roundtrip(worker_modules):
    protocol, _, _ = worker_modules
    req = protocol.Request.from_json('{"id": 7, "method": "ping", "params": {"k": 1}}')
    assert req.id == 7
    assert req.method == "ping"
    assert req.params == {"k": 1}


def test_request_defaults_params_to_empty(worker_modules):
    protocol, _, _ = worker_modules
    req = protocol.Request.from_json('{"id": 1, "method": "ping"}')
    assert req.params == {}


def test_request_rejects_non_object(worker_modules):
    protocol, _, _ = worker_modules
    with pytest.raises(ValueError):
        protocol.Request.from_json("[]")


def test_request_rejects_missing_fields(worker_modules):
    protocol, _, _ = worker_modules
    with pytest.raises(ValueError):
        protocol.Request.from_json('{"id": 1}')


def test_response_ok_shape(worker_modules):
    protocol, _, _ = worker_modules
    line = protocol.ok(3, {"pong": True}).to_json()
    obj = json.loads(line)
    assert obj == {"id": 3, "result": {"pong": True}}


def test_response_err_shape(worker_modules):
    protocol, _, _ = worker_modules
    line = protocol.err(4, "boom").to_json()
    obj = json.loads(line)
    assert obj == {"id": 4, "error": "boom"}


# --- registry + dispatch ---------------------------------------------------


def test_ping_handler_registered(worker_modules):
    _, registry, _ = worker_modules
    assert "ping" in registry.methods()


def test_dispatch_ping_returns_pong_and_pid(worker_modules):
    _, registry, _ = worker_modules
    result = asyncio.run(registry.dispatch("ping", {}))
    assert result["pong"] is True
    assert result["pid"] == os.getpid()


def test_dispatch_unknown_method_raises_keyerror(worker_modules):
    _, registry, _ = worker_modules
    with pytest.raises(KeyError):
        asyncio.run(registry.dispatch("nope", {}))


def test_handler_decorator_registers_and_supports_async(worker_modules):
    _, registry, _ = worker_modules
    try:
        @registry.handler("t.sync")
        def sync_fn(x: int) -> int:
            return x + 1

        @registry.handler("t.async")
        async def async_fn(x: int) -> int:
            await asyncio.sleep(0)
            return x * 2

        assert asyncio.run(registry.dispatch("t.sync", {"x": 4})) == 5
        assert asyncio.run(registry.dispatch("t.async", {"x": 4})) == 8
    finally:
        # Don't leak into other tests.
        registry._HANDLERS.pop("t.sync", None)
        registry._HANDLERS.pop("t.async", None)


# --- handle_line -----------------------------------------------------------


def test_handle_line_blank_returns_none(worker_modules):
    _, _, server = worker_modules
    assert asyncio.run(server.handle_line("   \n")) is None


def test_handle_line_good_request(worker_modules):
    _, _, server = worker_modules
    resp = asyncio.run(server.handle_line('{"id": 1, "method": "ping", "params": {}}'))
    assert resp.id == 1
    assert resp.error is None
    assert resp.result["pong"] is True


def test_handle_line_parse_error_recovers_id(worker_modules):
    _, _, server = worker_modules
    resp = asyncio.run(server.handle_line('{"id": 9, "garbage": true}'))
    assert resp.id == 9
    assert resp.error and "parse error" in resp.error


def test_handle_line_malformed_json_uses_zero_id(worker_modules):
    _, _, server = worker_modules
    resp = asyncio.run(server.handle_line("not-json"))
    assert resp.id == 0
    assert resp.error


def test_handle_line_unknown_method(worker_modules):
    _, _, server = worker_modules
    resp = asyncio.run(server.handle_line('{"id": 2, "method": "bogus", "params": {}}'))
    assert resp.id == 2
    assert resp.error and "unknown method" in resp.error


def test_handle_line_bad_params_reports_type_error(worker_modules):
    _, _, server = worker_modules
    resp = asyncio.run(
        server.handle_line('{"id": 3, "method": "ping", "params": {"unexpected": 1}}')
    )
    assert resp.id == 3
    assert resp.error and "bad params" in resp.error


# --- subprocess smoke test -------------------------------------------------


def test_subprocess_smoke_ping():
    """Spawn the worker, send a ping, read the response, shut down."""
    env = dict(os.environ)
    # Make `import agent.worker.server` resolvable.
    env["PYTHONPATH"] = str(CADAGENT_DIR) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        [sys.executable, "-m", "agent.worker.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,  # line buffered
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write('{"id": 42, "method": "ping", "params": {}}\n')
        proc.stdin.flush()

        # Also send an unknown method to confirm graceful error handling.
        proc.stdin.write('{"id": 43, "method": "no_such_method", "params": {}}\n')
        proc.stdin.flush()

        line1 = proc.stdout.readline()
        line2 = proc.stdout.readline()

        # EOF → graceful shutdown.
        proc.stdin.close()
        rc = proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    assert rc == 0, f"worker exited {rc}; stderr={proc.stderr.read() if proc.stderr else ''}"

    obj1 = json.loads(line1)
    assert obj1["id"] == 42
    assert obj1["result"]["pong"] is True
    assert isinstance(obj1["result"]["pid"], int)

    obj2 = json.loads(line2)
    assert obj2["id"] == 43
    assert "unknown method" in obj2["error"]
