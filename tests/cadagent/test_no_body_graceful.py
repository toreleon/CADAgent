"""Error-recovery: agent asked to Pad on a fresh doc with no Body.

Two acceptable outcomes — both must avoid crashing the FreeCAD process or
emitting Python tracebacks to stderr:

1. Agent self-recovers: creates a Body + Sketch before padding, ends up with a
   valid solid.
2. Agent gives up gracefully: no valid solid, tool calls return is_error=True
   (agent reports the problem as text) — doc stays empty but undamaged.
"""

from __future__ import annotations

import shutil

import pytest

from .replay import run_agent


pytestmark = pytest.mark.live_llm


def test_pad_on_empty_doc_does_not_crash(tmp_path, transport_env, empty_doc):
    work_doc = tmp_path / "empty.FCStd"
    shutil.copy(empty_doc, work_doc)

    trace = run_agent(
        "Please Pad a 10x10 square 3 mm tall in this document. "
        "Do not use Tier-A macros. Use the Part Design pad tool directly.",
        tmpdir=tmp_path,
        doc=work_doc,
        save_as=work_doc,
        timeout_s=180.0,
    )

    # Harness-level: no process crash, no panel-level exception trace.
    assert trace.returncode in (0, 1), f"FreeCADCmd crashed: rc={trace.returncode} stderr={trace.stderr[-500:]}"
    assert "Traceback" not in trace.stderr, f"unhandled exception leaked:\n{trace.stderr[-1000:]}"
    assert trace.errors == [], f"panel errors: {trace.errors}"

    # The agent should at least attempt recovery by making tool calls.
    tool_uses = [e for e in trace.trace if e.get("kind") == "tool_use"]
    assert tool_uses, "agent made no tool calls — cannot assess recovery behaviour"

    # A ResultMessage must mark the turn complete (success or graceful error).
    result_events = [e for e in trace.trace if e.get("kind") == "result"]
    assert result_events, "turn never completed with a ResultMessage"
