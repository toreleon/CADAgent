# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2026 FreeCAD Project Association <www.freecad.org>      *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful,            *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with FreeCAD; if not, write to the Free Software        *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************
"""In-process MCP tools exposing FreeCAD's Python API to the CAD Agent.

Each mutating tool wraps its work in `doc.openTransaction / commitTransaction`
so a single agent action becomes one Ctrl+Z step. Read-only tools return
JSON-encoded summaries of the requested state.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from claude_agent_sdk import create_sdk_mcp_server, tool

import tools_partdesign
import tools_macros
import tools_diagnostics
import errors
from gui_thread import run_sync


_LAST_RESULT: dict[str, Any] = {"tool": None, "summary": None}


def _ok(payload: dict) -> dict:
    out = {"ok": True}
    out.update(payload)
    text = json.dumps(out, default=str)
    _LAST_RESULT["summary"] = {
        "tool": _LAST_RESULT.get("tool"),
        "ok": True,
        "created": out.get("created"),
        "warnings": out.get("warnings"),
    }
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str, **extras) -> dict:
    """Legacy error path: prefer errors.fail(kind, ...) for new callers."""
    payload = errors.fail("internal_error", message=message, **extras)
    try:
        body = json.loads(payload["content"][0]["text"])
        _LAST_RESULT["summary"] = {
            "tool": _LAST_RESULT.get("tool"),
            "ok": False,
            "error": body.get("error"),
        }
    except Exception:
        pass
    return payload


def _summarise_result(doc, created: list[str], warnings: list[str] | None = None) -> dict:
    """Build the closed-loop payload every mutating tool returns.

    `created` is a list of object names produced by the operation. The helper
    computes bbox / volume / solid validity for the last-created shape-bearing
    object so the agent can immediately tell whether the operation succeeded.
    """
    bbox = None
    volume = None
    is_valid = None
    primary = None
    if doc is not None:
        for name in reversed(created or []):
            obj = doc.getObject(name)
            if obj is None:
                continue
            shape = getattr(obj, "Shape", None)
            if shape is None:
                continue
            primary = obj.Name
            try:
                bb = shape.BoundBox
                bbox = {
                    "xmin": bb.XMin, "ymin": bb.YMin, "zmin": bb.ZMin,
                    "xmax": bb.XMax, "ymax": bb.YMax, "zmax": bb.ZMax,
                    "length": bb.XLength, "width": bb.YLength, "height": bb.ZLength,
                }
                volume = float(shape.Volume)
            except Exception:
                pass
            try:
                is_valid = bool(shape.isValid())
            except Exception:
                is_valid = None
            break
    return {
        "created": list(created or []),
        "primary": primary,
        "bbox": bbox,
        "volume": volume,
        "is_valid_solid": is_valid,
        "warnings": list(warnings or []),
    }


def mark_tool(name: str) -> None:
    """Record the last tool the agent invoked (for the context snapshot)."""
    _LAST_RESULT["tool"] = name


def get_last_result_summary() -> dict | None:
    return _LAST_RESULT.get("summary")


def _resolve_doc(doc_name: str | None):
    if doc_name:
        doc = App.getDocument(doc_name) if doc_name in App.listDocuments() else None
        if doc is None:
            raise ValueError(f"No document named {doc_name!r}. Use list_documents.")
        return doc
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError(
            "No active FreeCAD document. Call create_document first or open one."
        )
    return doc


def _with_transaction(doc, label: str, fn):
    """Marshal `fn` onto the Qt GUI thread, wrapped in a single undo transaction.

    FreeCAD's document API is not thread-safe — mutating calls from the
    asyncio worker thread trigger Qt QObject thread-affinity aborts. `run_sync`
    dispatches the work to the main thread and blocks for the result.
    """
    def work():
        doc.openTransaction(f"CADAgent: {label}")
        try:
            result = fn()
            doc.commitTransaction()
            return result
        except Exception:
            doc.abortTransaction()
            raise

    return run_sync(work)


def _on_gui(fn):
    """Execute `fn` on the Qt GUI thread; re-raise exceptions on the caller."""
    return run_sync(fn)


def _summarise_object(obj) -> dict:
    info: dict[str, Any] = {
        "name": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
    }
    try:
        if hasattr(obj, "Shape") and obj.Shape is not None:
            bb = obj.Shape.BoundBox
            info["bbox"] = {
                "xmin": bb.XMin, "ymin": bb.YMin, "zmin": bb.ZMin,
                "xmax": bb.XMax, "ymax": bb.YMax, "zmax": bb.ZMax,
            }
            info["volume"] = obj.Shape.Volume
    except Exception:
        pass
    try:
        if _HAS_GUI and obj.ViewObject is not None:
            info["visible"] = bool(obj.ViewObject.Visibility)
    except Exception:
        pass
    return info


# --- Tools --------------------------------------------------------------


@tool("list_documents", "List the names of all open FreeCAD documents.", {})
async def list_documents(args):
    def work():
        names = list(App.listDocuments().keys())
        active = App.ActiveDocument.Name if App.ActiveDocument else None
        return {"documents": names, "active": active}
    try:
        return _ok(_on_gui(work))
    except Exception as exc:
        return _err(str(exc))


@tool(
    "get_active_document",
    "Return the active document name and a short summary of its objects.",
    {},
)
async def get_active_document(args):
    def work():
        doc = App.ActiveDocument
        if doc is None:
            return {"active": None, "objects": []}
        return {
            "active": doc.Name,
            "label": doc.Label,
            "objects": [_summarise_object(o) for o in doc.Objects],
        }
    try:
        return _ok(_on_gui(work))
    except Exception as exc:
        return _err(str(exc))


@tool(
    "create_document",
    "Create a new FreeCAD document and make it active. Returns the document name.",
    {"name": str},
)
async def create_document(args):
    def work():
        doc = App.newDocument(args["name"])
        return {"name": doc.Name, "label": doc.Label}
    try:
        return _ok(_on_gui(work))
    except Exception as exc:
        return _err(str(exc))


@tool(
    "list_objects",
    "List all objects in a document (active if doc is omitted).",
    {"doc": str},
)
async def list_objects(args):
    def work():
        doc = _resolve_doc(args.get("doc"))
        return {
            "doc": doc.Name,
            "objects": [_summarise_object(o) for o in doc.Objects],
        }
    try:
        return _ok(_on_gui(work))
    except Exception as exc:
        return _err(str(exc))


@tool(
    "get_object",
    "Return properties and bounding-box summary for a named object.",
    {"name": str, "doc": str},
)
async def get_object(args):
    def work():
        doc = _resolve_doc(args.get("doc"))
        obj = doc.getObject(args["name"])
        if obj is None:
            raise ValueError(f"No object named {args['name']!r} in {doc.Name}.")
        info = _summarise_object(obj)
        info["properties"] = {}
        for prop in obj.PropertiesList:
            try:
                val = getattr(obj, prop)
                info["properties"][prop] = repr(val)
            except Exception:
                info["properties"][prop] = "<unreadable>"
        return info
    try:
        return _ok(_on_gui(work))
    except Exception as exc:
        return _err(str(exc))


@tool("get_selection", "Return names of objects currently selected in the GUI.", {})
async def get_selection(args):
    def work():
        if not _HAS_GUI:
            return {"selection": []}
        sel = Gui.Selection.getSelection()
        return {"selection": [_summarise_object(o) for o in sel]}
    try:
        return _ok(_on_gui(work))
    except Exception as exc:
        return _err(str(exc))


@tool(
    "make_box",
    "Create a parametric Part::Box primitive with given length/width/height (mm).",
    {"length": float, "width": float, "height": float, "name": str, "doc": str},
)
async def make_box(args):
    try:
        doc = _resolve_doc(args.get("doc"))
        name = args.get("name") or "Box"

        def _do():
            obj = doc.addObject("Part::Box", name)
            obj.Length = float(args["length"])
            obj.Width = float(args["width"])
            obj.Height = float(args["height"])
            doc.recompute()
            return obj

        obj = _with_transaction(doc, f"make_box {name}", _do)
        return _ok(_summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "make_cylinder",
    "Create a parametric Part::Cylinder with given radius and height (mm).",
    {"radius": float, "height": float, "name": str, "doc": str},
)
async def make_cylinder(args):
    try:
        doc = _resolve_doc(args.get("doc"))
        name = args.get("name") or "Cylinder"

        def _do():
            obj = doc.addObject("Part::Cylinder", name)
            obj.Radius = float(args["radius"])
            obj.Height = float(args["height"])
            doc.recompute()
            return obj

        obj = _with_transaction(doc, f"make_cylinder {name}", _do)
        return _ok(_summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "make_sphere",
    "Create a parametric Part::Sphere with given radius (mm).",
    {"radius": float, "name": str, "doc": str},
)
async def make_sphere(args):
    try:
        doc = _resolve_doc(args.get("doc"))
        name = args.get("name") or "Sphere"

        def _do():
            obj = doc.addObject("Part::Sphere", name)
            obj.Radius = float(args["radius"])
            doc.recompute()
            return obj

        obj = _with_transaction(doc, f"make_sphere {name}", _do)
        return _ok(_summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "make_cone",
    "Create a parametric Part::Cone with radius1/radius2/height (mm).",
    {"radius1": float, "radius2": float, "height": float, "name": str, "doc": str},
)
async def make_cone(args):
    try:
        doc = _resolve_doc(args.get("doc"))
        name = args.get("name") or "Cone"

        def _do():
            obj = doc.addObject("Part::Cone", name)
            obj.Radius1 = float(args["radius1"])
            obj.Radius2 = float(args["radius2"])
            obj.Height = float(args["height"])
            doc.recompute()
            return obj

        obj = _with_transaction(doc, f"make_cone {name}", _do)
        return _ok(_summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "boolean_op",
    (
        "Parametric boolean between two existing objects. "
        "op is one of 'fuse', 'cut', 'common'."
    ),
    {"op": str, "base": str, "tool_name": str, "name": str, "doc": str},
)
async def boolean_op(args):
    try:
        doc = _resolve_doc(args.get("doc"))
        op = args["op"].lower()
        type_map = {"fuse": "Part::Fuse", "cut": "Part::Cut", "common": "Part::Common"}
        if op not in type_map:
            return _err(f"Unknown op {op!r}. Use fuse, cut or common.")
        base = doc.getObject(args["base"])
        tool_obj = doc.getObject(args["tool_name"])
        if base is None or tool_obj is None:
            return _err("base or tool_name not found in the document.")
        name = args.get("name") or op.capitalize()

        def _do():
            obj = doc.addObject(type_map[op], name)
            obj.Base = base
            obj.Tool = tool_obj
            doc.recompute()
            return obj

        obj = _with_transaction(doc, f"boolean_{op} {name}", _do)
        return _ok(_summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


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
        doc = _resolve_doc(args.get("doc"))
        obj = doc.getObject(args["name"])
        if obj is None:
            return _err(f"No object named {args['name']!r}.")
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

        obj = _with_transaction(doc, f"set_placement {obj.Name}", _do)
        result = _summarise_result(doc, [obj.Name])
        result["updated"] = obj.Name
        return _ok(result)
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "delete_object",
    "Remove an object from the document by name.",
    {"name": str, "doc": str},
)
async def delete_object(args):
    try:
        doc = _resolve_doc(args.get("doc"))
        obj = doc.getObject(args["name"])
        if obj is None:
            return _err(f"No object named {args['name']!r}.")

        def _do():
            doc.removeObject(args["name"])

        _with_transaction(doc, f"delete_object {args['name']}", _do)
        return _ok({"deleted": args["name"]})
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "recompute_and_fit",
    "Recompute the document and fit the 3D view to all objects.",
    {"doc": str},
)
async def recompute_and_fit(args):
    def work():
        doc = _resolve_doc(args.get("doc"))
        doc.recompute()
        if _HAS_GUI:
            try:
                view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
                if view is not None and hasattr(view, "fitAll"):
                    view.fitAll()
                else:
                    Gui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
        return {"recomputed": doc.Name}
    try:
        return _ok(_on_gui(work))
    except Exception as exc:
        return _err(str(exc))


@tool(
    "export_step",
    "Export named objects to a STEP file at the given path.",
    {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Object names to export.",
            },
            "path": {"type": "string", "description": "Output STEP file path."},
            "doc": {
                "type": "string",
                "description": "Document name (optional; defaults to active).",
            },
        },
        "required": ["names", "path"],
    },
)
async def export_step(args):
    def work():
        doc = _resolve_doc(args.get("doc"))
        objs = []
        for n in args["names"]:
            o = doc.getObject(n)
            if o is None:
                raise ValueError(f"No object named {n!r}.")
            objs.append(o)
        import Import  # FreeCAD's STEP/IGES importer/exporter
        Import.export(objs, args["path"])
        return {"exported": args["path"], "objects": args["names"]}
    try:
        return _ok(_on_gui(work))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "run_python",
    (
        "Execute arbitrary Python in FreeCAD's console (via Gui.doCommand). "
        "Use only when primitive tools can't express the request. "
        "The code runs on the GUI thread inside a transaction; App, "
        "FreeCAD, FreeCADGui and Part are already importable."
    ),
    {"code": str, "label": str},
)
async def run_python(args):
    code = args.get("code") or ""
    label = args.get("label") or "run_python"
    if not code.strip():
        return _err("Empty code.")

    def work():
        doc = App.ActiveDocument
        tx_owner = doc
        if tx_owner is not None:
            tx_owner.openTransaction(f"CADAgent: {label}")
        try:
            if _HAS_GUI:
                for line in code.splitlines():
                    Gui.doCommand(line)
            else:
                exec(code, {"App": App, "FreeCAD": App})
            if tx_owner is not None:
                tx_owner.commitTransaction()
                tx_owner.recompute()
            return {"ran": True, "label": label}
        except Exception:
            if tx_owner is not None:
                tx_owner.abortTransaction()
            raise

    try:
        return _ok(run_sync(work))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


# --- Server builder -----------------------------------------------------

TOOL_FUNCS = [
    list_documents,
    get_active_document,
    create_document,
    list_objects,
    get_object,
    get_selection,
    make_box,
    make_cylinder,
    make_sphere,
    make_cone,
    boolean_op,
    set_placement,
    delete_object,
    recompute_and_fit,
    export_step,
    run_python,
]

TOOL_NAMES = [
    "list_documents",
    "get_active_document",
    "create_document",
    "list_objects",
    "get_object",
    "get_selection",
    "make_box",
    "make_cylinder",
    "make_sphere",
    "make_cone",
    "boolean_op",
    "set_placement",
    "delete_object",
    "recompute_and_fit",
    "export_step",
    "run_python",
]


def build_mcp_server():
    """Create the in-process MCP server exposing CAD tools."""
    all_tools = (
        TOOL_FUNCS
        + tools_partdesign.TOOL_FUNCS
        + tools_macros.TOOL_FUNCS
        + tools_diagnostics.TOOL_FUNCS
    )
    return create_sdk_mcp_server(name="cad", version="0.1.0", tools=all_tools)


def allowed_tool_names() -> list[str]:
    return (
        [f"mcp__cad__{n}" for n in TOOL_NAMES]
        + tools_partdesign.allowed_tool_names()
        + tools_macros.allowed_tool_names()
        + tools_diagnostics.allowed_tool_names()
    )
