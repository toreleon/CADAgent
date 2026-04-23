# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection, placement, and object-lifecycle custom tools."""

from __future__ import annotations

import traceback

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from claude_agent_sdk import tool
from mcp.types import ToolAnnotations

_READ_ONLY = ToolAnnotations(readOnlyHint=True)

from ._shared import (
    ok,
    err,
    on_gui,
    resolve_doc,
    summarise_object,
    summarise_result,
    with_transaction,
)


@tool("get_selection", "Return names of objects currently selected in the GUI.", {}, annotations=_READ_ONLY)
async def get_selection(args):
    def work():
        if not _HAS_GUI:
            return {"selection": []}
        sel = Gui.Selection.getSelection()
        return {"selection": [summarise_object(o) for o in sel]}
    try:
        return ok(on_gui(work))
    except Exception as exc:
        return err(str(exc))


@tool(
    "set_placement",
    (
        "Set an object's placement. Position is [x,y,z] mm. "
        "Rotation axis is [ax,ay,az]; angle is in degrees."
    ),
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Target object name."},
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "[x, y, z] in millimetres.",
            },
            "rotation_axis": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "[ax, ay, az] rotation axis.",
            },
            "rotation_angle": {
                "type": "number",
                "description": "Rotation angle in degrees.",
            },
            "doc": {
                "type": "string",
                "description": "Document name (optional).",
            },
        },
        "required": ["name"],
    },
)
async def set_placement(args):
    try:
        doc = resolve_doc(args.get("doc"))
        obj = doc.getObject(args["name"])
        if obj is None:
            return err(f"No object named {args['name']!r}.")
        pos = args.get("position") or [0.0, 0.0, 0.0]
        axis = args.get("rotation_axis") or [0.0, 0.0, 1.0]
        angle = float(args.get("rotation_angle") or 0.0)

        def _do():
            obj.Placement = App.Placement(
                App.Vector(float(pos[0]), float(pos[1]), float(pos[2])),
                App.Rotation(
                    App.Vector(float(axis[0]), float(axis[1]), float(axis[2])),
                    angle,
                ),
            )
            doc.recompute()
            return obj

        obj = with_transaction(doc, f"set_placement {obj.Name}", _do)
        result = summarise_result(doc, [obj.Name])
        result["updated"] = obj.Name
        return ok(result)
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "delete_object",
    "Remove an object from the document by name.",
    {"name": str, "doc": str},
)
async def delete_object(args):
    try:
        doc = resolve_doc(args.get("doc"))
        obj = doc.getObject(args["name"])
        if obj is None:
            return err(f"No object named {args['name']!r}.")

        def _do():
            doc.removeObject(args["name"])

        with_transaction(doc, f"delete_object {args['name']}", _do)
        return ok({"deleted": args["name"]})
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


TOOL_FUNCS = [get_selection, set_placement, delete_object]
TOOL_NAMES = ["get_selection", "set_placement", "delete_object"]


