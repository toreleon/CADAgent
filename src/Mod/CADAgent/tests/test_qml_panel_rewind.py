"""Headless tests for ChatBridge.requestRewind (W2-A).

Drives the bridge slot with a mock runtime that returns a target sid; verifies
the model is reloaded from the persisted rows and a non-empty new_text is
re-submitted.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import threading
import time

import pytest

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


class _Qt:
    @staticmethod
    def translate(_ctx, msg, *_):
        return msg


@pytest.fixture(autouse=True)
def _patch_freecad_qt(fc):
    """qml_panel does ``App.Qt.translate(...)`` at module top-level."""
    fc_mod = sys.modules.get("FreeCAD")
    if fc_mod is not None and not hasattr(fc_mod, "Qt"):
        fc_mod.Qt = _Qt  # type: ignore[attr-defined]
    yield


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Loop:
    """Tiny dedicated asyncio loop running on a worker thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._t.join(timeout=1)


class _Runtime:
    """Mock dock_runtime: only the surface ``requestRewind`` touches."""

    def __init__(self, loop, new_sid: str = "fork-sid") -> None:
        self._loop = loop
        self._new_sid = new_sid
        self.calls: list[tuple[str, bool, object]] = []
        self.submitted: list[str] = []

    async def rewind_to(self, row_id, fork, new_user_text=None):
        self.calls.append((row_id, fork, new_user_text))
        return self._new_sid

    def submit(self, text, attachments=None):
        self.submitted.append(text)


@pytest.fixture
def panel(qapp, fake_doc):
    """Construct a stub panel + bridge wired to a fake runtime/loop."""
    qm = importlib.import_module("agent.ui.qml_panel")

    class _Stub:
        def __init__(self):
            self._bound_doc = fake_doc
            self._current_session_id = None
            self._first_prompt = None
            self.errors: list[str] = []

        def _active_doc(self):
            return self._bound_doc

        def show_error(self, msg):
            self.errors.append(msg)

    stub = _Stub()
    stub.model = qm.MessagesModel()
    bridge = qm.QmlChatBridge(stub.model)
    stub.bridge = bridge
    return qm, stub, bridge


def _wait_until(qapp, predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def test_request_rewind_reloads_and_resubmits(qapp, panel, fake_doc):
    qm, stub, bridge = panel
    from agent import sessions

    rows = [
        {"rowId": "r0", "kind": "user", "text": "u0"},
        {"rowId": "r1", "kind": "assistant", "text": "a0"},
    ]
    sessions.save_rows(fake_doc, "fork-sid", rows)

    loop = _Loop()
    rt = _Runtime(loop.loop, new_sid="fork-sid")
    bridge.bind(stub, rt)

    bridge.requestRewind("r0", True, "  new prompt  ")

    assert _wait_until(qapp, lambda: bool(rt.submitted))
    # Drain pending GUI events one more time.
    for _ in range(5):
        qapp.processEvents()

    loop.stop()

    assert rt.calls == [("r0", True, "new prompt")]
    assert rt.submitted == ["new prompt"]
    assert stub._current_session_id == "fork-sid"
    # Persisted prefix loaded; the resubmitted prompt is appended on top.
    kinds = [r.get("kind") for r in stub.model._rows]
    assert kinds[:2] == ["user", "assistant"]
    assert kinds[-1] == "user"
    assert stub.model._rows[-1].get("text") == "new prompt"


def test_request_rewind_empty_text_only_reloads(qapp, panel, fake_doc):
    qm, stub, bridge = panel
    from agent import sessions

    sessions.save_rows(fake_doc, "same-sid", [
        {"rowId": "r0", "kind": "user", "text": "u0"},
    ])

    loop = _Loop()
    rt = _Runtime(loop.loop, new_sid="same-sid")
    bridge.bind(stub, rt)

    bridge.requestRewind("r0", False, "")

    assert _wait_until(qapp, lambda: stub._current_session_id == "same-sid")

    loop.stop()

    assert rt.calls == [("r0", False, None)]
    assert rt.submitted == []


def test_request_rewind_no_runtime_is_noop(qapp, panel):
    qm, stub, bridge = panel
    bridge._runtime = None
    bridge.requestRewind("r0", False, "x")
    assert stub.errors == []
