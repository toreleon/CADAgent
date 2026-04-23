# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draft workbench provider — native v2 kinds.

Unlike the v1-passthrough providers, this one implements its operations
directly against FreeCAD's Draft module. It's the first workbench to ship
without a v1 counterpart and serves as the reference shape for future
native providers (Assembly, Sheet Metal, Mesh, …).

Each ``execute`` takes (doc, params) and returns either a FreeCAD object
or a list of objects — the dispatcher's default summarizer extracts names
and builds the standard ``summarise_result`` payload.
"""

from __future__ import annotations

from typing import Any

import FreeCAD as App

from .. import registry
from ..registry import positive_number, required_str, chain


def _import_draft():
    """Lazy import — Draft isn't always available in headless FreeCADCmd."""
    import Draft  # noqa: WPS433 — lazy import is intentional
    return Draft


def _vec(xs):
    """Coerce [x,y,z] (or [x,y]) into App.Vector."""
    if xs is None:
        return App.Vector(0, 0, 0)
    if len(xs) == 2:
        return App.Vector(float(xs[0]), float(xs[1]), 0.0)
    return App.Vector(float(xs[0]), float(xs[1]), float(xs[2]))


# ---- primitives -------------------------------------------------------------

def _make_line(doc, params: dict) -> Any:
    Draft = _import_draft()
    start = _vec(params["start"])
    end = _vec(params["end"])
    obj = Draft.makeLine(start, end)
    doc.recompute()
    return obj


def _make_wire(doc, params: dict) -> Any:
    Draft = _import_draft()
    points = [_vec(p) for p in params["points"]]
    closed = bool(params.get("closed", False))
    obj = Draft.makeWire(points, closed=closed, face=closed)
    doc.recompute()
    return obj


def _make_polygon(doc, params: dict) -> Any:
    Draft = _import_draft()
    faces = int(params["sides"])
    radius = float(params["radius"])
    centre = _vec(params.get("centre"))
    obj = Draft.makePolygon(faces, radius=radius)
    obj.Placement.Base = centre
    doc.recompute()
    return obj


def _make_circle(doc, params: dict) -> Any:
    Draft = _import_draft()
    radius = float(params["radius"])
    centre = _vec(params.get("centre"))
    obj = Draft.makeCircle(radius, placement=App.Placement(centre, App.Rotation()))
    doc.recompute()
    return obj


def _make_arc(doc, params: dict) -> Any:
    Draft = _import_draft()
    radius = float(params["radius"])
    start_angle = float(params.get("start_angle", 0.0))
    end_angle = float(params.get("end_angle", 90.0))
    centre = _vec(params.get("centre"))
    obj = Draft.makeCircle(
        radius,
        placement=App.Placement(centre, App.Rotation()),
        startangle=start_angle,
        endangle=end_angle,
    )
    doc.recompute()
    return obj


def _make_bspline(doc, params: dict) -> Any:
    Draft = _import_draft()
    points = [_vec(p) for p in params["points"]]
    closed = bool(params.get("closed", False))
    obj = Draft.makeBSpline(points, closed=closed, face=closed)
    doc.recompute()
    return obj


# ---- arrays / clones --------------------------------------------------------

def _make_ortho_array(doc, params: dict) -> Any:
    Draft = _import_draft()
    base = doc.getObject(params["source"])
    if base is None:
        raise ValueError(f"No such object {params['source']!r}")
    xv = _vec(params.get("x_offset", [10, 0, 0]))
    yv = _vec(params.get("y_offset", [0, 10, 0]))
    zv = _vec(params.get("z_offset", [0, 0, 0]))
    nx = int(params.get("nx", 2))
    ny = int(params.get("ny", 1))
    nz = int(params.get("nz", 1))
    obj = Draft.makeArray(base, xv, yv, zv, nx, ny, nz)
    doc.recompute()
    return obj


def _make_polar_array(doc, params: dict) -> Any:
    Draft = _import_draft()
    base = doc.getObject(params["source"])
    if base is None:
        raise ValueError(f"No such object {params['source']!r}")
    count = int(params.get("count", 4))
    angle = float(params.get("angle", 360.0))
    centre = _vec(params.get("centre"))
    obj = Draft.makeArray(base, centre, angle, count)
    doc.recompute()
    return obj


def _make_clone(doc, params: dict) -> Any:
    Draft = _import_draft()
    base = doc.getObject(params["source"])
    if base is None:
        raise ValueError(f"No such object {params['source']!r}")
    obj = Draft.make_clone(base)
    doc.recompute()
    return obj


def _make_offset(doc, params: dict) -> Any:
    Draft = _import_draft()
    base = doc.getObject(params["source"])
    if base is None:
        raise ValueError(f"No such object {params['source']!r}")
    delta = float(params["delta"])
    obj = Draft.offset(base, App.Vector(delta, 0, 0), copy=True)
    doc.recompute()
    return obj


# ---- registrations ---------------------------------------------------------

registry.register(
    verb="create", kind="draft.line",
    description="Draft line between two 3D points.",
    params_schema={"start": "list[float]", "end": "list[float]"},
    execute=_make_line,
    preflight=required_str(),  # start/end are lists; no string preflight needed
)

registry.register(
    verb="create", kind="draft.wire",
    description="Draft polyline from a list of points (closed=true → face).",
    params_schema={"points": "list[list[float]]", "closed": "bool?"},
    execute=_make_wire,
)

registry.register(
    verb="create", kind="draft.polygon",
    description="Regular Draft polygon (sides ≥ 3) inscribed in a circle of radius.",
    params_schema={"sides": "int", "radius": "float", "centre": "list[float]?"},
    execute=_make_polygon,
    preflight=positive_number("radius"),
)

registry.register(
    verb="create", kind="draft.circle",
    description="Draft circle of given radius at centre.",
    params_schema={"radius": "float", "centre": "list[float]?"},
    execute=_make_circle,
    preflight=positive_number("radius"),
)

registry.register(
    verb="create", kind="draft.arc",
    description="Draft arc: radius + start/end angles in degrees.",
    params_schema={"radius": "float", "start_angle": "float?", "end_angle": "float?", "centre": "list[float]?"},
    execute=_make_arc,
    preflight=positive_number("radius"),
)

registry.register(
    verb="create", kind="draft.bspline",
    description="Draft B-spline through given points (closed=true → face).",
    params_schema={"points": "list[list[float]]", "closed": "bool?"},
    execute=_make_bspline,
)

registry.register(
    verb="create", kind="draft.array.ortho",
    description="Orthogonal array of an object (nx × ny × nz copies with offsets).",
    params_schema={
        "source": "str",
        "x_offset": "list[float]?", "y_offset": "list[float]?", "z_offset": "list[float]?",
        "nx": "int?", "ny": "int?", "nz": "int?",
    },
    execute=_make_ortho_array,
    preflight=required_str("source"),
)

registry.register(
    verb="create", kind="draft.array.polar",
    description="Polar array of an object around a centre (N copies over angle degrees).",
    params_schema={"source": "str", "count": "int?", "angle": "float?", "centre": "list[float]?"},
    execute=_make_polar_array,
    preflight=required_str("source"),
)

registry.register(
    verb="create", kind="draft.clone",
    description="Linked clone of an existing object (transform-only copy).",
    params_schema={"source": "str"},
    execute=_make_clone,
    preflight=required_str("source"),
)

registry.register(
    verb="modify", kind="draft.offset",
    description="Offset a Draft wire / curve by delta (mm). Creates a new object.",
    params_schema={"source": "str", "delta": "float"},
    execute=_make_offset,
    preflight=chain(required_str("source"), positive_number("delta")),
)
