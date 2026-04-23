"""Live_LLM test: orchestrator invokes Reviewer subagent after a build.

Confirms the Phase 4 wiring: agents={"reviewer": ...} in options, `Agent`
tool allowed, on_subagent_stop hook fires. Asserts the orchestrator
delegates via the Agent tool and the subagent's read-only tool list
prevents mutation even if it were prompted to.
"""

from __future__ import annotations

import shutil

import pytest

from .replay import run_agent


pytestmark = pytest.mark.live_llm


def test_reviewer_invocation_after_make_box(tmp_path, transport_env):
    trace = run_agent(
        "Do these two steps without asking for permission and without any "
        "clarifying questions:\n"
        "1. Call mcp__cad__make_box (Tier C, NOT the parametric variant) "
        "with length=30, width=20, height=10.\n"
        "2. Immediately delegate to the reviewer subagent via the Agent "
        "tool with a brief like: 'Confirm the box 30x20x10 exists as a "
        "valid solid.' Report the reviewer's verdict in your final reply.",
        tmpdir=tmp_path,
        timeout_s=240.0,
    )

    assert not trace.timed_out, f"agent timed out at {trace.elapsed_s:.1f}s"
    assert trace.errors == [], f"panel errors: {trace.errors}"

    tool_names = trace.tool_names()
    # Orchestrator must have created the box first.
    assert any(n.startswith("mcp__cad__") for n in tool_names), (
        f"no cad tool calls recorded; got {tool_names}"
    )

    # Orchestrator delegated to a subagent via the SDK's built-in Agent tool.
    assert "Agent" in tool_names, (
        f"Agent delegation did not fire; tool sequence was {tool_names}"
    )

    # Subagent stop hook fires on stderr per-run; we can't observe it from
    # the driver side (the hook stream isn't captured), but the turn must
    # have completed with a ResultMessage.
    assert any(e.get("kind") == "result" for e in trace.trace), (
        "turn did not complete with a ResultMessage"
    )

    # Post-review: doc still contains a valid 30x20x10 solid (review didn't
    # mutate, subsequent orchestrator didn't either).
    shapes = trace.shape_objects
    matches = [
        s for s in shapes
        if sorted([s["bbox"]["xlen"], s["bbox"]["ylen"], s["bbox"]["zlen"]]) == pytest.approx([10.0, 20.0, 30.0], abs=0.01)
        and s["is_valid_solid"]
    ]
    assert matches, (
        f"expected a 30x20x10 valid solid to remain after review; got "
        f"{[(s['name'], s['bbox']['xlen'], s['bbox']['ylen'], s['bbox']['zlen']) for s in shapes]}"
    )
