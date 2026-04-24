"""Unit tests for the MCP verb-tool shims (A3).

Pure Python — no FreeCAD, no real worker subprocess. We patch
``get_worker()`` to return a stub and assert the shim's envelope behaviour.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CADAGENT_DIR = REPO_ROOT / "src" / "Mod" / "CADAgent"


@pytest.fixture
def verb_tools_module(monkeypatch):
    monkeypatch.syspath_prepend(str(CADAGENT_DIR))
    for name in list(sys.modules):
        if name in ("agent.cli.verb_tools", "agent.cli.worker_singleton"):
            del sys.modules[name]
    import agent.cli.verb_tools as vt  # type: ignore
    return vt


class _StubWorker:
    """Minimal ``WorkerClient`` stand-in — records calls, returns a canned dict."""

    def __init__(self, response: dict | None = None, alive: bool = True):
        self.is_alive = alive
        self._response = response or {}
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict, **_kwargs):
        self.calls.append((method, params))
        return dict(self._response)


def _parse_envelope(result: dict) -> dict:
    """Extract the JSON payload the SDK wraps tool output in."""
    content = result["content"][0]
    assert content["type"] == "text"
    return json.loads(content["text"])


def _call(fn, args: dict) -> dict:
    handler = getattr(fn, "handler", None) or fn
    return asyncio.run(handler(args))


def test_doc_inspect_returns_ok_envelope(verb_tools_module, monkeypatch):
    canned = {
        "path": "/tmp/x.FCStd",
        "name": "X",
        "label": "X",
        "dirty": False,
        "object_count": 1,
        "objects": [{"name": "Box1", "label": "Box", "type": "Part::Box", "visible": True}],
    }
    worker = _StubWorker(response=canned)
    monkeypatch.setattr(verb_tools_module, "get_worker", lambda: worker)

    result = _call(verb_tools_module.doc_inspect, {"doc": "/tmp/x.FCStd"})
    payload = _parse_envelope(result)
    assert payload["ok"] is True
    assert payload["object_count"] == 1
    assert payload["objects"][0]["name"] == "Box1"
    # Shim passes the resolved absolute path + default include_hidden=True.
    assert worker.calls == [
        ("doc_inspect", {"doc": "/tmp/x.FCStd", "include_hidden": True})
    ]


def test_doc_inspect_forwards_include_hidden_false(verb_tools_module, monkeypatch):
    worker = _StubWorker(response={"path": "/tmp/x.FCStd", "name": "X", "label": "X",
                                   "dirty": False, "object_count": 0, "objects": []})
    monkeypatch.setattr(verb_tools_module, "get_worker", lambda: worker)

    _call(
        verb_tools_module.doc_inspect,
        {"doc": "/tmp/x.FCStd", "include_hidden": False},
    )
    assert worker.calls[0][1]["include_hidden"] is False


def test_doc_inspect_errors_when_worker_missing(verb_tools_module, monkeypatch):
    monkeypatch.setattr(verb_tools_module, "get_worker", lambda: None)
    result = _call(verb_tools_module.doc_inspect, {"doc": "/tmp/x.FCStd"})
    assert result.get("isError") is True
    payload = _parse_envelope(result)
    assert payload["ok"] is False
    assert "not running" in payload["error"]


def test_doc_inspect_errors_when_worker_dead(verb_tools_module, monkeypatch):
    monkeypatch.setattr(
        verb_tools_module, "get_worker", lambda: _StubWorker(alive=False)
    )
    result = _call(verb_tools_module.doc_inspect, {"doc": "/tmp/x.FCStd"})
    assert result.get("isError") is True
    payload = _parse_envelope(result)
    assert "not running" in payload["error"]


def test_doc_inspect_requires_doc(verb_tools_module, monkeypatch):
    monkeypatch.setattr(
        verb_tools_module, "get_worker", lambda: _StubWorker(response={})
    )
    result = _call(verb_tools_module.doc_inspect, {})
    assert result.get("isError") is True
    payload = _parse_envelope(result)
    assert "'doc' is required" in payload["error"]


def test_allowed_tool_names_includes_doc_inspect(verb_tools_module):
    names = verb_tools_module.allowed_tool_names("cad")
    assert "mcp__cad__doc_inspect" in names
