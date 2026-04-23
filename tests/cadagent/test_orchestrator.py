"""Unit tests for orchestrator.py phase detection + preamble rendering.

Pure-data: reads memory state, produces strings. No FreeCAD, no SDK.
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
    sys.modules["FreeCAD"] = stub


class _FakeDoc:
    def __init__(self, fcstd_path: Path):
        self.FileName = str(fcstd_path)
        self.Name = fcstd_path.stem


@pytest.fixture
def orch(tmp_path, monkeypatch):
    _install_freecad_stub(tmp_path)
    mod_dir = Path(__file__).resolve().parents[2] / "src" / "Mod" / "CADAgent"
    monkeypatch.syspath_prepend(str(mod_dir))
    for name in ("agent.orchestrator", "agent.memory", "agent"):
        sys.modules.pop(name, None)
    import agent.memory as memory
    import agent.orchestrator as orchestrator
    return memory, orchestrator


@pytest.fixture
def doc(tmp_path):
    return _FakeDoc(tmp_path / "design.FCStd")


def test_current_phase_is_plan_when_no_plan_exists(orch, doc):
    _, orchestrator = orch
    assert orchestrator.current_phase(doc) == "plan"


def test_current_phase_is_plan_when_plan_is_empty(orch, doc):
    memory, orchestrator = orch
    memory.set_plan(doc, [])
    assert orchestrator.current_phase(doc) == "plan"


def test_current_phase_is_execute_with_pending_milestones(orch, doc):
    memory, orchestrator = orch
    memory.set_plan(doc, [{"title": "a"}, {"title": "b"}])
    assert orchestrator.current_phase(doc) == "execute"


def test_current_phase_is_execute_with_active_milestone(orch, doc):
    memory, orchestrator = orch
    memory.set_plan(doc, [{"id": "m-001", "title": "a"}, {"id": "m-002", "title": "b"}])
    memory.update_milestone(doc, "m-001", status="active")
    assert orchestrator.current_phase(doc) == "execute"


def test_current_phase_is_review_when_all_terminal(orch, doc):
    memory, orchestrator = orch
    memory.set_plan(doc, [{"id": "m-001", "title": "a"}])
    memory.update_milestone(doc, "m-001", status="done")
    assert orchestrator.current_phase(doc) == "review"


def test_preamble_plan_mentions_emit_plan_first(orch, doc):
    _, orchestrator = orch
    out = orchestrator.preamble_for(doc)
    assert "PLAN phase" in out
    assert "emit_plan" in out


def test_preamble_execute_includes_active_milestone_details(orch, doc):
    memory, orchestrator = orch
    memory.set_plan(doc, [
        {"id": "m-001", "title": "create body",
         "acceptance_criteria": ["body exists"],
         "tool_hints": ["create_body", "create_sketch"]},
        {"id": "m-002", "title": "pad"},
    ])
    memory.update_milestone(doc, "m-001", status="active")
    out = orchestrator.preamble_for(doc)

    assert "EXECUTE phase" in out
    assert "m-001" in out and "create body" in out
    assert "body exists" in out  # acceptance criterion
    assert "create_body" in out  # tool hint
    assert "mark_milestone_done" in out
    assert "Progress: 0/2" in out


def test_preamble_execute_for_pending_tells_agent_to_activate(orch, doc):
    memory, orchestrator = orch
    memory.set_plan(doc, [{"id": "m-001", "title": "t"}])
    out = orchestrator.preamble_for(doc)
    assert "mark_milestone_active" in out


def test_preamble_review_clean_suggests_reviewer_delegation(orch, doc):
    memory, orchestrator = orch
    memory.set_plan(doc, [{"id": "m-001", "title": "a"}])
    memory.update_milestone(doc, "m-001", status="done")
    out = orchestrator.preamble_for(doc)
    assert "REVIEW phase" in out
    assert "reviewer" in out
    assert "Do NOT" in out  # stop-rather-than-replan rule


def test_preamble_review_failure_allows_replan(orch, doc):
    memory, orchestrator = orch
    memory.set_plan(doc, [{"id": "m-001", "title": "a"}])
    memory.update_milestone(doc, "m-001", status="failed", notes="oops")
    out = orchestrator.preamble_for(doc)
    assert "REVIEW phase" in out
    assert "replan" in out.lower()


def test_preamble_returns_empty_when_no_doc(orch):
    _, orchestrator = orch
    assert orchestrator.preamble_for(None) == ""
