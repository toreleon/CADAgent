# SPDX-License-Identifier: LGPL-2.1-or-later
"""Project-memory and named-parameter custom tools.

Exposes the JSON sidecar via read/write tools, plus `set_parameter` which
mirrors the value into a FreeCAD Parameters spreadsheet so feature properties
can bind to `Parameters.<name>` expressions.
"""

from __future__ import annotations

import traceback

import FreeCAD as App

from claude_agent_sdk import tool
from mcp.types import ToolAnnotations

_READ_ONLY = ToolAnnotations(readOnlyHint=True)

from .. import memory as project_memory
from ..gui_thread import run_sync
from ._shared import ok, err, resolve_doc, with_transaction


def ensure_parameters_spreadsheet(doc):
    """Return the Parameters spreadsheet, creating it on first use."""
    sheet = doc.getObject("Parameters")
    if sheet is None:
        import Spreadsheet  # noqa: F401 — ensures the type is registered
        sheet = doc.addObject("Spreadsheet::Sheet", "Parameters")
        sheet.Label = "Parameters"
    return sheet


def sync_parameter_to_sheet(doc, name: str, value: float, unit: str) -> None:
    """Write name=value (with alias) into the Parameters sheet.

    Allocates a new row at the bottom if this parameter doesn't already have
    an alias; reuses the existing row otherwise. Column A is the name, column
    B holds the value and is aliased to `<name>`.
    """
    sheet = ensure_parameters_spreadsheet(doc)
    target_row = None
    for row in range(1, 200):
        try:
            if sheet.getAlias(f"B{row}") == name:
                target_row = row
                break
        except Exception:
            pass
        try:
            if not sheet.getContents(f"A{row}"):
                target_row = row
                break
        except Exception:
            target_row = row
            break
    if target_row is None:
        target_row = 1
    sheet.set(f"A{target_row}", name)
    sheet.set(f"B{target_row}", f"{value} {unit}".strip())
    try:
        sheet.setAlias(f"B{target_row}", name)
    except Exception:
        pass


@tool(
    "read_project_memory",
    "Return the project memory sidecar (design intent, parameters, decisions).",
    {"doc": str},
    annotations=_READ_ONLY,
)
async def read_project_memory(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        return project_memory.load(doc)

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(str(exc))


@tool(
    "get_parameters",
    "Return the named parameters stored in project memory.",
    {"doc": str},
    annotations=_READ_ONLY,
)
async def get_parameters(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        return {"parameters": project_memory.get_parameters(doc)}

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(str(exc))


@tool(
    "set_parameter",
    (
        "Set a named parameter in project memory AND in the Parameters "
        "spreadsheet (auto-created on first use). Bind a feature to it via "
        "set_datum(value_or_expr='Parameters.<name>')."
    ),
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "value": {"type": "number"},
            "unit": {"type": "string"},
            "note": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["name", "value"],
    },
)
async def set_parameter(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        name = args["name"]
        value = float(args["value"])
        unit = args.get("unit") or "mm"
        note = args.get("note") or ""

        def work():
            spec = project_memory.set_parameter(doc, name, value, unit, note)
            try:
                sync_parameter_to_sheet(doc, name, value, unit)
            except Exception as exc:
                App.Console.PrintWarning(
                    f"CADAgent: could not sync parameter {name} to spreadsheet: {exc}\n"
                )
            doc.recompute()
            return {"name": name, **spec}

        return with_transaction(doc, f"set_parameter {name}", work)

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "write_project_memory_note",
    "Write a key=value into a top-level section of the project memory sidecar.",
    {
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "key": {"type": "string"},
            "value": {},
            "doc": {"type": "string"},
        },
        "required": ["section", "key", "value"],
    },
)
async def write_project_memory_note(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        return project_memory.write_note(doc, args["section"], args["key"], args["value"])

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(str(exc))


TOOL_FUNCS = [
    read_project_memory,
    get_parameters,
    set_parameter,
    write_project_memory_note,
]

TOOL_NAMES = [
    "read_project_memory",
    "get_parameters",
    "set_parameter",
    "write_project_memory_note",
]


