# SPDX-License-Identifier: LGPL-2.1-or-later
"""Read-only geometry introspection and Part primitive / boolean tools."""

from __future__ import annotations

import traceback

import FreeCAD as App

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


@tool(
    "list_objects",
    "List all objects in a document (active if doc is omitted).",
    {"doc": str},
    annotations=_READ_ONLY,
)
async def list_objects(args):
    def work():
        doc = resolve_doc(args.get("doc"))
        return {
            "doc": doc.Name,
            "objects": [summarise_object(o) for o in doc.Objects],
        }
    try:
        return ok(on_gui(work))
    except Exception as exc:
        return err(str(exc))


@tool(
    "get_object",
    "Return properties and bounding-box summary for a named object.",
    {"name": str, "doc": str},
    annotations=_READ_ONLY,
)
async def get_object(args):
    def work():
        doc = resolve_doc(args.get("doc"))
        obj = doc.getObject(args["name"])
        if obj is None:
            raise ValueError(f"No object named {args['name']!r} in {doc.Name}.")
        info = summarise_object(obj)
        info["properties"] = {}
        for prop in obj.PropertiesList:
            try:
                val = getattr(obj, prop)
                info["properties"][prop] = repr(val)
            except Exception:
                info["properties"][prop] = "<unreadable>"
        return info
    try:
        return ok(on_gui(work))
    except Exception as exc:
        return err(str(exc))


@tool(
    "make_box",
    "Create a parametric Part::Box primitive with given length/width/height (mm).",
    {"length": float, "width": float, "height": float, "name": str, "doc": str},
)
async def make_box(args):
    try:
        doc = resolve_doc(args.get("doc"))
        name = args.get("name") or "Box"

        def _do():
            obj = doc.addObject("Part::Box", name)
            obj.Length = float(args["length"])
            obj.Width = float(args["width"])
            obj.Height = float(args["height"])
            doc.recompute()
            return obj

        obj = with_transaction(doc, f"make_box {name}", _do)
        return ok(summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "make_cylinder",
    "Create a parametric Part::Cylinder with given radius and height (mm).",
    {"radius": float, "height": float, "name": str, "doc": str},
)
async def make_cylinder(args):
    try:
        doc = resolve_doc(args.get("doc"))
        name = args.get("name") or "Cylinder"

        def _do():
            obj = doc.addObject("Part::Cylinder", name)
            obj.Radius = float(args["radius"])
            obj.Height = float(args["height"])
            doc.recompute()
            return obj

        obj = with_transaction(doc, f"make_cylinder {name}", _do)
        return ok(summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "make_sphere",
    "Create a parametric Part::Sphere with given radius (mm).",
    {"radius": float, "name": str, "doc": str},
)
async def make_sphere(args):
    try:
        doc = resolve_doc(args.get("doc"))
        name = args.get("name") or "Sphere"

        def _do():
            obj = doc.addObject("Part::Sphere", name)
            obj.Radius = float(args["radius"])
            doc.recompute()
            return obj

        obj = with_transaction(doc, f"make_sphere {name}", _do)
        return ok(summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "make_cone",
    "Create a parametric Part::Cone with radius1/radius2/height (mm).",
    {"radius1": float, "radius2": float, "height": float, "name": str, "doc": str},
)
async def make_cone(args):
    try:
        doc = resolve_doc(args.get("doc"))
        name = args.get("name") or "Cone"

        def _do():
            obj = doc.addObject("Part::Cone", name)
            obj.Radius1 = float(args["radius1"])
            obj.Radius2 = float(args["radius2"])
            obj.Height = float(args["height"])
            doc.recompute()
            return obj

        obj = with_transaction(doc, f"make_cone {name}", _do)
        return ok(summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


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
        doc = resolve_doc(args.get("doc"))
        op = args["op"].lower()
        type_map = {"fuse": "Part::Fuse", "cut": "Part::Cut", "common": "Part::Common"}
        if op not in type_map:
            return err(f"Unknown op {op!r}. Use fuse, cut or common.")
        base = doc.getObject(args["base"])
        tool_obj = doc.getObject(args["tool_name"])
        if base is None or tool_obj is None:
            return err("base or tool_name not found in the document.")
        name = args.get("name") or op.capitalize()

        def _do():
            obj = doc.addObject(type_map[op], name)
            obj.Base = base
            obj.Tool = tool_obj
            doc.recompute()
            return obj

        obj = with_transaction(doc, f"boolean_{op} {name}", _do)
        return ok(summarise_result(doc, [obj.Name]))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


TOOL_FUNCS = [
    list_objects,
    get_object,
    make_box,
    make_cylinder,
    make_sphere,
    make_cone,
    boolean_op,
]

TOOL_NAMES = [
    "list_objects",
    "get_object",
    "make_box",
    "make_cylinder",
    "make_sphere",
    "make_cone",
    "boolean_op",
]


