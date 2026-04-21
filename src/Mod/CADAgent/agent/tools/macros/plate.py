# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parametric prismatic Tier A macros: box, cylinder, plate.

Each macro builds Body + Sketch + Pad (+ optional fillet for plate) in one
undo step, writes named parameters to the Parameters spreadsheet, and binds
the sketch/pad to those parameters so the user can edit values later.
"""

from __future__ import annotations

import traceback

import FreeCAD as App

from claude_agent_sdk import tool

from ... import errors, memory as project_memory
from ...gui_thread import run_sync
from .. import profiles
from .._shared import ok, summarise_result
from ._macro_shared import (
    ensure_body,
    new_pad,
    new_sketch_on_body,
    present_result,
    set_parametric,
    write_parameter,
)


@tool(
    "make_parametric_box",
    (
        "One-shot parametric box (Body + Sketch + Pad in a single undo step). "
        "length×width×height in mm. When parametric=true (default), writes "
        "Length, Width, Height to the Parameters spreadsheet and binds the "
        "sketch's Width/Height constraints and the Pad's Length to those "
        "parameters so the user can edit values post-hoc."
    ),
    {
        "type": "object",
        "properties": {
            "length": {"type": "number"},
            "width": {"type": "number"},
            "height": {"type": "number"},
            "label": {"type": "string"},
            "parametric": {"type": "boolean", "default": True},
            "doc": {"type": "string"},
        },
        "required": ["length", "width", "height"],
    },
)
async def make_parametric_box(args):
    def _do():
        length = float(args["length"])
        width = float(args["width"])
        height = float(args["height"])
        label = args.get("label") or "Box"
        parametric = bool(args.get("parametric", True))

        # Open a fresh doc if none is active — a zero-friction path for the
        # user's first prompt of the session.
        doc = App.ActiveDocument or App.newDocument("Unnamed")

        def work():
            doc.openTransaction(f"CADAgent: make_parametric_box {label}")
            try:
                if parametric:
                    write_parameter(doc, "Length", length, "mm")
                    write_parameter(doc, "Width", width, "mm")
                    write_parameter(doc, "Height", height, "mm")

                body = ensure_body(doc, label)
                doc.recompute()  # wire the GuiDocument for the new body
                sk = new_sketch_on_body(doc, body, "XY", f"{label}_Sketch")
                info = profiles.build(
                    sk,
                    {"kind": "rectangle", "width": length, "height": width, "anchor": "origin"},
                )
                doc.recompute()
                pad = new_pad(body, sk, height, f"{label}_Pad")

                warnings: list[str] = []
                if parametric:
                    warnings += set_parametric(
                        doc, sk, pad,
                        info.get("named_constraints", {}),
                        {"Width": "Length", "Height": "Width"},
                        ("Length", "Height"),
                    )
                doc.recompute()

                summary = summarise_result(doc, [body.Name, sk.Name, pad.Name], warnings)
                summary["body"] = body.Name
                summary["sketch"] = sk.Name
                summary["pad"] = pad.Name
                summary["parameters"] = (
                    {"Length": length, "Width": width, "Height": height} if parametric else {}
                )
                if not summary.get("is_valid_solid"):
                    doc.abortTransaction()
                    return {"__error__": errors.fail(
                        "invalid_solid", feature=pad.Name,
                        hint="Pad produced invalid solid. Check profile dimensions.",
                        **summary,
                    )}
                doc.commitTransaction()
                present_result(doc, body=body, feature=pad, sketch=sk)
                project_memory.append_decision(
                    doc,
                    f"make_parametric_box L={length} W={width} H={height} "
                    f"→ {body.Name}/{pad.Name} ({summary.get('volume')} mm³)"
                )
                return summary
            except Exception:
                doc.abortTransaction()
                raise

        return work()

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


@tool(
    "make_parametric_cylinder",
    (
        "One-shot parametric cylinder (Body + Sketch(circle) + Pad). "
        "radius and height in mm. When parametric=true, writes Radius and "
        "Height to the Parameters spreadsheet and binds them."
    ),
    {
        "type": "object",
        "properties": {
            "radius": {"type": "number"},
            "height": {"type": "number"},
            "label": {"type": "string"},
            "parametric": {"type": "boolean", "default": True},
            "doc": {"type": "string"},
        },
        "required": ["radius", "height"],
    },
)
async def make_parametric_cylinder(args):
    def _do():
        radius = float(args["radius"])
        height = float(args["height"])
        label = args.get("label") or "Cylinder"
        parametric = bool(args.get("parametric", True))

        doc = App.ActiveDocument or App.newDocument("Unnamed")

        def work():
            doc.openTransaction(f"CADAgent: make_parametric_cylinder {label}")
            try:
                if parametric:
                    write_parameter(doc, "Radius", radius, "mm")
                    write_parameter(doc, "Height", height, "mm")

                body = ensure_body(doc, label)
                doc.recompute()
                sk = new_sketch_on_body(doc, body, "XY", f"{label}_Sketch")
                info = profiles.build(sk, {"kind": "circle", "radius": radius, "center": [0, 0]})
                doc.recompute()
                pad = new_pad(body, sk, height, f"{label}_Pad")

                warnings: list[str] = []
                if parametric:
                    warnings += set_parametric(
                        doc, sk, pad,
                        info.get("named_constraints", {}),
                        {"Radius": "Radius"},
                        ("Length", "Height"),
                    )
                doc.recompute()

                summary = summarise_result(doc, [body.Name, sk.Name, pad.Name], warnings)
                summary["body"] = body.Name
                summary["sketch"] = sk.Name
                summary["pad"] = pad.Name
                summary["parameters"] = (
                    {"Radius": radius, "Height": height} if parametric else {}
                )
                if not summary.get("is_valid_solid"):
                    doc.abortTransaction()
                    return {"__error__": errors.fail(
                        "invalid_solid", feature=pad.Name,
                        **summary,
                    )}
                doc.commitTransaction()
                present_result(doc, body=body, feature=pad, sketch=sk)
                project_memory.append_decision(
                    doc,
                    f"make_parametric_cylinder R={radius} H={height} "
                    f"→ {body.Name}/{pad.Name} ({summary.get('volume')} mm³)"
                )
                return summary
            except Exception:
                doc.abortTransaction()
                raise

        return work()

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


@tool(
    "make_parametric_plate",
    (
        "One-shot parametric plate (Body + rectangle Sketch + Pad, optional "
        "fillet on top edges). length×width×thickness in mm. corner_radius>0 "
        "adds a fillet on the top-face edges."
    ),
    {
        "type": "object",
        "properties": {
            "length": {"type": "number"},
            "width": {"type": "number"},
            "thickness": {"type": "number"},
            "corner_radius": {"type": "number", "default": 0},
            "label": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["length", "width", "thickness"],
    },
)
async def make_parametric_plate(args):
    def _do():
        length = float(args["length"])
        width = float(args["width"])
        thickness = float(args["thickness"])
        corner_r = float(args.get("corner_radius") or 0)
        label = args.get("label") or "Plate"
        doc = App.ActiveDocument or App.newDocument("Unnamed")

        def work():
            doc.openTransaction(f"CADAgent: make_parametric_plate {label}")
            try:
                write_parameter(doc, "Length", length, "mm")
                write_parameter(doc, "Width", width, "mm")
                write_parameter(doc, "Thickness", thickness, "mm")
                if corner_r > 0:
                    write_parameter(doc, "CornerRadius", corner_r, "mm")

                body = ensure_body(doc, label)
                doc.recompute()
                sk = new_sketch_on_body(doc, body, "XY", f"{label}_Sketch")
                info = profiles.build(
                    sk,
                    {"kind": "rectangle", "width": length, "height": width, "anchor": "origin"},
                )
                doc.recompute()
                pad = new_pad(body, sk, thickness, f"{label}_Pad")
                warnings = set_parametric(
                    doc, sk, pad,
                    info.get("named_constraints", {}),
                    {"Width": "Length", "Height": "Width"},
                    ("Length", "Thickness"),
                )
                doc.recompute()

                created = [body.Name, sk.Name, pad.Name]

                if corner_r > 0:
                    # Fillet only the top-face edges, identified by their Z.
                    shape = pad.Shape
                    top_edges: list[str] = []
                    if shape is not None:
                        z_top = shape.BoundBox.ZMax
                        for idx, edge in enumerate(shape.Edges, start=1):
                            if (abs(edge.Vertexes[0].Z - z_top) < 1e-6 and
                                    abs(edge.Vertexes[-1].Z - z_top) < 1e-6):
                                top_edges.append(f"Edge{idx}")
                    if top_edges:
                        fillet = body.newObject("PartDesign::Fillet", f"{label}_Fillet")
                        fillet.Base = (pad, top_edges)
                        fillet.Radius = corner_r
                        try:
                            fillet.setExpression("Radius", "Parameters.CornerRadius")
                        except Exception as exc:
                            warnings.append(f"bind Fillet.Radius failed: {exc}")
                        doc.recompute()
                        created.append(fillet.Name)

                summary = summarise_result(doc, created, warnings)
                summary["body"] = body.Name
                summary["sketch"] = sk.Name
                summary["pad"] = pad.Name
                summary["parameters"] = {
                    "Length": length, "Width": width, "Thickness": thickness,
                    **({"CornerRadius": corner_r} if corner_r > 0 else {}),
                }
                if not summary.get("is_valid_solid"):
                    doc.abortTransaction()
                    return {"__error__": errors.fail(
                        "invalid_solid", feature=pad.Name, **summary,
                    )}
                doc.commitTransaction()
                final_feature = doc.getObject(created[-1]) if created else pad
                present_result(doc, body=body, feature=final_feature, sketch=sk)
                project_memory.append_decision(
                    doc,
                    f"make_parametric_plate L={length} W={width} T={thickness}"
                    + (f" r={corner_r}" if corner_r > 0 else "")
                    + f" → {body.Name} ({summary.get('volume')} mm³)"
                )
                return summary
            except Exception:
                doc.abortTransaction()
                raise

        return work()

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


TOOL_FUNCS = [make_parametric_box, make_parametric_cylinder, make_parametric_plate]
TOOL_NAMES = ["make_parametric_box", "make_parametric_cylinder", "make_parametric_plate"]


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in TOOL_NAMES]
