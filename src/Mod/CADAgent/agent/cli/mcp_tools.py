# SPDX-License-Identifier: LGPL-2.1-or-later
"""MCP tools exposed to the standalone CLI agent.

Surface is deliberately narrow: sidecar memory + milestone planning, each
keyed by the .FCStd path the agent is working on. Everything else (doc
creation, geometry, verification) is handled via ``Bash`` + ``FreeCADCmd``.

Tool names are verbose on purpose — the agent picks them by name, so
``memory.parameter.set`` is clearer than ``set_parameter``. Namespacing with
``memory.`` / ``plan.`` lets the orchestrator scope subagents by prefix.

Each tool takes ``doc`` (absolute .FCStd path) — the sidecar lives next to it.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from claude_agent_sdk import tool
from mcp.types import ToolAnnotations

from .. import memory as project_memory
from .doc_handle import DocHandle


_READ_ONLY = ToolAnnotations(readOnlyHint=True)


def _ok(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps({"ok": True, **payload}, default=str)}]}


def _err(message: str, **extras: Any) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps({"ok": False, "error": message, **extras}, default=str)}],
        "isError": True,
    }


def _handle(args: dict) -> DocHandle:
    """Resolve the ``doc`` argument into a DocHandle, or raise."""
    path = (args or {}).get("doc")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("'doc' is required: absolute path to the .FCStd file")
    return DocHandle(path)


def _schema(**properties) -> dict:
    """Build a JSON Schema with ``doc`` pre-required and extras as given.

    The SDK's dict-shorthand marks every listed property required; the verbose
    form lets us separate required from optional.
    """
    required = ["doc"]
    props = {"doc": {"type": "string"}}
    for name, spec in properties.items():
        rq = spec.pop("required", False) if isinstance(spec, dict) else False
        props[name] = spec
        if rq:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


# ---------------------------------------------------------------------------
# memory tools
# ---------------------------------------------------------------------------


@tool(
    "memory_read",
    "Return the full project-memory sidecar (design_intent, parameters, decisions, plan, naming) for the given .FCStd.",
    _schema(),
    annotations=_READ_ONLY,
)
async def memory_read(args):
    try:
        return _ok(project_memory.load(_handle(args)))
    except Exception as exc:
        return _err(str(exc), traceback=traceback.format_exc(limit=4))


@tool(
    "memory_note_write",
    "Write a key/value into a top-level section of the sidecar (e.g. section='design_intent' or 'naming').",
    _schema(
        section={"type": "string", "required": True},
        key={"type": "string", "required": True},
        value={},  # any JSON value
    ),
)
async def memory_note_write(args):
    try:
        doc = _handle(args)
        section = args.get("section")
        key = args.get("key")
        if not section or not key:
            raise ValueError("section and key are required")
        if "value" not in args:
            raise ValueError("value is required")
        return _ok({"written": project_memory.write_note(doc, section, key, args["value"])})
    except Exception as exc:
        return _err(str(exc))


@tool(
    "memory_parameter_set",
    "Set a named design parameter (value + unit + optional note) in the sidecar. The agent's FreeCAD scripts may read these to drive geometry.",
    _schema(
        name={"type": "string", "required": True},
        value={"type": "number", "required": True},
        unit={"type": "string"},
        note={"type": "string"},
    ),
)
async def memory_parameter_set(args):
    try:
        doc = _handle(args)
        spec = project_memory.set_parameter(
            doc,
            args["name"],
            float(args["value"]),
            args.get("unit") or "mm",
            args.get("note") or "",
        )
        return _ok({"name": args["name"], **spec})
    except Exception as exc:
        return _err(str(exc))


@tool(
    "memory_parameters_get",
    "Return all named parameters recorded for this doc.",
    _schema(),
    annotations=_READ_ONLY,
)
async def memory_parameters_get(args):
    try:
        return _ok({"parameters": project_memory.get_parameters(_handle(args))})
    except Exception as exc:
        return _err(str(exc))


@tool(
    "memory_decision_record",
    "Record a typed design decision (goal/constraints/alternatives/choice/rationale/depends_on). Depends_on ids link to earlier decisions (d-NNN).",
    _schema(
        goal={"type": "string"},
        constraints={"type": "array", "items": {"type": "string"}},
        alternatives={"type": "array", "items": {"type": "string"}},
        choice={"type": "string"},
        rationale={"type": "string"},
        depends_on={"type": "array", "items": {"type": "string"}},
        milestone={"type": "string"},
    ),
)
async def memory_decision_record(args):
    try:
        doc = _handle(args)
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
        return _ok({"decision": entry})
    except Exception as exc:
        return _err(str(exc))


@tool(
    "memory_decisions_list",
    "Dump every decision record for this doc (for re-grounding in later turns).",
    _schema(),
    annotations=_READ_ONLY,
)
async def memory_decisions_list(args):
    try:
        return _ok({"decisions": project_memory.list_decisions(_handle(args))})
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# plan / milestone tools
# ---------------------------------------------------------------------------


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


@tool(
    "plan_emit",
    "Submit a milestone plan. Replaces any existing plan. Each milestone needs at least a title; acceptance_criteria define 'done'.",
    _schema(
        milestones={"type": "array", "items": _MILESTONE_SCHEMA, "minItems": 1, "required": True},
        plan_id={"type": "string"},
    ),
)
async def plan_emit(args):
    try:
        doc = _handle(args)
        plan = project_memory.set_plan(doc, args["milestones"], plan_id=args.get("plan_id"))
        return _ok({"plan": plan})
    except Exception as exc:
        return _err(str(exc))


@tool(
    "plan_active_get",
    "Return the currently active milestone, or the next pending one. {milestone: null} when no plan exists.",
    _schema(),
    annotations=_READ_ONLY,
)
async def plan_active_get(args):
    try:
        return _ok({"milestone": project_memory.active_milestone(_handle(args))})
    except Exception as exc:
        return _err(str(exc))


def _transition(args: dict, status: str) -> dict:
    doc = _handle(args)
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
    return _schema(
        milestone_id={"type": "string", "required": True},
        notes={"type": "string"},
        session_id={"type": "string"},
    )


@tool("plan_milestone_activate", "Mark a milestone as 'active'.", _milestone_transition_schema())
async def plan_milestone_activate(args):
    try:
        return _ok(_transition(args, "active"))
    except Exception as exc:
        return _err(str(exc))


@tool("plan_milestone_done", "Mark a milestone as 'done'. Call only after verifying geometry.", _milestone_transition_schema())
async def plan_milestone_done(args):
    try:
        return _ok(_transition(args, "done"))
    except Exception as exc:
        return _err(str(exc))


@tool("plan_milestone_failed", "Mark a milestone as 'failed'. Include a short 'notes' diagnosis.", _milestone_transition_schema())
async def plan_milestone_failed(args):
    try:
        return _ok(_transition(args, "failed"))
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# registry helpers used by runtime.py
# ---------------------------------------------------------------------------


TOOL_FUNCS = [
    memory_read,
    memory_note_write,
    memory_parameter_set,
    memory_parameters_get,
    memory_decision_record,
    memory_decisions_list,
    plan_emit,
    plan_active_get,
    plan_milestone_activate,
    plan_milestone_done,
    plan_milestone_failed,
]

TOOL_NAMES = [f.name if hasattr(f, "name") else f.__name__ for f in TOOL_FUNCS]


def allowed_tool_names(server_name: str = "cad") -> list[str]:
    """Full MCP tool names with the SDK's ``mcp__<server>__`` prefix."""
    return [f"mcp__{server_name}__{n}" for n in TOOL_NAMES]
