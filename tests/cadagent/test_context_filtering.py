"""Unit tests for context.py's decision-filtering helpers.

Exercises _select_relevant_decisions + _format_decision in isolation. The
functions pull from memory.py, so we reuse the FreeCAD-stub machinery from
test_memory_schema.py.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


def _install_freecad_stub(tmp_path: Path) -> None:
    if "FreeCAD" in sys.modules:
        return
    stub = types.ModuleType("FreeCAD")
    stub.getUserAppDataDir = lambda: str(tmp_path)  # type: ignore[attr-defined]
    # context.py imports a few Units helpers via `App.Units.getSchema()` in
    # _units_scheme(), but only when build_context_snapshot runs. These tests
    # call the private helpers directly, so Units isn't needed.
    sys.modules["FreeCAD"] = stub


class _FakeDoc:
    def __init__(self, fcstd_path: Path):
        self.FileName = str(fcstd_path)
        self.Name = fcstd_path.stem


@pytest.fixture
def modules(tmp_path, monkeypatch):
    _install_freecad_stub(tmp_path)
    mod_dir = Path(__file__).resolve().parents[2] / "src" / "Mod" / "CADAgent"
    monkeypatch.syspath_prepend(str(mod_dir))
    for name in ("agent.context", "agent.memory", "agent"):
        sys.modules.pop(name, None)
    import agent.memory as memory
    # context.py imports FreeCADGui / PySide / claude_agent_sdk lazily in paths
    # we don't hit here. Ensure those imports exist before we pull in the helper
    # functions — we don't need their real behaviour.
    sys.modules.setdefault("FreeCADGui", types.ModuleType("FreeCADGui"))
    # agent.context imports gui_thread → needs PySide. Swap it for a stub.
    gui_thread = types.ModuleType("agent.gui_thread")
    gui_thread.run_sync = lambda fn, timeout=5.0: fn()  # type: ignore[attr-defined]
    sys.modules["agent.gui_thread"] = gui_thread
    import agent.context as context
    return memory, context


@pytest.fixture
def doc(tmp_path):
    return _FakeDoc(tmp_path / "design.FCStd")


def test_select_falls_back_to_tail_when_no_plan(modules, doc):
    memory, context = modules
    for i in range(5):
        memory.append_decision_record(doc, rationale=f"r{i}")

    decisions = memory.list_decisions(doc)
    rendered = context._select_relevant_decisions(doc, None, decisions)
    assert [d["rationale"] for d in rendered] == ["r2", "r3", "r4"]  # last 3


def test_select_uses_milestone_closure_when_decisions_are_tagged(modules, doc):
    memory, context = modules
    memory.set_plan(doc, [
        {"id": "m-001", "title": "foundation"},
        {"id": "m-002", "title": "features"},
    ])
    memory.update_milestone(doc, "m-002", status="active")

    d1 = memory.append_decision_record(doc, rationale="root for m-001", milestone="m-001")
    d2 = memory.append_decision_record(
        doc, rationale="builds on d-001", milestone="m-002", depends_on=[d1["id"]]
    )
    d3 = memory.append_decision_record(doc, rationale="unrelated m-002 decision", milestone="m-002")

    decisions = memory.list_decisions(doc)
    plan = memory.get_plan(doc)
    rendered = context._select_relevant_decisions(doc, plan, decisions)
    ids = [d["id"] for d in rendered]
    # Seeds: decisions tagged m-002 (d-002, d-003). Closure via depends_on pulls
    # in d-001. So all three should be rendered, in file order.
    assert ids == [d1["id"], d2["id"], d3["id"]]


def test_select_falls_back_to_tail_when_no_decisions_tagged_to_active(modules, doc):
    memory, context = modules
    memory.set_plan(doc, [{"id": "m-001", "title": "only"}])
    # Decisions exist but none carry a milestone — this is the v1-upgrade case.
    for i in range(4):
        memory.append_decision_record(doc, rationale=f"r{i}")
    decisions = memory.list_decisions(doc)
    plan = memory.get_plan(doc)
    rendered = context._select_relevant_decisions(doc, plan, decisions)
    # No seeds tagged to m-001 → tail fallback (last 3).
    assert [d["rationale"] for d in rendered] == ["r1", "r2", "r3"]


def test_format_decision_surfaces_typed_fields(modules, doc):
    _, context = modules
    entry = {
        "id": "d-007",
        "ts": "2026-04-23T10:00:00",
        "goal": "pick wall thickness",
        "choice": "3.2 mm",
        "rationale": "matches off-the-shelf sheet stock",
        "constraints": ["stiffness >= X", "weight < Y"],
        "depends_on": ["d-003"],
    }
    line = context._format_decision(entry)
    assert "d-007" in line
    assert "goal='pick wall thickness'" in line
    assert "chose='3.2 mm'" in line
    assert "because matches off-the-shelf" in line
    assert "depends_on=['d-003']" in line


def test_format_decision_handles_empty_record(modules, doc):
    _, context = modules
    line = context._format_decision({"id": "d-001", "ts": "t"})
    assert line == "  - [t] d-001"  # just the header; no empty bits
