# SPDX-License-Identifier: LGPL-2.1-or-later
"""Project-memory tools.

Sidecar reads/writes keyed by .FCStd path: design intent, parameters,
decisions, naming. The sidecar lives next to the .FCStd file.
"""

from __future__ import annotations

import traceback

from claude_agent_sdk import tool

from .. import memory as project_memory
from ._common import READ_ONLY, err, handle, ok, schema


@tool(
    "memory_read",
    "Return the full project-memory sidecar (design_intent, parameters, decisions, plan, naming) for the given .FCStd.",
    schema(),
    annotations=READ_ONLY,
)
async def memory_read(args):
    try:
        return ok(project_memory.load(handle(args)))
    except Exception as exc:
        return err(str(exc), traceback=traceback.format_exc(limit=4))


@tool(
    "memory_note_write",
    "Write a key/value into a top-level section of the sidecar (e.g. section='design_intent' or 'naming').",
    schema(
        section={"type": "string", "required": True},
        key={"type": "string", "required": True},
        value={},  # any JSON value
    ),
)
async def memory_note_write(args):
    try:
        doc = handle(args)
        section = args.get("section")
        key = args.get("key")
        if not section or not key:
            raise ValueError("section and key are required")
        if "value" not in args:
            raise ValueError("value is required")
        return ok({"written": project_memory.write_note(doc, section, key, args["value"])})
    except Exception as exc:
        return err(str(exc))


@tool(
    "memory_parameter_set",
    "Set a named design parameter (value + unit + optional note + optional verify query) in the sidecar. "
    "If verify is provided (an inspect-DSL query string like 'slots width=8 length=15' or 'spheres radius=250'), "
    "the auto-probe runs it after every Bash mutation and surfaces any deviation. Use verify on count/dimension "
    "parameters that define done-ness.",
    schema(
        name={"type": "string", "required": True},
        value={"type": "number", "required": True},
        unit={"type": "string"},
        note={"type": "string"},
        verify={"type": "string"},
    ),
)
async def memory_parameter_set(args):
    try:
        doc = handle(args)
        spec = project_memory.set_parameter(
            doc,
            args["name"],
            float(args["value"]),
            args.get("unit") or "mm",
            args.get("note") or "",
            verify=args.get("verify"),
        )
        return ok({"name": args["name"], **spec})
    except Exception as exc:
        return err(str(exc))


@tool(
    "memory_parameters_get",
    "Return all named parameters recorded for this doc.",
    schema(),
    annotations=READ_ONLY,
)
async def memory_parameters_get(args):
    try:
        return ok({"parameters": project_memory.get_parameters(handle(args))})
    except Exception as exc:
        return err(str(exc))


@tool(
    "memory_decision_record",
    "Record a typed design decision (goal/constraints/alternatives/choice/rationale/depends_on). Depends_on ids link to earlier decisions (d-NNN).",
    schema(
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
        doc = handle(args)
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
        return ok({"decision": entry})
    except Exception as exc:
        return err(str(exc))


@tool(
    "memory_decisions_list",
    "Dump every decision record for this doc (for re-grounding in later turns).",
    schema(),
    annotations=READ_ONLY,
)
async def memory_decisions_list(args):
    try:
        return ok({"decisions": project_memory.list_decisions(handle(args))})
    except Exception as exc:
        return err(str(exc))


__all__ = [
    "memory_decision_record",
    "memory_decisions_list",
    "memory_note_write",
    "memory_parameter_set",
    "memory_parameters_get",
    "memory_read",
]
