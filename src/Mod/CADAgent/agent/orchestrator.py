# SPDX-License-Identifier: LGPL-2.1-or-later
"""Plan/execute orchestrator (Phase 5).

The runtime stays a single-agent, single-turn loop. What changes is the
per-turn prompt: the orchestrator reads the plan state from the sidecar
memory and prepends an instruction block telling the agent which phase
of the milestone lifecycle it's in. The agent drives transitions by
calling ``emit_plan`` / ``mark_milestone_*`` tools — no Python-side
state machine required.

Three phases the agent can be in:

- ``plan``      No plan exists. Emit one before doing any work.
- ``execute``   A milestone is active or pending. Advance it.
- ``review``    All milestones terminal. Report and stop, or start fresh.

Why prompt-driven and not code-driven:

- The SDK's ``permission_mode="plan"`` would suppress ``emit_plan`` itself.
  We want ``emit_plan`` to actually run, so plan mode is too blunt.
- The milestone state machine already lives in ``agent/memory.py``.
  Duplicating it in the orchestrator would risk drift.
- Single-turn execution is simpler to reason about under FreeCAD's
  GUI-thread constraints than multi-turn orchestration in Python.
"""

from __future__ import annotations

from . import memory as project_memory


PHASE_PLAN = "plan"
PHASE_EXECUTE = "execute"
PHASE_REVIEW = "review"


def current_phase(doc) -> str:
    """Return which lifecycle phase the agent should enter this turn."""
    plan = project_memory.get_plan(doc) if doc is not None else None
    if not plan or not (plan.get("milestones") or []):
        return PHASE_PLAN
    statuses = [m.get("status") for m in plan["milestones"]]
    if all(s in ("done", "failed") for s in statuses):
        return PHASE_REVIEW
    return PHASE_EXECUTE


def _criterion_bullets(items: list[str]) -> str:
    if not items:
        return "    (none specified)"
    return "\n".join(f"    - {line}" for line in items)


def _render_plan_preamble() -> str:
    return (
        "## Orchestrator — PLAN phase\n"
        "No design plan exists yet for this document. Before you call any "
        "mutating CAD tool, break the user's request into milestones and "
        "call `emit_plan(milestones=[...])` as your FIRST tool call.\n\n"
        "Milestone shape:\n"
        "  {title, acceptance_criteria: [...], tool_hints: [...]}\n\n"
        "Keep it to 1–6 milestones. Each milestone should be small enough to "
        "complete in one session and large enough to be meaningful (not a "
        "single tool call). After emit_plan returns, mark the first milestone "
        "active with `mark_milestone_active(milestone_id=...)` and proceed to "
        "execute it."
    )


def _render_execute_preamble(active: dict, plan: dict) -> str:
    status = active.get("status", "pending")
    lines = [
        "## Orchestrator — EXECUTE phase",
        f"You are working on milestone **{active.get('id','?')} — {active.get('title','')}** (status: {status}).",
        "Acceptance criteria:",
        _criterion_bullets(active.get("acceptance_criteria") or []),
    ]
    hints = active.get("tool_hints") or []
    if hints:
        lines.append(f"Suggested tools: {', '.join(hints)}")
    if status == "pending":
        lines.append(
            "First action this turn: call `mark_milestone_active(milestone_id="
            f"'{active.get('id','')}')` to signal the transition, then execute "
            "toward the acceptance criteria."
        )
    else:
        lines.append(
            "Continue executing. When the acceptance criteria are satisfied AND "
            "the most recent `verify_*` call confirms valid geometry, call "
            f"`mark_milestone_done(milestone_id='{active.get('id','')}')`. "
            "If the milestone is blocked by something the plan did not "
            "anticipate, call `mark_milestone_failed(milestone_id='"
            f"{active.get('id','')}', notes='...')` and explain what went wrong — "
            "do NOT silently skip it."
        )
    total = len(plan.get("milestones") or [])
    done = sum(1 for m in plan.get("milestones", []) if m.get("status") == "done")
    lines.append(f"Progress: {done}/{total} milestones complete.")
    return "\n".join(lines)


def _render_review_preamble(plan: dict) -> str:
    ms = plan.get("milestones") or []
    done = sum(1 for m in ms if m.get("status") == "done")
    failed = sum(1 for m in ms if m.get("status") == "failed")
    lines = [
        "## Orchestrator — REVIEW phase",
        f"All milestones in plan {plan.get('id','?')} are terminal ({done} done, {failed} failed).",
    ]
    if failed:
        lines.append(
            "At least one milestone failed. Consider delegating to the "
            "`reviewer` subagent for a final independent check, then ask the "
            "user whether to replan the failed milestones or accept the "
            "current state."
        )
    else:
        lines.append(
            "Delegate to the `reviewer` subagent for a final check, summarise "
            "the result, and stop. Do NOT emit a new plan unless the user "
            "explicitly asks for more work."
        )
    return "\n".join(lines)


def preamble_for(doc) -> str:
    """Produce the orchestrator preamble to prepend to the user's message."""
    if doc is None:
        return ""
    phase = current_phase(doc)
    if phase == PHASE_PLAN:
        return _render_plan_preamble()
    plan = project_memory.get_plan(doc) or {}
    if phase == PHASE_REVIEW:
        return _render_review_preamble(plan)
    active = project_memory.active_milestone(doc)
    if active is None:  # defensive — shouldn't happen in execute phase
        return ""
    return _render_execute_preamble(active, plan)
