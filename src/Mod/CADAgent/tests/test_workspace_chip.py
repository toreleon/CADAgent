"""W2-D backend tests: runtime.list_open_docs / set_active_document."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_runtime_freecad():
    """The dock_runtime module captured ``App`` at import time, so it sees a
    different namespace than the per-test ``fc`` fixture. Wipe its docs here
    so tests don't bleed state into each other."""
    from agent.runtime import dock_runtime as _dr

    for name in list(_dr.App.listDocuments()):
        _dr.App.closeDocument(name)
    yield
    for name in list(_dr.App.listDocuments()):
        _dr.App.closeDocument(name)


@pytest.fixture
def runtime(fc, monkeypatch):
    """A DockRuntime with a minimal QObject panel — enough to exercise
    list_open_docs / set_active_document without standing up the QML view.
    """
    from PySide6 import QtCore  # type: ignore[import-not-found]

    from agent.runtime import dock_runtime

    class _StubPanel(QtCore.QObject):
        def __init__(self):
            super().__init__()
            self._model = None
            self._bound_doc = None
            self._current_session_id = None

        def show_error(self, *_a, **_k):
            pass

        # Slots the _PanelProxy connects in __init__; no-ops are fine.
        def append_assistant_text(self, *_a, **_k): pass
        def append_thinking(self, *_a, **_k): pass
        def announce_tool_use(self, *_a, **_k): pass
        def announce_tool_result(self, *_a, **_k): pass
        def record_result(self, *_a, **_k): pass
        def mark_turn_complete(self, *_a, **_k): pass

    rt = dock_runtime.DockRuntime(_StubPanel())
    return rt


def test_list_open_docs_empty(runtime):
    assert runtime.list_open_docs() == []


def test_list_open_docs_marks_active(runtime, fc, tmp_path):
    from agent.runtime import dock_runtime as _dr
    App = _dr.App  # the runtime's bound module — what list_open_docs reads.

    a = App.openDocument(str(tmp_path / "a.FCStd"))
    b = App.openDocument(str(tmp_path / "b.FCStd"))
    App.setActiveDocument(a.Name)

    entries = runtime.list_open_docs()
    by_name = {e["name"]: e for e in entries}
    assert set(by_name) == {a.Name, b.Name}
    assert by_name[a.Name]["active"] is True
    assert by_name[b.Name]["active"] is False
    assert by_name[a.Name]["path"].endswith("a.FCStd")


def test_set_active_document_by_name_updates_workspace(runtime, fc, tmp_path):
    from agent.runtime import dock_runtime as _dr
    App = _dr.App  # the runtime's bound module — what list_open_docs reads.

    a = App.openDocument(str(tmp_path / "a.FCStd"))
    b = App.openDocument(str(tmp_path / "b.FCStd"))
    App.setActiveDocument(a.Name)

    fired: list[str] = []
    runtime._proxy.activeDocChanged.connect(fired.append)

    assert runtime.set_active_document(b.Name) is True
    assert App.ActiveDocument.Name == b.Name
    assert runtime._workspace_path and runtime._workspace_path.endswith("b.FCStd")
    assert fired and fired[-1].endswith("b.FCStd")


def test_set_active_document_by_label_fallback(runtime, fc, tmp_path):
    from agent.runtime import dock_runtime as _dr
    App = _dr.App  # the runtime's bound module — what list_open_docs reads.

    doc = App.openDocument(str(tmp_path / "labelled.FCStd"))
    doc.Label = "my model"

    assert runtime.set_active_document("my model") is True
    assert App.ActiveDocument.Name == doc.Name


def test_set_active_document_unknown_returns_false(runtime, fc):
    assert runtime.set_active_document("does-not-exist") is False
