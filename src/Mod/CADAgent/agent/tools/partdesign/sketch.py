# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sketcher MCP tools: create, add geometry/constraints, close, profile-driven.

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

import traceback
from typing import Any

import FreeCAD as App

from claude_agent_sdk import tool

from ... import errors
from ...gui_thread import run_sync
from .. import profiles
from .._shared import (
    ok,
    err,
    resolve_doc,
    sketch_health,
    summarise_result,
    with_transaction,
)
from ._pd_shared import resolve_body, resolve_sketch, resolve_support


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
        doc = resolve_doc(args.get("doc"))
        body = resolve_body(doc, args.get("body"))
        plane = args.get("plane") or "XY"
        sketch_name = args.get("name") or "Sketch"

        def work():
            sketch = body.newObject("Sketcher::SketchObject", sketch_name)
            support = resolve_support(doc, body, plane)
            # FreeCAD 1.x uses AttachmentSupport; fall back to Support if needed.
            if "AttachmentSupport" in sketch.PropertiesList:
                sketch.AttachmentSupport = support
            else:
                sketch.Support = support
            sketch.MapMode = "FlatFace"
            doc.recompute()
            return sketch

        sk = with_transaction(doc, f"create_sketch {sketch_name}", work)
        summary = summarise_result(doc, [sk.Name])
        summary["body"] = body.Name
        summary["plane"] = plane
        summary.update(sketch_health(sk))
        return summary

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


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
        doc = resolve_doc(args.get("doc"))
        sk = resolve_sketch(doc, args["sketch"])
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
            return {"geo_ids": geo_ids, "constraint_ids": [], **sketch_health(sk)}

        result = with_transaction(doc, f"add_geometry {kind}", work)
        return {"sketch": sk.Name, **result}

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


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
        doc = resolve_doc(args.get("doc"))
        sk = resolve_sketch(doc, args["sketch"])
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

        cid = with_transaction(doc, f"constraint {kind}", work)
        return {"sketch": sk.Name, "constraint_id": cid}

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


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
        doc = resolve_doc(args.get("doc"))
        sk = resolve_sketch(doc, args["sketch"])

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

        return with_transaction(doc, f"close_sketch {sk.Name}", work)

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


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
        doc = resolve_doc(args.get("doc"))
        body = resolve_body(doc, args.get("body"))
        plane = args["plane"]
        sketch_name = args.get("name") or "Sketch"
        profile = args["profile"]

        def work():
            sk = body.newObject("Sketcher::SketchObject", sketch_name)
            support = resolve_support(doc, body, plane)
            if "AttachmentSupport" in sk.PropertiesList:
                sk.AttachmentSupport = support
            else:
                sk.Support = support
            sk.MapMode = "FlatFace"
            info = profiles.build(sk, profile)
            doc.recompute()
            return sk, info

        sk, info = with_transaction(doc, f"sketch_from_profile {sketch_name}", work)
        summary = summarise_result(doc, [sk.Name])
        summary["body"] = body.Name
        summary["plane"] = plane
        summary["profile"] = profile.get("kind")
        summary["named_constraints"] = info.get("named_constraints", {})
        summary.update(sketch_health(sk))
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
        return ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


TOOL_FUNCS = [
    create_sketch,
    sketch_from_profile,
    add_sketch_geometry,
    add_sketch_constraint,
    close_sketch,
]

TOOL_NAMES = [
    "create_sketch",
    "sketch_from_profile",
    "add_sketch_geometry",
    "add_sketch_constraint",
    "close_sketch",
]

