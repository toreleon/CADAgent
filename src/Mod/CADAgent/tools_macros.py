# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tier A macros — intent-level CAD operations that compose the primitive
tools into one-shot, atomic, guaranteed-valid transactions.

Each macro:
  * runs inside a single `openTransaction` → `commitTransaction` (so the user
    gets one Ctrl+Z per macro call),
  * builds geometry through `profiles.build` so the sketch emerges with DOF=0,
  * binds named parameters + a Parameters spreadsheet when `parametric=True`,
  * auto-appends a decision row to the project-memory sidecar,
  * returns a closed-loop payload with bbox, volume, is_valid_solid, the
    created objects, any warnings, and the parameters that were written.

The macros are the agent's preferred path for common CAD intents like
"create a box" or "create a 50×30×10 plate" — one call produces a correct
feature tree without the agent orchestrating seven fragile sub-calls.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

import FreeCAD as App

try:
    import FreeCADGui as Gui  # noqa: F401
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from claude_agent_sdk import tool

import errors
import profiles
import project_memory
from gui_thread import run_sync
from tools_partdesign import (
    _resolve_doc,
    _resolve_body,
    _resolve_support,
    _sketch_health,
    _summarise_created,
    _sync_parameter_to_sheet,
)


def _ok(payload: dict) -> dict:
    out = {"ok": True}
    out.update(payload)
    return {"content": [{"type": "text", "text": json.dumps(out, default=str)}]}


def _fail(kind: str, **details) -> dict:
    return errors.fail(kind, **details)


def _ensure_body(doc, label: str):
    """Return an existing body or create a new one inside the caller's
    transaction. Caller is responsible for the transaction."""
    body = doc.addObject("PartDesign::Body", label)
    return body


def _new_sketch_on_body(doc, body, plane_spec: str, name: str):
    sk = body.newObject("Sketcher::SketchObject", name)
    support = _resolve_support(doc, body, plane_spec)
    if "AttachmentSupport" in sk.PropertiesList:
        sk.AttachmentSupport = support
    else:
        sk.Support = support
    sk.MapMode = "FlatFace"
    return sk


def _new_pad(body, sketch, length: float, name: str):
    pad = body.newObject("PartDesign::Pad", name)
    pad.Profile = sketch
    pad.Length = float(length)
    pad.Type = "Length"
    if "SideType" in pad.PropertiesList:
        pad.SideType = "One side"
    return pad


def _set_parametric(doc, sketch, pad, named_constraints: dict[str, int],
                    param_bindings: dict[str, str], pad_binding: tuple[str, str] | None) -> list[str]:
    """Write parameters to sidecar + spreadsheet, then bind sketch constraints
    and the pad's Length to Parameters.<alias>.

    `param_bindings` maps constraint label → parameter name (e.g. 'Width' → 'Length').
    `pad_binding` is an optional (pad_prop, param_name) pair for the pad.
    Returns a list of warnings (non-fatal binding failures).
    """
    warnings: list[str] = []
    for label, param in param_bindings.items():
        cid = named_constraints.get(label)
        if cid is None:
            warnings.append(f"no named constraint '{label}' to bind")
            continue
        try:
            sketch.setExpression(f"Constraints.{label}", f"Parameters.{param}")
        except Exception as exc:
            warnings.append(f"bind {label}→Parameters.{param} failed: {exc}")
    if pad_binding is not None:
        prop, param = pad_binding
        try:
            pad.setExpression(prop, f"Parameters.{param}")
        except Exception as exc:
            warnings.append(f"bind Pad.{prop}→Parameters.{param} failed: {exc}")
    doc.recompute()
    return warnings


def _write_parameter(doc, name: str, value: float, unit: str = "mm") -> None:
    project_memory.set_parameter(doc, name, value, unit, "")
    try:
        _sync_parameter_to_sheet(doc, name, value, unit)
    except Exception as exc:
        App.Console.PrintWarning(
            f"CADAgent: could not sync parameter {name} to spreadsheet: {exc}\n"
        )


# --- macros ------------------------------------------------------------


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
                    _write_parameter(doc, "Length", length, "mm")
                    _write_parameter(doc, "Width", width, "mm")
                    _write_parameter(doc, "Height", height, "mm")

                body = _ensure_body(doc, label)
                doc.recompute()  # wire the GuiDocument for the new body
                sk = _new_sketch_on_body(doc, body, "XY", f"{label}_Sketch")
                info = profiles.build(
                    sk,
                    {"kind": "rectangle", "width": length, "height": width, "anchor": "origin"},
                )
                doc.recompute()
                pad = _new_pad(body, sk, height, f"{label}_Pad")

                warnings: list[str] = []
                if parametric:
                    warnings += _set_parametric(
                        doc, sk, pad,
                        info.get("named_constraints", {}),
                        {"Width": "Length", "Height": "Width"},
                        ("Length", "Height"),
                    )
                doc.recompute()

                summary = _summarise_created(doc, [body.Name, sk.Name, pad.Name], warnings)
                summary["body"] = body.Name
                summary["sketch"] = sk.Name
                summary["pad"] = pad.Name
                summary["parameters"] = (
                    {"Length": length, "Width": width, "Height": height} if parametric else {}
                )
                if not summary.get("is_valid_solid"):
                    doc.abortTransaction()
                    return {"__error__": _fail(
                        "invalid_solid", feature=pad.Name,
                        hint="Pad produced invalid solid. Check profile dimensions.",
                        **summary,
                    )}
                doc.commitTransaction()
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
        return _ok(result)
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
                    _write_parameter(doc, "Radius", radius, "mm")
                    _write_parameter(doc, "Height", height, "mm")

                body = _ensure_body(doc, label)
                doc.recompute()
                sk = _new_sketch_on_body(doc, body, "XY", f"{label}_Sketch")
                info = profiles.build(sk, {"kind": "circle", "radius": radius, "center": [0, 0]})
                doc.recompute()
                pad = _new_pad(body, sk, height, f"{label}_Pad")

                warnings: list[str] = []
                if parametric:
                    warnings += _set_parametric(
                        doc, sk, pad,
                        info.get("named_constraints", {}),
                        {"Radius": "Radius"},
                        ("Length", "Height"),
                    )
                doc.recompute()

                summary = _summarise_created(doc, [body.Name, sk.Name, pad.Name], warnings)
                summary["body"] = body.Name
                summary["sketch"] = sk.Name
                summary["pad"] = pad.Name
                summary["parameters"] = (
                    {"Radius": radius, "Height": height} if parametric else {}
                )
                if not summary.get("is_valid_solid"):
                    doc.abortTransaction()
                    return {"__error__": _fail(
                        "invalid_solid", feature=pad.Name,
                        **summary,
                    )}
                doc.commitTransaction()
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
        return _ok(result)
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
                _write_parameter(doc, "Length", length, "mm")
                _write_parameter(doc, "Width", width, "mm")
                _write_parameter(doc, "Thickness", thickness, "mm")
                if corner_r > 0:
                    _write_parameter(doc, "CornerRadius", corner_r, "mm")

                body = _ensure_body(doc, label)
                doc.recompute()
                sk = _new_sketch_on_body(doc, body, "XY", f"{label}_Sketch")
                info = profiles.build(
                    sk,
                    {"kind": "rectangle", "width": length, "height": width, "anchor": "origin"},
                )
                doc.recompute()
                pad = _new_pad(body, sk, thickness, f"{label}_Pad")
                warnings = _set_parametric(
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

                summary = _summarise_created(doc, created, warnings)
                summary["body"] = body.Name
                summary["sketch"] = sk.Name
                summary["pad"] = pad.Name
                summary["parameters"] = {
                    "Length": length, "Width": width, "Thickness": thickness,
                    **({"CornerRadius": corner_r} if corner_r > 0 else {}),
                }
                if not summary.get("is_valid_solid"):
                    doc.abortTransaction()
                    return {"__error__": _fail(
                        "invalid_solid", feature=pad.Name, **summary,
                    )}
                doc.commitTransaction()
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
        return _ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


@tool(
    "add_corner_holes",
    (
        "Add clearance holes at the corners of a feature's top face. "
        "`feature` is the name of an existing Pad/Plate. `diameter` and "
        "`inset` in mm. `depth` defaults to through-all; otherwise extrude "
        "the hole sketch by that length. `pattern` is 4 (four corners)."
    ),
    {
        "type": "object",
        "properties": {
            "feature": {"type": "string"},
            "diameter": {"type": "number"},
            "inset": {"type": "number"},
            "depth": {"type": "number"},
            "pattern": {"type": "integer", "default": 4},
            "doc": {"type": "string"},
        },
        "required": ["feature", "diameter", "inset"],
    },
)
async def add_corner_holes(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        feat = doc.getObject(args["feature"])
        if feat is None:
            raise ValueError(f"No feature named {args['feature']!r}.")
        diameter = float(args["diameter"])
        inset = float(args["inset"])
        depth = args.get("depth")
        body = None
        for parent in feat.InList:
            if parent.TypeId == "PartDesign::Body":
                body = parent
                break
        if body is None:
            raise ValueError(f"{feat.Name} is not inside a PartDesign::Body.")

        def work():
            doc.openTransaction(f"CADAgent: add_corner_holes {feat.Name}")
            try:
                shape = feat.Shape
                bb = shape.BoundBox
                # Identify the top face (max Z planar face).
                top_face_idx = None
                for idx, face in enumerate(shape.Faces, start=1):
                    if face.Surface.__class__.__name__ != "Plane":
                        continue
                    if abs(face.CenterOfMass.z - bb.ZMax) < 1e-6:
                        top_face_idx = idx
                        break
                if top_face_idx is None:
                    raise ValueError("Could not find a planar top face on the feature.")

                sk = body.newObject("Sketcher::SketchObject", f"{feat.Name}_HoleSketch")
                if "AttachmentSupport" in sk.PropertiesList:
                    sk.AttachmentSupport = (feat, [f"Face{top_face_idx}"])
                else:
                    sk.Support = (feat, [f"Face{top_face_idx}"])
                sk.MapMode = "FlatFace"

                import Part
                r = diameter / 2
                # Hole centres offset by `inset` from each corner of the face's bbox.
                face = shape.Faces[top_face_idx - 1]
                fbb = face.BoundBox
                centres = [
                    (fbb.XMin + inset, fbb.YMin + inset),
                    (fbb.XMax - inset, fbb.YMin + inset),
                    (fbb.XMax - inset, fbb.YMax - inset),
                    (fbb.XMin + inset, fbb.YMax - inset),
                ][: int(args.get("pattern") or 4)]
                for cx, cy in centres:
                    sk.addGeometry(
                        Part.Circle(App.Vector(cx, cy, 0), App.Vector(0, 0, 1), r),
                        False,
                    )
                doc.recompute()

                pocket = body.newObject("PartDesign::Pocket", f"{feat.Name}_Holes")
                pocket.Profile = sk
                if depth is None:
                    pocket.Type = "ThroughAll"
                else:
                    pocket.Type = "Length"
                    pocket.Length = float(depth)
                doc.recompute()

                summary = _summarise_created(doc, [sk.Name, pocket.Name])
                summary["body"] = body.Name
                summary["feature"] = feat.Name
                summary["holes"] = len(centres)
                if not summary.get("is_valid_solid"):
                    doc.abortTransaction()
                    return {"__error__": _fail("invalid_solid", feature=pocket.Name, **summary)}
                doc.commitTransaction()
                project_memory.append_decision(
                    doc,
                    f"add_corner_holes on {feat.Name}: ⌀{diameter} × {len(centres)} @ inset {inset}"
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
        return _ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


# --- exports -----------------------------------------------------------

TOOL_FUNCS = [
    make_parametric_box,
    make_parametric_cylinder,
    make_parametric_plate,
    add_corner_holes,
]

TOOL_NAMES = [
    "make_parametric_box",
    "make_parametric_cylinder",
    "make_parametric_plate",
    "add_corner_holes",
]


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in TOOL_NAMES]
