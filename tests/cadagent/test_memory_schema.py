"""Unit tests for memory.py schema v2: migration, decision closure, plan state.

These don't hit the LLM and don't need FreeCAD running, but memory.py imports
``FreeCAD as App`` at module top. We satisfy that with a tiny stub so tests
run under plain pytest (``pytest tests/cadagent/test_memory_schema.py``).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest


# --- FreeCAD stub so memory.py imports cleanly under plain pytest ----------


def _install_freecad_stub(tmp_path: Path) -> None:
    if "FreeCAD" in sys.modules:
        return
    stub = types.ModuleType("FreeCAD")
    unsaved = tmp_path / "unsaved"
    unsaved.mkdir(parents=True, exist_ok=True)
    stub.getUserAppDataDir = lambda: str(tmp_path)  # type: ignore[attr-defined]
    sys.modules["FreeCAD"] = stub


class _FakeDoc:
    """Minimal stand-in: memory.sidecar_path() only reads .FileName."""
    def __init__(self, fcstd_path: Path):
        self.FileName = str(fcstd_path)
        self.Name = fcstd_path.stem


@pytest.fixture
def memory_module(tmp_path, monkeypatch):
    _install_freecad_stub(tmp_path)
    # Ensure src/Mod/CADAgent on path so `import agent.memory` resolves.
    mod_dir = Path(__file__).resolve().parents[2] / "src" / "Mod" / "CADAgent"
    monkeypatch.syspath_prepend(str(mod_dir))
    # Fresh import each session so tests see a clean module state.
    if "agent.memory" in sys.modules:
        del sys.modules["agent.memory"]
    if "agent" in sys.modules:
        del sys.modules["agent"]
    import agent.memory as m  # type: ignore
    return m


@pytest.fixture
def doc(tmp_path):
    return _FakeDoc(tmp_path / "design.FCStd")


# --- migration -------------------------------------------------------------


def test_empty_load_returns_v2_defaults(memory_module, doc):
    data = memory_module.load(doc)
    assert data["schema_version"] == 2
    assert data["decisions"] == []
    assert data["plan"] is None
    assert data["parameters"] == {}


def test_v1_sidecar_upgrades_on_load(memory_module, doc):
    # Write a v1-shaped sidecar directly to disk.
    sidecar = Path(memory_module.sidecar_path(doc))
    sidecar.write_text(json.dumps({
        "schema_version": 1,
        "design_intent": "prototype bracket",
        "decisions": [
            {"ts": "2026-04-01T10:00:00", "text": "use 3mm aluminium"},
            {"ts": "2026-04-02T10:00:00", "text": "four M6 fasteners"},
        ],
    }))

    data = memory_module.load(doc)

    assert data["schema_version"] == 2  # in-memory shape is v2
    assert len(data["decisions"]) == 2
    first = data["decisions"][0]
    assert first["id"] == "d-legacy-000"
    assert first["rationale"] == "use 3mm aluminium"
    assert first["text"] == "use 3mm aluminium"  # context.py legacy mirror
    assert first["constraints"] == []
    assert first["depends_on"] == []

    # Disk file unchanged until a writer runs.
    on_disk = json.loads(sidecar.read_text())
    assert on_disk["schema_version"] == 1


def test_append_decision_record_allocates_fresh_id_and_persists(memory_module, doc):
    r1 = memory_module.append_decision_record(doc, goal="g1", rationale="r1")
    r2 = memory_module.append_decision_record(
        doc, goal="g2", rationale="r2", depends_on=[r1["id"]]
    )

    assert r1["id"] == "d-001"
    assert r2["id"] == "d-002"
    assert r2["depends_on"] == ["d-001"]
    assert memory_module.list_decisions(doc) == [r1, r2]
    assert memory_module.get_decision(doc, "d-002") == r2
    assert memory_module.get_decision(doc, "nope") is None


def test_legacy_append_decision_shim_creates_v2_record(memory_module, doc):
    entry = memory_module.append_decision(doc, "use 6061-T6")
    assert entry["id"] == "d-001"
    assert entry["rationale"] == "use 6061-T6"
    assert entry["text"] == "use 6061-T6"  # back-compat for context.py


# --- decision_closure ------------------------------------------------------


def test_decision_closure_follows_depends_on_graph(memory_module, doc):
    a = memory_module.append_decision_record(doc, rationale="root A")
    b = memory_module.append_decision_record(doc, rationale="B", depends_on=[a["id"]])
    c = memory_module.append_decision_record(doc, rationale="C unrelated")
    d = memory_module.append_decision_record(
        doc, rationale="D needs B+C", depends_on=[b["id"], c["id"]]
    )

    closure = memory_module.decision_closure(doc, [d["id"]])
    ids = [x["id"] for x in closure]
    # All four must be reachable; order is file-order-stable.
    assert ids == [a["id"], b["id"], c["id"], d["id"]]

    # Isolated seed — no dependencies beyond itself.
    closure_a = memory_module.decision_closure(doc, [a["id"]])
    assert [x["id"] for x in closure_a] == [a["id"]]


def test_decision_closure_drops_unknown_seed_ids(memory_module, doc):
    a = memory_module.append_decision_record(doc, rationale="a")
    closure = memory_module.decision_closure(doc, ["d-missing", a["id"]])
    assert [x["id"] for x in closure] == [a["id"]]


def test_decision_closure_survives_circular_depends_on(memory_module, doc):
    # Craft a cycle by writing the sidecar directly — the API won't let you
    # introduce one in normal use, but we must not loop forever if one sneaks in.
    sidecar = Path(memory_module.sidecar_path(doc))
    sidecar.write_text(json.dumps({
        "schema_version": 2,
        "decisions": [
            {"id": "d-1", "rationale": "x", "depends_on": ["d-2"]},
            {"id": "d-2", "rationale": "y", "depends_on": ["d-1"]},
        ],
    }))
    closure = memory_module.decision_closure(doc, ["d-1"])
    assert {x["id"] for x in closure} == {"d-1", "d-2"}


# --- plan + milestones -----------------------------------------------------


def test_set_plan_creates_pending_milestones(memory_module, doc):
    plan = memory_module.set_plan(doc, [
        {"id": "m-001", "title": "create body", "acceptance_criteria": ["body exists"]},
        {"title": "add sketch", "tool_hints": ["create_sketch", "add_sketch_geometry"]},
    ])
    assert plan["status"] == "active"
    assert plan["milestones"][0]["id"] == "m-001"
    assert plan["milestones"][0]["status"] == "pending"
    assert plan["milestones"][1]["id"] == "m-002"  # auto-assigned
    assert plan["milestones"][1]["tool_hints"] == ["create_sketch", "add_sketch_geometry"]


def test_update_milestone_timestamps_transitions(memory_module, doc):
    memory_module.set_plan(doc, [
        {"id": "m-001", "title": "t1"},
        {"id": "m-002", "title": "t2"},
    ])

    m = memory_module.update_milestone(doc, "m-001", status="active", session_id="s-1")
    assert m["status"] == "active"
    assert m["started_ts"] is not None
    assert m["completed_ts"] is None
    assert m["session_id"] == "s-1"

    m = memory_module.update_milestone(doc, "m-001", status="done")
    assert m["completed_ts"] is not None

    # Plan is still active — m-002 is pending.
    plan = memory_module.get_plan(doc)
    assert plan["status"] == "active"

    memory_module.update_milestone(doc, "m-002", status="failed")
    plan = memory_module.get_plan(doc)
    assert plan["status"] == "done"  # all terminal


def test_update_milestone_rejects_invalid_status(memory_module, doc):
    memory_module.set_plan(doc, [{"id": "m-001", "title": "x"}])
    with pytest.raises(ValueError):
        memory_module.update_milestone(doc, "m-001", status="bogus")


def test_update_milestone_returns_none_on_missing_id(memory_module, doc):
    memory_module.set_plan(doc, [{"id": "m-001", "title": "x"}])
    assert memory_module.update_milestone(doc, "m-999", status="active") is None


def test_active_milestone_picks_active_before_pending(memory_module, doc):
    memory_module.set_plan(doc, [
        {"id": "m-001", "title": "a"},
        {"id": "m-002", "title": "b"},
    ])
    # Nothing active yet — first pending wins.
    assert memory_module.active_milestone(doc)["id"] == "m-001"

    memory_module.update_milestone(doc, "m-002", status="active")
    # Even though m-002 came second in the list, it's the active one now.
    assert memory_module.active_milestone(doc)["id"] == "m-002"


def test_active_milestone_none_when_no_plan(memory_module, doc):
    assert memory_module.active_milestone(doc) is None


# --- parameter path (unchanged behaviour) ---------------------------------


def test_set_parameter_roundtrips(memory_module, doc):
    spec = memory_module.set_parameter(doc, "Thickness", 3.2, "mm", "pilot")
    assert spec == {"value": 3.2, "unit": "mm", "note": "pilot"}
    assert memory_module.get_parameters(doc) == {"Thickness": spec}
