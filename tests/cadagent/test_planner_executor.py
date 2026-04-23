"""Live_LLM test: planner → executor lifecycle across a multi-step request.

A prompt that clearly needs a plan (two distinct features) should cause the
agent to:
  1. Call emit_plan(milestones=[...]) FIRST.
  2. Call mark_milestone_active / mark_milestone_done around each milestone.
  3. Finish with at least one active → done transition recorded in the
     sidecar.

We assert on the tool-call trace and the final sidecar JSON, not on model
text. Tool order tolerates the model reordering mark_* calls within a
milestone as long as emit_plan comes first overall.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from .replay import run_agent


pytestmark = pytest.mark.live_llm


def test_planner_then_executor_runs_a_two_milestone_build(tmp_path, transport_env, pad_on_rect):
    work_doc = tmp_path / "plate.FCStd"
    shutil.copy(pad_on_rect, work_doc)

    trace = run_agent(
        "The document has a 50x30x5 plate. Please:\n"
        "  1. Add four corner holes, 6 mm diameter, 6 mm inset from each edge.\n"
        "  2. Apply a 1 mm fillet to the outer top edges of the plate.\n"
        "These are two distinct features — use the milestone lifecycle and "
        "call emit_plan first. Do not ask me for permission between steps.",
        tmpdir=tmp_path,
        doc=work_doc,
        save_as=work_doc,
        timeout_s=300.0,
    )

    assert not trace.timed_out, f"timed out at {trace.elapsed_s:.1f}s"
    assert trace.errors == [], f"panel errors: {trace.errors}"

    tools = trace.tool_names()
    assert "mcp__cad__emit_plan" in tools, (
        f"agent did not emit a plan; tool trace was {tools}"
    )
    # emit_plan must come before any mutating CAD tool.
    first_mutating_idx = next(
        (i for i, t in enumerate(tools)
         if t.startswith("mcp__cad__") and t not in (
             "mcp__cad__emit_plan",
             "mcp__cad__mark_milestone_active",
             "mcp__cad__mark_milestone_done",
             "mcp__cad__mark_milestone_failed",
             "mcp__cad__get_active_milestone",
             "mcp__cad__list_decisions",
             "mcp__cad__read_project_memory",
             "mcp__cad__record_decision",
             "mcp__cad__list_documents",
             "mcp__cad__get_active_document",
             "mcp__cad__list_objects",
             "mcp__cad__get_object",
             "mcp__cad__get_selection",
             "mcp__cad__get_parameters",
             "mcp__cad__verify_sketch",
             "mcp__cad__verify_feature",
             "mcp__cad__preview_topology",
             "mcp__cad__render_view",
         )),
        None,
    )
    emit_idx = tools.index("mcp__cad__emit_plan")
    if first_mutating_idx is not None:
        assert emit_idx < first_mutating_idx, (
            f"emit_plan at index {emit_idx} came after first mutation at "
            f"index {first_mutating_idx}; tools={tools}"
        )

    # At least one milestone was marked done — confirms the executor closed
    # the loop rather than running open-loop and forgetting to transition.
    assert "mcp__cad__mark_milestone_done" in tools, (
        f"no mark_milestone_done call; tools={tools}"
    )

    # The sidecar on disk must reflect at least one done milestone.
    sidecar = work_doc.with_suffix(".cadagent.json")
    assert sidecar.exists(), f"sidecar {sidecar} missing; saved_as={trace.doc_out}"
    data = json.loads(sidecar.read_text())
    plan = data.get("plan") or {}
    milestones = plan.get("milestones") or []
    assert milestones, "plan has no milestones after the turn"
    done = [m for m in milestones if m.get("status") == "done"]
    assert done, (
        f"no milestone reached 'done' state; statuses="
        f"{[m.get('status') for m in milestones]}"
    )
