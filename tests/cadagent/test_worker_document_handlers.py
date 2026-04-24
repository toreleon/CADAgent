"""Tests for the FreeCAD document handlers (A2).

Runs without a real FreeCAD install by stubbing ``FreeCAD`` in
``sys.modules`` before the handler module imports. The stub mimics the
attributes the handler touches: ``App.openDocument``, ``listDocuments``,
``closeDocument`` plus a ``Document``/``DocumentObject`` duo with
``Name``/``Label``/``TypeId``/``FileName``/``Objects``/``getObject``/
``recompute``.
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CADAGENT_DIR = REPO_ROOT / "src" / "Mod" / "CADAgent"


class _FakeObject:
    def __init__(self, name, type_id="App::Feature", **props):
        self.Name = name
        self.Label = name
        self.TypeId = type_id
        for k, v in props.items():
            setattr(self, k, v)


class _FakeDoc:
    def __init__(self, path, objects=None):
        self.Name = Path(path).stem
        self.Label = self.Name
        self.FileName = path
        self.Objects = list(objects or [])
        self.recomputes = 0

    def getObject(self, name):
        for o in self.Objects:
            if o.Name == name:
                return o
        return None

    def recompute(self):
        self.recomputes += 1


class _FakeApp:
    def __init__(self):
        self._docs: dict[str, _FakeDoc] = {}
        self._next_doc: _FakeDoc | None = None

    # --- FreeCAD API surface the handlers use ---
    def listDocuments(self):
        return dict(self._docs)

    def openDocument(self, path):
        if self._next_doc is not None:
            doc = self._next_doc
            self._next_doc = None
        else:
            doc = _FakeDoc(path)
        self._docs[doc.Name] = doc
        return doc

    def closeDocument(self, name):
        self._docs.pop(name, None)

    # --- test helpers ---
    def seed(self, doc: _FakeDoc):
        """Pre-load a doc as if the user already had it open."""
        self._docs[doc.Name] = doc

    def queue_open(self, doc: _FakeDoc):
        """The next openDocument() call returns this doc."""
        self._next_doc = doc


@pytest.fixture
def handlers(monkeypatch):
    app = _FakeApp()
    fake_module = types.ModuleType("FreeCAD")
    fake_module.listDocuments = app.listDocuments
    fake_module.openDocument = app.openDocument
    fake_module.closeDocument = app.closeDocument
    monkeypatch.setitem(sys.modules, "FreeCAD", fake_module)

    monkeypatch.syspath_prepend(str(CADAGENT_DIR))
    for name in list(sys.modules):
        if name == "agent" or name.startswith("agent."):
            if name in ("agent", "agent.worker") or name.startswith("agent.worker."):
                del sys.modules[name]

    import agent.worker.registry as registry  # type: ignore
    registry.clear()
    from agent.worker import server as server  # type: ignore  # noqa: F401 registers ping
    from agent.worker.handlers import document as document  # type: ignore

    yield types.SimpleNamespace(app=app, document=document, registry=registry)

    registry.clear()


def _run(coro):
    return asyncio.run(coro)


def test_doc_open_returns_summary(handlers):
    doc = _FakeDoc("/tmp/a.FCStd", objects=[_FakeObject("Box")])
    handlers.app.queue_open(doc)
    result = _run(handlers.registry.dispatch("doc.open", {"path": "/tmp/a.FCStd"}))
    assert result == {
        "name": "a",
        "label": "a",
        "path": "/tmp/a.FCStd",
        "object_count": 1,
    }


def test_doc_open_reuses_already_loaded(handlers):
    doc = _FakeDoc("/tmp/b.FCStd")
    handlers.app.seed(doc)
    _run(handlers.registry.dispatch("doc.open", {"path": "/tmp/b.FCStd"}))
    # openDocument should NOT have been called (seed → no queued next doc)
    assert handlers.app._next_doc is None
    # current() reflects the seeded instance
    cur = _run(handlers.registry.dispatch("doc.current", {}))
    assert cur["name"] == "b"


def test_doc_inspect_tree_and_single_object(handlers):
    doc = _FakeDoc(
        "/tmp/c.FCStd",
        objects=[
            _FakeObject("Box", Length=10),
            _FakeObject("Cyl", "Part::Cylinder", Radius=5),
        ],
    )
    handlers.app.queue_open(doc)
    _run(handlers.registry.dispatch("doc.open", {"path": "/tmp/c.FCStd"}))

    # Full tree, no props
    tree = _run(handlers.registry.dispatch("doc.inspect", {}))
    assert tree["document"]["object_count"] == 2
    assert [o["name"] for o in tree["objects"]] == ["Box", "Cyl"]
    assert "properties" not in tree["objects"][0]

    # One object with selected props
    single = _run(handlers.registry.dispatch(
        "doc.inspect", {"obj_name": "Box", "props": ["Length", "DoesNotExist"]}
    ))
    assert single["object"]["name"] == "Box"
    assert single["object"]["properties"]["Length"] == 10
    # Missing attrs become a structured error string, not a raise
    assert "AttributeError" in single["object"]["properties"]["DoesNotExist"]


def test_doc_inspect_unknown_object_raises(handlers):
    doc = _FakeDoc("/tmp/d.FCStd")
    handlers.app.queue_open(doc)
    _run(handlers.registry.dispatch("doc.open", {"path": "/tmp/d.FCStd"}))
    with pytest.raises(KeyError):
        _run(handlers.registry.dispatch("doc.inspect", {"obj_name": "Nope"}))


def test_doc_inspect_without_open_raises(handlers):
    with pytest.raises(RuntimeError, match="no document open"):
        _run(handlers.registry.dispatch("doc.inspect", {}))


def test_doc_recompute_increments(handlers):
    doc = _FakeDoc("/tmp/e.FCStd", objects=[_FakeObject("X")])
    handlers.app.queue_open(doc)
    _run(handlers.registry.dispatch("doc.open", {"path": "/tmp/e.FCStd"}))
    out = _run(handlers.registry.dispatch("doc.recompute", {}))
    assert out == {"object_count": 1}
    assert doc.recomputes == 1


def test_doc_close_drops_state(handlers):
    doc = _FakeDoc("/tmp/f.FCStd")
    handlers.app.queue_open(doc)
    _run(handlers.registry.dispatch("doc.open", {"path": "/tmp/f.FCStd"}))
    out = _run(handlers.registry.dispatch("doc.close", {}))
    assert out == {"closed": True}
    out2 = _run(handlers.registry.dispatch("doc.close", {}))
    assert out2 == {"closed": False}
