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

"""Part Design and Sketcher MCP tools for the CAD Agent.

Adds parametric Body / Sketch / Pad / Pocket / Fillet / Chamfer / Hole tools
plus project-memory helpers. Every mutating call hops onto the Qt GUI thread
via ``gui_thread.run_sync`` and wraps work in one undo transaction.

Sketch constraint ``refs`` conventions
--------------------------------------
Constraints take a flat list of ints matching the ``Sketcher.Constraint``
positional arguments. Point positions: 0=edge, 1=start, 2=end, 3=center.

Examples::

    Horizontal(Geo=2)                     refs=[2]
    Vertical(Geo=3)                       refs=[3]
    Coincident(g1=0,p1=2,g2=1,p2=1)       refs=[0,2,1,1]
    Distance(Geo=2, L=50)                 refs=[2], value=50
    DistanceX(g1=0,p1=1,g2=0,p2=2, L=50)  refs=[0,1,0,2], value=50
    Radius(Geo=0, R=5)                    refs=[0], value=5
    Equal(g1, g2)                         refs=[g1,g2]
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

from claude_agent_sdk import tool

import errors
import profiles
import project_memory
from gui_thread import run_sync


# --- helpers ------------------------------------------------------------


def _ok(payload: dict) -> dict:
    out = {"ok": True}
    out.update(payload)
    return {"content": [{"type": "text", "text": json.dumps(out, default=str)}]}


def _err(message: str) -> dict:
    return errors.fail("internal_error", message=message)


def _summarise_created(doc, created: list[str], warnings: list[str] | None = None) -> dict:
    """Compute bbox / volume / validity for the primary created object."""
    bbox = None
    volume = None
    is_valid = None
    primary = None
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


def _sketch_health(sk) -> dict:
    return {
        "dof": int(getattr(sk, "DoF", -1)),
        "malformed": list(getattr(sk, "MalformedConstraints", []) or []),
        "conflicting": list(getattr(sk, "ConflictingConstraints", []) or []),
        "redundant": list(getattr(sk, "RedundantConstraints", []) or []),
    }


def _resolve_doc(doc_name):
    if doc_name:
        if doc_name not in App.listDocuments():
            raise ValueError(f"No document named {doc_name!r}.")
        return App.getDocument(doc_name)
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError("No active FreeCAD document. Open or create one first.")
    return doc


def _with_transaction(doc, label: str, fn):
    doc.openTransaction(f"CADAgent: {label}")
    try:
        result = fn()
        doc.commitTransaction()
        return result
    except Exception:
        doc.abortTransaction()
        raise


def _resolve_body(doc, name):
    if name:
        obj = doc.getObject(name)
        if obj is None or obj.TypeId != "PartDesign::Body":
            raise ValueError(f"{name!r} is not a PartDesign::Body in {doc.Name}.")
        return obj
    # Fallback: active body, else first body.
    if _HAS_GUI:
        try:
            import PartDesignGui  # type: ignore
            body = PartDesignGui.getActiveBody(False)
            if body is not None and body.Document is doc:
                return body
        except Exception:
            pass
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Body":
            return obj
    raise ValueError("No PartDesign::Body in the document; call create_body first.")


def _resolve_sketch(doc, name):
    obj = doc.getObject(name)
    if obj is None or "Sketcher::SketchObject" not in obj.TypeId:
        raise ValueError(f"{name!r} is not a Sketch.")
    return obj


_PLANE_MAP = {
    "XY": "XY_Plane",
    "XZ": "XZ_Plane",
    "YZ": "YZ_Plane",
}


def _resolve_support(doc, body, plane_spec: str):
    """Return the (feature, subnames) tuple to use as AttachmentSupport."""
    if plane_spec in _PLANE_MAP:
        origin = body.Origin
        plane = origin.getObject(_PLANE_MAP[plane_spec])
        if plane is None:
            for p in origin.OriginFeatures:
                if p.Name.endswith(_PLANE_MAP[plane_spec]):
                    plane = p
                    break
        if plane is None:
            raise ValueError(f"Body {body.Name} has no {plane_spec} origin plane.")
        return (plane, [""])
    if "." in plane_spec:
        feat_name, sub = plane_spec.split(".", 1)
        feat = doc.getObject(feat_name)
        if feat is None:
            raise ValueError(f"Feature {feat_name!r} not found for sketch support.")
        return (feat, [sub])
    raise ValueError(
        f"Unknown plane spec {plane_spec!r}. Use 'XY'|'XZ'|'YZ' or 'Feature.FaceN'."
    )


# --- tools: body / sketch ----------------------------------------------


@tool(
    "create_body",
    "Create a new PartDesign::Body and make it active. Returns the body name.",
    {"label": str, "doc": str},
)
async def create_body(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        label = args.get("label") or "Body"

        def work():
            body = doc.addObject("PartDesign::Body", label)
            doc.recompute()
            # Setting the active body touches GuiDocument internals that crash
            # when the Gui document isn't fully wired (e.g. brand-new doc).
            # Guard defensively; the body is still usable without being active.
            if _HAS_GUI:
                try:
                    gui_doc = Gui.getDocument(doc.Name) if hasattr(Gui, "getDocument") else None
                    active_view = gui_doc.ActiveView if gui_doc is not None else None
                    if active_view is not None and hasattr(active_view, "setActiveObject"):
                        active_view.setActiveObject("pdbody", body)
                except Exception:
                    pass
            return body

        body = _with_transaction(doc, f"create_body {label}", work)
        summary = _summarise_created(doc, [body.Name])
        summary["label"] = body.Label
        summary["active_body"] = body.Name
        return summary

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "create_sketch",
    (
        "Create a PartDesign sketch on a plane or face. "
        "plane is 'XY'|'XZ'|'YZ' for the body origin, or 'Feature.FaceN' "
        "for a face on an existing feature. body defaults to the active body."
    ),
    {"plane": str, "body": str, "name": str, "doc": str},
)
async def create_sketch(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        body = _resolve_body(doc, args.get("body"))
        plane = args.get("plane") or "XY"
        sketch_name = args.get("name") or "Sketch"

        def work():
            sketch = body.newObject("Sketcher::SketchObject", sketch_name)
            support = _resolve_support(doc, body, plane)
            # FreeCAD 1.x uses AttachmentSupport; fall back to Support if needed.
            if "AttachmentSupport" in sketch.PropertiesList:
                sketch.AttachmentSupport = support
            else:
                sketch.Support = support
            sketch.MapMode = "FlatFace"
            doc.recompute()
            return sketch

        sk = _with_transaction(doc, f"create_sketch {sketch_name}", work)
        summary = _summarise_created(doc, [sk.Name])
        summary["body"] = body.Name
        summary["plane"] = plane
        summary.update(_sketch_health(sk))
        return summary

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


def _make_geometry(kind: str, params: dict):
    """Return (Part geometry, extra_info) for a kind+params combo. May return
    a list of geometries for composite kinds like rectangle/polyline."""
    import Part

    kind = kind.lower()
    if kind == "line":
        s = params["start"]; e = params["end"]
        return [Part.LineSegment(
            App.Vector(float(s[0]), float(s[1]), 0.0),
            App.Vector(float(e[0]), float(e[1]), 0.0),
        )]
    if kind == "circle":
        c = params["center"]; r = float(params["radius"])
        return [Part.Circle(
            App.Vector(float(c[0]), float(c[1]), 0.0),
            App.Vector(0.0, 0.0, 1.0),
            r,
        )]
    if kind == "arc":
        import math
        c = params["center"]; r = float(params["radius"])
        a0 = math.radians(float(params["start_angle"]))
        a1 = math.radians(float(params["end_angle"]))
        circle = Part.Circle(
            App.Vector(float(c[0]), float(c[1]), 0.0),
            App.Vector(0.0, 0.0, 1.0),
            r,
        )
        return [Part.ArcOfCircle(circle, a0, a1)]
    if kind == "rectangle":
        corner = params["corner"]
        w = float(params["width"]); h = float(params["height"])
        x, y = float(corner[0]), float(corner[1])
        V = App.Vector
        return [
            Part.LineSegment(V(x, y, 0),       V(x + w, y, 0)),
            Part.LineSegment(V(x + w, y, 0),   V(x + w, y + h, 0)),
            Part.LineSegment(V(x + w, y + h, 0), V(x, y + h, 0)),
            Part.LineSegment(V(x, y + h, 0),   V(x, y, 0)),
        ]
    if kind == "polyline":
        pts = params["points"]
        V = App.Vector
        segs = []
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            segs.append(Part.LineSegment(
                V(float(p[0]), float(p[1]), 0),
                V(float(q[0]), float(q[1]), 0),
            ))
        return segs
    raise ValueError(f"Unknown geometry kind {kind!r}.")


@tool(
    "add_sketch_geometry",
    (
        "Add geometry to a sketch. kind is one of line, circle, arc, rectangle, "
        "polyline. params carries kind-specific values (points in mm, angles in "
        "degrees). Returns assigned GeoIds. For rectangle, auto-adds coincident "
        "corners + horizontal/vertical constraints."
    ),
    {
        "type": "object",
        "properties": {
            "sketch": {"type": "string"},
            "kind": {"type": "string"},
            "params": {"type": "object"},
            "construction": {"type": "boolean"},
            "doc": {"type": "string"},
        },
        "required": ["sketch", "kind", "params"],
    },
)
async def add_sketch_geometry(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        sk = _resolve_sketch(doc, args["sketch"])
        kind = args["kind"]
        params = args.get("params") or {}
        construction = bool(args.get("construction", False))

        def work():
            # For profile-eligible kinds, always route through profiles.build
            # so the sketch emerges with DOF=0 and no malformed constraints.
            # Construction geometry stays on the hand-rolled path.
            profile_kinds = {"rectangle", "circle", "regular_polygon", "slot", "polyline"}
            if kind.lower() in profile_kinds and not construction:
                prof = dict(params)
                prof["kind"] = kind.lower()
                info = profiles.build(sk, prof)
                doc.recompute()
                return info
            geoms = _make_geometry(kind, params)
            geo_ids = []
            for g in geoms:
                gid = sk.addGeometry(g, construction)
                geo_ids.append(gid)
            doc.recompute()
            return {"geo_ids": geo_ids, "constraint_ids": [], **_sketch_health(sk)}

        result = _with_transaction(doc, f"add_geometry {kind}", work)
        return {"sketch": sk.Name, **result}

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "add_sketch_constraint",
    (
        "Add a constraint to a sketch. kind is one of Coincident, Horizontal, "
        "Vertical, Distance, DistanceX, DistanceY, Radius, Diameter, Equal, "
        "Parallel, Perpendicular, Tangent, PointOnObject, Symmetric. "
        "refs is a flat int list of Sketcher.Constraint positional args (see "
        "module docstring). value is the length/radius for dimensional "
        "constraints, in mm (or degrees for Angle)."
    ),
    {
        "type": "object",
        "properties": {
            "sketch": {"type": "string"},
            "kind": {"type": "string"},
            "refs": {"type": "array", "items": {"type": "integer"}},
            "value": {"type": "number"},
            "doc": {"type": "string"},
        },
        "required": ["sketch", "kind", "refs"],
    },
)
async def add_sketch_constraint(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        sk = _resolve_sketch(doc, args["sketch"])
        kind = args["kind"]
        refs = [int(x) for x in args["refs"]]
        value = args.get("value")

        def work():
            import Sketcher
            parts: list[Any] = [kind, *refs]
            if value is not None:
                parts.append(float(value))
            cid = sk.addConstraint(Sketcher.Constraint(*parts))
            doc.recompute()
            return cid

        cid = _with_transaction(doc, f"constraint {kind}", work)
        return {"sketch": sk.Name, "constraint_id": cid}

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "close_sketch",
    (
        "Recompute and solve a sketch, returning DOF and any conflict / "
        "redundancy info. DOF=0 means fully constrained."
    ),
    {"sketch": str, "doc": str},
)
async def close_sketch(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        sk = _resolve_sketch(doc, args["sketch"])

        def work():
            try:
                sk.solve()
            except Exception:
                pass
            doc.recompute()
            return {
                "sketch": sk.Name,
                "dof": getattr(sk, "DoF", None),
                "conflicting": list(getattr(sk, "ConflictingConstraints", []) or []),
                "redundant": list(getattr(sk, "RedundantConstraints", []) or []),
                "malformed": list(getattr(sk, "MalformedConstraints", []) or []),
            }

        return _with_transaction(doc, f"close_sketch {sk.Name}", work)

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


# --- tools: features ----------------------------------------------------


def _add_feature(body, type_id: str, name: str):
    return body.newObject(type_id, name)


_PAD_TYPES = {"Length", "TwoLengths", "ThroughAll", "UpToFirst", "UpToLast", "UpToFace"}


@tool(
    "pad",
    (
        "Create a PartDesign::Pad extruding a sketch. type defaults to "
        "'Length'. length is in mm. midplane/reversed are booleans."
    ),
    {
        "type": "object",
        "properties": {
            "sketch": {"type": "string"},
            "length": {"type": "number"},
            "type_": {"type": "string", "description": "Pad type"},
            "midplane": {"type": "boolean"},
            "reversed": {"type": "boolean"},
            "name": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["sketch", "length"],
    },
)
async def pad(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        sk = _resolve_sketch(doc, args["sketch"])
        body = None
        for parent in sk.InList:
            if parent.TypeId == "PartDesign::Body":
                body = parent
                break
        if body is None:
            raise ValueError(f"Sketch {sk.Name} is not inside a PartDesign::Body.")
        pad_type = args.get("type_") or "Length"
        if pad_type not in _PAD_TYPES:
            raise ValueError(f"Unknown pad type {pad_type!r}. Use one of {sorted(_PAD_TYPES)}.")
        name = args.get("name") or "Pad"

        # Gate on sketch health before touching the document — a broken sketch
        # would otherwise silently produce an invalid solid (triangle-prism bug).
        try:
            sk.solve()
        except Exception:
            pass
        health = _sketch_health(sk)
        if health["malformed"]:
            return {"__error__": errors.fail("sketch_malformed", sketch=sk.Name, **health)}
        if health["conflicting"] or health["redundant"]:
            return {"__error__": errors.fail("sketch_overconstrained", sketch=sk.Name, **health)}
        if health["dof"] > 0:
            return {"__error__": errors.fail(
                "sketch_underconstrained", sketch=sk.Name,
                hint=f"Sketch has {health['dof']} DOF; add dimensional constraints before padding.",
                **health,
            )}

        def work():
            feat = _add_feature(body, "PartDesign::Pad", name)
            feat.Profile = sk
            feat.Length = float(args["length"])
            feat.Type = pad_type
            midplane = bool(args.get("midplane", False))
            if "SideType" in feat.PropertiesList:
                feat.SideType = "Symmetric" if midplane else "One side"
            elif "Midplane" in feat.PropertiesList:
                feat.Midplane = midplane
            if "Reversed" in feat.PropertiesList:
                feat.Reversed = bool(args.get("reversed", False))
            doc.recompute()
            return feat

        feat = _with_transaction(doc, f"pad {name}", work)
        summary = _summarise_created(doc, [feat.Name])
        summary["body"] = body.Name
        if not summary.get("is_valid_solid"):
            return {"__error__": errors.fail(
                "invalid_solid", feature=feat.Name,
                hint="Pad ran but produced an invalid solid; inspect the sketch profile.",
                **summary,
            )}
        return summary

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return _ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


@tool(
    "pocket",
    (
        "Create a PartDesign::Pocket subtracting an extrusion of a sketch. "
        "length in mm. through_all overrides length with Type='ThroughAll'."
    ),
    {
        "type": "object",
        "properties": {
            "sketch": {"type": "string"},
            "length": {"type": "number"},
            "through_all": {"type": "boolean"},
            "reversed": {"type": "boolean"},
            "name": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["sketch"],
    },
)
async def pocket(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        sk = _resolve_sketch(doc, args["sketch"])
        body = None
        for parent in sk.InList:
            if parent.TypeId == "PartDesign::Body":
                body = parent
                break
        if body is None:
            raise ValueError(f"Sketch {sk.Name} is not inside a PartDesign::Body.")
        name = args.get("name") or "Pocket"
        through = bool(args.get("through_all", False))
        if not through and args.get("length") is None:
            raise ValueError("pocket needs either length or through_all=true.")

        try:
            sk.solve()
        except Exception:
            pass
        health = _sketch_health(sk)
        if health["malformed"]:
            return {"__error__": errors.fail("sketch_malformed", sketch=sk.Name, **health)}
        if health["conflicting"] or health["redundant"]:
            return {"__error__": errors.fail("sketch_overconstrained", sketch=sk.Name, **health)}
        if health["dof"] > 0:
            return {"__error__": errors.fail(
                "sketch_underconstrained", sketch=sk.Name,
                hint=f"Sketch has {health['dof']} DOF; add dimensional constraints before pocketing.",
                **health,
            )}

        def work():
            feat = _add_feature(body, "PartDesign::Pocket", name)
            feat.Profile = sk
            if through:
                feat.Type = "ThroughAll"
            else:
                feat.Type = "Length"
                feat.Length = float(args["length"])
            if "Reversed" in feat.PropertiesList:
                feat.Reversed = bool(args.get("reversed", False))
            doc.recompute()
            return feat

        feat = _with_transaction(doc, f"pocket {name}", work)
        summary = _summarise_created(doc, [feat.Name])
        summary["body"] = body.Name
        return summary

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return _ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


def _edge_refs_to_base(doc, edge_refs):
    """Convert ['Feature.Edge1', ...] → (feature, ['Edge1', ...]).

    All edges must belong to the same feature.
    """
    if not edge_refs:
        raise ValueError("edges must be a non-empty list.")
    feat_name = None
    subs = []
    for ref in edge_refs:
        if "." not in ref:
            raise ValueError(f"Edge ref {ref!r} must be 'Feature.EdgeN'.")
        f, sub = ref.split(".", 1)
        if feat_name is None:
            feat_name = f
        elif feat_name != f:
            raise ValueError(
                "All edges must belong to the same feature for one fillet/chamfer."
            )
        subs.append(sub)
    feat = doc.getObject(feat_name)
    if feat is None:
        raise ValueError(f"Feature {feat_name!r} not found.")
    return feat, subs


@tool(
    "fillet",
    (
        "Add a PartDesign::Fillet on the given edges. edges is a list of "
        "'Feature.EdgeN' strings; all must belong to the same feature."
    ),
    {
        "type": "object",
        "properties": {
            "edges": {"type": "array", "items": {"type": "string"}},
            "radius": {"type": "number"},
            "name": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["edges", "radius"],
    },
)
async def fillet(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        feat, subs = _edge_refs_to_base(doc, args["edges"])
        body = None
        for parent in feat.InList:
            if parent.TypeId == "PartDesign::Body":
                body = parent
                break
        if body is None:
            raise ValueError(f"{feat.Name} is not inside a PartDesign::Body.")
        name = args.get("name") or "Fillet"

        def work():
            f = _add_feature(body, "PartDesign::Fillet", name)
            f.Base = (feat, subs)
            f.Radius = float(args["radius"])
            doc.recompute()
            return f

        f = _with_transaction(doc, f"fillet {name}", work)
        summary = _summarise_created(doc, [f.Name])
        summary["body"] = body.Name
        summary["edges"] = args["edges"]
        return summary

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "chamfer",
    (
        "Add a PartDesign::Chamfer on the given edges. edges is a list of "
        "'Feature.EdgeN' strings; all must belong to the same feature."
    ),
    {
        "type": "object",
        "properties": {
            "edges": {"type": "array", "items": {"type": "string"}},
            "size": {"type": "number"},
            "name": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["edges", "size"],
    },
)
async def chamfer(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        feat, subs = _edge_refs_to_base(doc, args["edges"])
        body = None
        for parent in feat.InList:
            if parent.TypeId == "PartDesign::Body":
                body = parent
                break
        if body is None:
            raise ValueError(f"{feat.Name} is not inside a PartDesign::Body.")
        name = args.get("name") or "Chamfer"

        def work():
            f = _add_feature(body, "PartDesign::Chamfer", name)
            f.Base = (feat, subs)
            if "Size" in f.PropertiesList:
                f.Size = float(args["size"])
            doc.recompute()
            return f

        f = _with_transaction(doc, f"chamfer {name}", work)
        summary = _summarise_created(doc, [f.Name])
        summary["body"] = body.Name
        summary["edges"] = args["edges"]
        return summary

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "set_datum",
    (
        "Edit a feature property in-place. If value_or_expr is a string and "
        "looks like an expression (contains '.', '+', '*' etc), bind it as an "
        "expression (e.g. 'Parameters.Thickness'). Otherwise set the value "
        "directly. Use to bind a Pad.Length to a named parameter."
    ),
    {
        "type": "object",
        "properties": {
            "feature": {"type": "string"},
            "property_": {"type": "string", "description": "Property name, e.g. 'Length'"},
            "value_or_expr": {},
            "doc": {"type": "string"},
        },
        "required": ["feature", "property_", "value_or_expr"],
    },
)
async def set_datum(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        feat = doc.getObject(args["feature"])
        if feat is None:
            raise ValueError(f"No object named {args['feature']!r}.")
        prop = args["property_"]
        val = args["value_or_expr"]
        if prop not in feat.PropertiesList:
            raise ValueError(f"{feat.Name} has no property {prop!r}.")

        def work():
            is_expr = isinstance(val, str) and any(c in val for c in ".+-*/")
            if is_expr:
                feat.setExpression(prop, str(val))
            else:
                setattr(feat, prop, float(val) if isinstance(val, (int, float, str)) else val)
                try:
                    feat.setExpression(prop, None)
                except Exception:
                    pass
            doc.recompute()
            return {"feature": feat.Name, "property": prop, "set": str(val), "expression": is_expr}

        return _with_transaction(doc, f"set_datum {feat.Name}.{prop}", work)

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


# --- tools: project memory / parameters --------------------------------


def _ensure_parameters_spreadsheet(doc):
    """Return the Parameters spreadsheet, creating it on first use."""
    sheet = doc.getObject("Parameters")
    if sheet is None:
        import Spreadsheet  # noqa: F401 — ensures the type is registered
        sheet = doc.addObject("Spreadsheet::Sheet", "Parameters")
        sheet.Label = "Parameters"
    return sheet


def _sync_parameter_to_sheet(doc, name: str, value: float, unit: str) -> None:
    """Write name=value (with alias) into the Parameters sheet.

    Allocates a new row at the bottom if this parameter doesn't already have
    an alias; reuses the existing row otherwise. Column A is the name, column
    B holds the value and is aliased to `<name>`.
    """
    sheet = _ensure_parameters_spreadsheet(doc)
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
)
async def read_project_memory(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        return project_memory.load(doc)

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(str(exc))


@tool(
    "get_parameters",
    "Return the named parameters stored in project memory.",
    {"doc": str},
)
async def get_parameters(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        return {"parameters": project_memory.get_parameters(doc)}

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(str(exc))


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
        doc = _resolve_doc(args.get("doc"))
        name = args["name"]
        value = float(args["value"])
        unit = args.get("unit") or "mm"
        note = args.get("note") or ""

        def work():
            spec = project_memory.set_parameter(doc, name, value, unit, note)
            try:
                _sync_parameter_to_sheet(doc, name, value, unit)
            except Exception as exc:
                App.Console.PrintWarning(
                    f"CADAgent: could not sync parameter {name} to spreadsheet: {exc}\n"
                )
            doc.recompute()
            return {"name": name, **spec}

        return _with_transaction(doc, f"set_parameter {name}", work)

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(f"{exc}\n{traceback.format_exc()}")


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
        doc = _resolve_doc(args.get("doc"))
        return project_memory.write_note(doc, args["section"], args["key"], args["value"])

    try:
        return _ok(run_sync(_do))
    except Exception as exc:
        return _err(str(exc))


@tool(
    "sketch_from_profile",
    (
        "Create a fully-constrained sketch from a structured profile. "
        "profile.kind is one of: rectangle, circle, regular_polygon, slot, "
        "polyline. The resulting sketch has DOF=0; dimensional constraints are "
        "named (Width, Height, Radius, …) so you can bind them to named "
        "parameters with set_datum(value_or_expr='Parameters.<name>')."
    ),
    {
        "type": "object",
        "properties": {
            "plane": {"type": "string", "description": "'XY'|'XZ'|'YZ' or 'Feature.FaceN'"},
            "profile": {"type": "object", "description": "Structured profile — see tool description"},
            "body": {"type": "string", "description": "Body name; defaults to active"},
            "name": {"type": "string", "description": "Optional sketch name"},
            "doc": {"type": "string"},
        },
        "required": ["plane", "profile"],
    },
)
async def sketch_from_profile(args):
    def _do():
        doc = _resolve_doc(args.get("doc"))
        body = _resolve_body(doc, args.get("body"))
        plane = args["plane"]
        sketch_name = args.get("name") or "Sketch"
        profile = args["profile"]

        def work():
            sk = body.newObject("Sketcher::SketchObject", sketch_name)
            support = _resolve_support(doc, body, plane)
            if "AttachmentSupport" in sk.PropertiesList:
                sk.AttachmentSupport = support
            else:
                sk.Support = support
            sk.MapMode = "FlatFace"
            info = profiles.build(sk, profile)
            doc.recompute()
            return sk, info

        sk, info = _with_transaction(doc, f"sketch_from_profile {sketch_name}", work)
        summary = _summarise_created(doc, [sk.Name])
        summary["body"] = body.Name
        summary["plane"] = plane
        summary["profile"] = profile.get("kind")
        summary["named_constraints"] = info.get("named_constraints", {})
        summary.update(_sketch_health(sk))
        if summary["malformed"] or summary["conflicting"] or summary["dof"] > 0:
            return {"__error__": errors.fail(
                "sketch_underconstrained" if summary["dof"] > 0 else "sketch_malformed",
                sketch=sk.Name, **summary,
            )}
        return summary

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return _ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


# --- exports ------------------------------------------------------------

TOOL_FUNCS = [
    create_body,
    create_sketch,
    sketch_from_profile,
    add_sketch_geometry,
    add_sketch_constraint,
    close_sketch,
    pad,
    pocket,
    fillet,
    chamfer,
    set_datum,
    read_project_memory,
    get_parameters,
    set_parameter,
    write_project_memory_note,
]

TOOL_NAMES = [
    "create_body",
    "create_sketch",
    "sketch_from_profile",
    "add_sketch_geometry",
    "add_sketch_constraint",
    "close_sketch",
    "pad",
    "pocket",
    "fillet",
    "chamfer",
    "set_datum",
    "read_project_memory",
    "get_parameters",
    "set_parameter",
    "write_project_memory_note",
]


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in TOOL_NAMES]
