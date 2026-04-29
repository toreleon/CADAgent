# SPDX-License-Identifier: LGPL-2.1-or-later
"""Plan / milestone tools.

``plan_emit`` replaces any existing plan; milestone transitions advance
status. ``exit_plan_mode`` writes the plan markdown next to the .FCStd
and signals the runtime to leave plan mode for the next turn.
"""

from __future__ import annotations

from .. import memory as project_memory
from ._common import READ_ONLY, err, handle, ok, schema
from ._registry import cad_tool
from .categories import Category


_MILESTONE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "tool_hints": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["title"],
}


@cad_tool(
    "plan_emit",
    "Submit a milestone plan. Replaces any existing plan. Each milestone needs at least a title; acceptance_criteria define 'done'.",
    schema(
        milestones={"type": "array", "items": _MILESTONE_SCHEMA, "minItems": 1, "required": True},
        plan_id={"type": "string"},
    ),
    category=Category.MUTATING,
)
async def plan_emit(args):
    try:
        doc = handle(args)
        plan = project_memory.set_plan(doc, args["milestones"], plan_id=args.get("plan_id"))
        return ok({"plan": plan})
    except Exception as exc:
        return err(str(exc))


@cad_tool(
    "plan_active_get",
    "Return the currently active milestone, or the next pending one. {milestone: null} when no plan exists.",
    schema(),
    category=Category.READ,
    annotations=READ_ONLY,
)
async def plan_active_get(args):
    try:
        return ok({"milestone": project_memory.active_milestone(handle(args))})
    except Exception as exc:
        return err(str(exc))


def _transition(args: dict, status: str) -> dict:
    doc = handle(args)
    milestone_id = args.get("milestone_id")
    if not milestone_id:
        raise ValueError("milestone_id is required")
    updates: dict = {"status": status}
    if args.get("notes") is not None:
        updates["notes"] = args["notes"]
    if args.get("session_id") is not None:
        updates["session_id"] = args["session_id"]
    m = project_memory.update_milestone(doc, milestone_id, **updates)
    if m is None:
        raise ValueError(f"no milestone with id {milestone_id!r}")
    return {"milestone": m}


def _milestone_transition_schema() -> dict:
    return schema(
        milestone_id={"type": "string", "required": True},
        notes={"type": "string"},
        session_id={"type": "string"},
    )


@cad_tool("plan_milestone_activate", "Mark a milestone as 'active'.", _milestone_transition_schema(), category=Category.MUTATING)
async def plan_milestone_activate(args):
    try:
        return ok(_transition(args, "active"))
    except Exception as exc:
        return err(str(exc))


@cad_tool("plan_milestone_done", "Mark a milestone as 'done'. Call only after verifying geometry.", _milestone_transition_schema(), category=Category.MUTATING)
async def plan_milestone_done(args):
    try:
        return ok(_transition(args, "done"))
    except Exception as exc:
        return err(str(exc))


@cad_tool("plan_milestone_failed", "Mark a milestone as 'failed'. Include a short 'notes' diagnosis.", _milestone_transition_schema(), category=Category.MUTATING)
async def plan_milestone_failed(args):
    try:
        return ok(_transition(args, "failed"))
    except Exception as exc:
        return err(str(exc))


@cad_tool(
    "exit_plan_mode",
    "Leave plan mode and begin execution. Call this only after you have "
    "finished researching and have written a final plan summary. Pass the "
    "plan as a markdown string — it is saved to .cadagent.plan.md alongside "
    "the .FCStd and shown to the user for approval before any Bash / Write "
    "tools unlock.",
    schema(
        summary={"type": "string", "required": True},
    ),
    category=Category.MUTATING,
)
async def exit_plan_mode(args):
    """Persist the plan and signal the runtime to leave plan mode.

    The runtime intercepts this tool's use (permission hook shows the plan
    for approval) and its result (flips ``permission_mode`` to ``default``
    for the next turn).
    """
    try:
        doc = handle(args)
        summary = args.get("summary") or ""
        path = project_memory.write_plan_file(doc, summary)
        return ok({"plan_file": path, "bytes": len(summary)})
    except Exception as exc:
        return err(str(exc))


__all__ = [
    "exit_plan_mode",
    "plan_active_get",
    "plan_emit",
    "plan_milestone_activate",
    "plan_milestone_done",
    "plan_milestone_failed",
]
