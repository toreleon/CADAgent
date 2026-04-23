# SPDX-License-Identifier: LGPL-2.1-or-later
"""Planning & structured-decision tools surfaced to the agent.

These tools live on top of ``agent/memory.py``'s v2 schema. They are the only
sanctioned write path for milestone plans and typed decision records — the
orchestrator reads the sidecar, picks the next milestone, and the agent
reports back via these tools.

All writes go through ``memory.save`` which does an atomic rename, so a crash
mid-turn can't half-write the sidecar. Reads are cheap JSON loads.

Tool inventory:

- ``emit_plan``            — Planner submits a full milestone list (plan mode).
- ``record_decision``      — Write a typed decision record with depends_on graph.
- ``list_decisions``       — Read-only dump of decision records.
- ``mark_milestone_active``, ``mark_milestone_done``, ``mark_milestone_failed``
                           — Executor transitions the current milestone.
- ``get_active_milestone`` — Read-only hint for the agent about what it's doing.
"""

from __future__ import annotations

from claude_agent_sdk import tool
from mcp.types import ToolAnnotations

from ..gui_thread import run_sync
from .. import memory as project_memory
from ._shared import ok, err, resolve_doc


_READ_ONLY = ToolAnnotations(readOnlyHint=True)


# ---------------------------------------------------------------------------
# plan I/O
# ---------------------------------------------------------------------------


_MILESTONE_ITEM_SCHEMA = {
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


@tool(
    "emit_plan",
    (
        "Submit a milestone plan for this design session. Replaces any "
        "existing plan. Each milestone must have a title; optional "
        "acceptance_criteria describe what 'done' means, and tool_hints help "
        "the orchestrator route milestones to specialist subagents. Call this "
        "only from plan mode; the executor resumes per milestone afterwards."
    ),
    {
        "type": "object",
        "properties": {
            "milestones": {
                "type": "array",
                "items": _MILESTONE_ITEM_SCHEMA,
                "minItems": 1,
            },
            "plan_id": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["milestones"],
    },
)
async def emit_plan(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        plan = project_memory.set_plan(
            doc, args["milestones"], plan_id=args.get("plan_id")
        )
        return {"plan": plan}

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(str(exc))


@tool(
    "get_active_milestone",
    (
        "Return the milestone the executor is currently working on, or the "
        "next pending one. Returns {milestone: null} if there is no plan."
    ),
    {"doc": str},
    annotations=_READ_ONLY,
)
async def get_active_milestone(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        return {"milestone": project_memory.active_milestone(doc)}

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(str(exc))


# ---------------------------------------------------------------------------
# milestone transitions
# ---------------------------------------------------------------------------


def _milestone_transition_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "milestone_id": {"type": "string"},
            "notes": {"type": "string"},
            "session_id": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["milestone_id"],
    }


@tool(
    "mark_milestone_active",
    (
        "Mark a milestone as in-progress. The orchestrator normally does this; "
        "the agent only calls it when self-driving without a planner."
    ),
    _milestone_transition_schema(),
)
async def mark_milestone_active(args):
    return _update_milestone_via_args(args, status="active")


@tool(
    "mark_milestone_done",
    (
        "Mark the current milestone as complete. Call this when the "
        "acceptance_criteria are satisfied AND verify_* tools confirm valid "
        "geometry. The orchestrator advances to the next milestone."
    ),
    _milestone_transition_schema(),
)
async def mark_milestone_done(args):
    return _update_milestone_via_args(args, status="done")


@tool(
    "mark_milestone_failed",
    (
        "Mark the current milestone as failed. Supply 'notes' with a short "
        "diagnosis so the planner can re-plan. The orchestrator will not "
        "auto-advance; it hands control back to the planner."
    ),
    _milestone_transition_schema(),
)
async def mark_milestone_failed(args):
    return _update_milestone_via_args(args, status="failed")


def _update_milestone_via_args(args, *, status: str):
    def _do():
        doc = resolve_doc(args.get("doc"))
        updates: dict = {"status": status}
        if args.get("notes") is not None:
            updates["notes"] = args["notes"]
        if args.get("session_id") is not None:
            updates["session_id"] = args["session_id"]
        m = project_memory.update_milestone(doc, args["milestone_id"], **updates)
        if m is None:
            raise ValueError(
                f"no milestone with id {args['milestone_id']!r}; call get_active_milestone first"
            )
        return {"milestone": m}

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(str(exc))


# ---------------------------------------------------------------------------
# typed decision records
# ---------------------------------------------------------------------------


@tool(
    "record_decision",
    (
        "Record a typed design decision that must outlive this turn. Fields: "
        "goal (what problem), constraints (list), alternatives (list of options "
        "considered), choice (what was picked), rationale (why). Use depends_on "
        "to link to earlier decision ids (d-NNN) when this choice only makes "
        "sense given those — the context snapshot uses that graph to filter "
        "what's relevant per milestone."
    ),
    {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "alternatives": {"type": "array", "items": {"type": "string"}},
            "choice": {"type": "string"},
            "rationale": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
            "milestone": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": [],
    },
)
async def record_decision(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        entry = project_memory.append_decision_record(
            doc,
            goal=args.get("goal", "") or "",
            constraints=args.get("constraints") or [],
            alternatives=args.get("alternatives") or [],
            choice=args.get("choice", "") or "",
            rationale=args.get("rationale", "") or "",
            depends_on=args.get("depends_on") or [],
            milestone=args.get("milestone"),
        )
        return {"decision": entry}

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(str(exc))


@tool(
    "list_decisions",
    (
        "Return every typed decision record for this document. Useful when the "
        "agent needs to review prior context before committing to a new choice."
    ),
    {"doc": str},
    annotations=_READ_ONLY,
)
async def list_decisions(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        return {"decisions": project_memory.list_decisions(doc)}

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(str(exc))


# ---------------------------------------------------------------------------
# registry hooks used by tools/__init__.py
# ---------------------------------------------------------------------------


TOOL_FUNCS = [
    emit_plan,
    get_active_milestone,
    mark_milestone_active,
    mark_milestone_done,
    mark_milestone_failed,
    record_decision,
    list_decisions,
]

TOOL_NAMES = [
    "emit_plan",
    "get_active_milestone",
    "mark_milestone_active",
    "mark_milestone_done",
    "mark_milestone_failed",
    "record_decision",
    "list_decisions",
]
