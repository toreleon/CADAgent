"""Phase 1 smoke test: proves the harness end-to-end.

The prompt is deliberately trivial and box-dimensioned so both Tier-A
(``make_parametric_box``) and Tier-C (``make_box``) tool choices are
acceptable. We assert on *what must be true of the resulting geometry*,
not on which tool name the agent picked.
"""

from __future__ import annotations

import pytest

from .replay import run_agent


pytestmark = pytest.mark.live_llm


def test_make_box_creates_single_valid_solid(tmp_path, transport_env):
    trace = run_agent(
        "Create a box with Length=20, Width=10, Height=5. Do not add anything else.",
        tmpdir=tmp_path,
        timeout_s=180.0,
    )

    # Harness-level: driver finished cleanly, no Qt/thread explosions.
    assert not trace.timed_out, f"agent timed out after {trace.elapsed_s:.1f}s"
    assert trace.returncode in (0, 1), f"FreeCADCmd crashed: {trace.stderr[-1000:]}"
    assert trace.errors == [], f"panel recorded errors: {trace.errors}"

    # Agent invoked at least one cad tool without is_error. Other tool names
    # (AskUserQuestion, Agent, built-in SDK helpers) are expected once the
    # orchestrator's lifecycle is active — we only require at least one
    # successful mcp__cad__ tool call.
    good = trace.successful_tool_names()
    assert good, f"no successful tool calls; trace={[e for e in trace.trace if e.get('kind')=='tool_use']}"
    cad_calls = [n for n in good if n.startswith("mcp__cad__")]
    assert cad_calls, f"no mcp__cad__ tool calls in sequence {good}"

    # Topology: at least one finite-volume solid with box dims == 20,10,5.
    # Tier-A macros produce a Body+Sketch+Pad hierarchy; Tier-C returns a
    # single CSG Box. Both are acceptable — we only require one correctly
    # dimensioned valid solid to exist in the doc.
    shapes = trace.shape_objects
    assert shapes, "no finite-volume solids in the final doc"

    target = sorted([20.0, 10.0, 5.0])
    matches = [
        s for s in shapes
        if sorted([s["bbox"]["xlen"], s["bbox"]["ylen"], s["bbox"]["zlen"]]) == pytest.approx(target, abs=0.01)
        and s["is_valid_solid"]
        and s["volume"] == pytest.approx(20 * 10 * 5, rel=1e-3)
    ]
    assert matches, (
        f"no 20x10x5 valid solid found; got dims "
        f"{[(s['name'], s['bbox']['xlen'], s['bbox']['ylen'], s['bbox']['zlen']) for s in shapes]}"
    )
