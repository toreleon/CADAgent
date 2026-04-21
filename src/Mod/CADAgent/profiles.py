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

"""Structured sketch profiles → fully-constrained sketches.

The agent passes a small JSON profile (rectangle / circle / regular_polygon /
slot / polyline) and this module builds the geometry *and* the constraints so
the sketch comes out with DOF=0 on the first recompute. This eliminates the
biggest failure mode we saw in practice: under-constrained auto-rectangles
silently padded into junk solids.

Profiles
--------
rectangle       width, height, anchor?='origin'|'center'
circle          radius, center?=[0,0]
regular_polygon sides, circumradius, center?=[0,0], orient?='flat'|'pointy'
slot            length, width, orientation?='horizontal'|'vertical', center?=[0,0]
polyline        points: [[x,y], …], close?=false

Every builder returns a dict with `geo_ids`, `constraint_ids`, `dof`,
`malformed`, `conflicting`, and `label_by_id` for the dimensional constraints
(so macros can bind them to named parameters later).
"""

from __future__ import annotations

import math
from typing import Any

import FreeCAD as App


# Per-profile-kind builders are plain functions on the given `sk` (Sketch).
# Each returns (geo_ids, constraints, named_dims). Constraints are a list of
# Sketcher.Constraint constructor arg-tuples; we only instantiate them at the
# end and batch-add via `sk.addConstraint([...])` so the solver runs once.


_ROOT_GEO = -1  # H/V axes live on GeoId=-1; PointPos=1 is the sketch origin.
_ORIGIN_PT = 1


def _line(start, end):
    import Part  # lazy: Part is resolved inside FreeCAD runtime.
    return Part.LineSegment(
        App.Vector(float(start[0]), float(start[1]), 0.0),
        App.Vector(float(end[0]), float(end[1]), 0.0),
    )


def _circle(center, radius):
    import Part
    return Part.Circle(
        App.Vector(float(center[0]), float(center[1]), 0.0),
        App.Vector(0.0, 0.0, 1.0),
        float(radius),
    )


def _arc(center, radius, a0, a1):
    import Part
    return Part.ArcOfCircle(
        _circle(center, radius),
        math.radians(float(a0)),
        math.radians(float(a1)),
    )


def _rect(profile: dict) -> tuple[list, list, dict]:
    w = float(profile["width"])
    h = float(profile["height"])
    anchor = profile.get("anchor", "origin")
    if anchor == "center":
        x0, y0 = -w / 2, -h / 2
    else:
        x0, y0 = 0.0, 0.0
    x1, y1 = x0 + w, y0 + h

    geoms = [
        _line((x0, y0), (x1, y0)),  # 0 bottom
        _line((x1, y0), (x1, y1)),  # 1 right
        _line((x1, y1), (x0, y1)),  # 2 top
        _line((x0, y1), (x0, y0)),  # 3 left
    ]
    # Relative GeoIds 0..3 map to the order above; the builder returns the
    # *real* GeoIds the sketch assigns, and constraint tuples reference them.
    def cons(real_ids: list[int]):
        g0, g1, g2, g3 = real_ids
        tuples = [
            # Close the corners.
            ("Coincident", g0, 2, g1, 1),
            ("Coincident", g1, 2, g2, 1),
            ("Coincident", g2, 2, g3, 1),
            ("Coincident", g3, 2, g0, 1),
            # Lock orientation.
            ("Horizontal", g0),
            ("Horizontal", g2),
            ("Vertical", g1),
            ("Vertical", g3),
            # Anchor the bottom-left corner to the sketch origin.
            ("Coincident", g3, 2, _ROOT_GEO, _ORIGIN_PT)
            if anchor == "origin"
            else ("Symmetric", g0, 1, g2, 2, _ROOT_GEO, _ORIGIN_PT),
        ]
        # Dimensional constraints — named so macros can bind them to params.
        dims = [
            ("Width", ("DistanceX", g0, 1, g0, 2, w)),
            ("Height", ("DistanceY", g3, 1, g3, 2, h)),
        ]
        return tuples, dims

    return geoms, cons, {}


def _circ(profile: dict) -> tuple[list, list, dict]:
    r = float(profile["radius"])
    cx, cy = profile.get("center", [0.0, 0.0])
    geoms = [_circle((cx, cy), r)]

    def cons(real_ids: list[int]):
        (gid,) = real_ids
        tuples = [
            # Lock the centre to the sketch origin (unless a non-origin centre
            # was requested — in that case skip the anchor and rely on the
            # point-coordinate constraint below).
        ]
        if cx == 0 and cy == 0:
            tuples.append(("Coincident", gid, 3, _ROOT_GEO, _ORIGIN_PT))
        else:
            tuples.append(("DistanceX", _ROOT_GEO, _ORIGIN_PT, gid, 3, float(cx)))
            tuples.append(("DistanceY", _ROOT_GEO, _ORIGIN_PT, gid, 3, float(cy)))
        dims = [("Radius", ("Radius", gid, r))]
        return tuples, dims

    return geoms, cons, {}


def _regular_polygon(profile: dict) -> tuple[list, list, dict]:
    sides = int(profile["sides"])
    if sides < 3:
        raise ValueError("regular_polygon.sides must be ≥ 3")
    R = float(profile["circumradius"])
    cx, cy = profile.get("center", [0.0, 0.0])
    orient = profile.get("orient", "flat")
    rot = 0.0 if orient == "pointy" else math.pi / sides

    pts = [
        (cx + R * math.cos(rot + 2 * math.pi * i / sides),
         cy + R * math.sin(rot + 2 * math.pi * i / sides))
        for i in range(sides)
    ]
    geoms = [_line(pts[i], pts[(i + 1) % sides]) for i in range(sides)]

    def cons(real_ids: list[int]):
        tuples: list[tuple] = []
        for i, gid in enumerate(real_ids):
            nxt = real_ids[(i + 1) % sides]
            tuples.append(("Coincident", gid, 2, nxt, 1))
        # Equal length for all sides.
        for i in range(1, sides):
            tuples.append(("Equal", real_ids[0], real_ids[i]))
        # Anchor first vertex to keep rotation + position locked.
        tuples.append(("DistanceX", _ROOT_GEO, _ORIGIN_PT, real_ids[0], 1, float(pts[0][0])))
        tuples.append(("DistanceY", _ROOT_GEO, _ORIGIN_PT, real_ids[0], 1, float(pts[0][1])))
        # One edge length fixes the polygon size.
        side_len = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
        dims = [("SideLength", ("Distance", real_ids[0], side_len))]
        return tuples, dims

    return geoms, cons, {}


def _slot(profile: dict) -> tuple[list, list, dict]:
    L = float(profile["length"])
    W = float(profile["width"])
    orientation = profile.get("orientation", "horizontal")
    cx, cy = profile.get("center", [0.0, 0.0])
    r = W / 2

    if orientation == "horizontal":
        hx = (L - W) / 2
        left_c = (cx - hx, cy)
        right_c = (cx + hx, cy)
        top_start = (cx - hx, cy + r); top_end = (cx + hx, cy + r)
        bot_start = (cx + hx, cy - r); bot_end = (cx - hx, cy - r)
        arc_left = _arc(left_c, r, 90, 270)
        arc_right = _arc(right_c, r, -90, 90)
    else:
        hy = (L - W) / 2
        bot_c = (cx, cy - hy); top_c = (cx, cy + hy)
        top_start = (cx - r, cy + hy); top_end = (cx + r, cy + hy)
        bot_start = (cx + r, cy - hy); bot_end = (cx - r, cy - hy)
        arc_left = _arc(bot_c, r, 180, 360)
        arc_right = _arc(top_c, r, 0, 180)

    geoms = [
        _line(top_start, top_end),
        _line(bot_start, bot_end),
        arc_left,
        arc_right,
    ]

    def cons(real_ids: list[int]):
        g_top, g_bot, g_al, g_ar = real_ids
        tuples: list[tuple] = []
        if orientation == "horizontal":
            tuples.extend([
                ("Horizontal", g_top),
                ("Horizontal", g_bot),
                ("Coincident", g_al, 1, g_top, 1),
                ("Coincident", g_al, 2, g_bot, 2),
                ("Coincident", g_ar, 1, g_bot, 1),
                ("Coincident", g_ar, 2, g_top, 2),
            ])
        else:
            tuples.extend([
                ("Vertical", g_top),
                ("Vertical", g_bot),
                ("Coincident", g_al, 1, g_top, 2),
                ("Coincident", g_al, 2, g_bot, 1),
                ("Coincident", g_ar, 1, g_bot, 2),
                ("Coincident", g_ar, 2, g_top, 1),
            ])
        tuples.append(("Equal", g_al, g_ar))
        tuples.append(("Equal", g_top, g_bot))
        # Anchor centre. Use the arc centre nearest the sketch origin as the
        # anchor point to avoid compounding tolerances.
        if orientation == "horizontal":
            tuples.append(("DistanceX", _ROOT_GEO, _ORIGIN_PT, g_al, 3, float(cx - (L - W) / 2)))
            tuples.append(("DistanceY", _ROOT_GEO, _ORIGIN_PT, g_al, 3, float(cy)))
        else:
            tuples.append(("DistanceX", _ROOT_GEO, _ORIGIN_PT, g_al, 3, float(cx)))
            tuples.append(("DistanceY", _ROOT_GEO, _ORIGIN_PT, g_al, 3, float(cy - (L - W) / 2)))
        dims = [
            ("Length", ("Distance", g_top, L - W)),
            ("Width", ("Radius", g_al, r)),
        ]
        return tuples, dims

    return geoms, cons, {}


def _polyline(profile: dict) -> tuple[list, list, dict]:
    pts = list(profile["points"])
    close = bool(profile.get("close", False))
    if close and pts[0] != pts[-1]:
        pts.append(pts[0])
    if len(pts) < 2:
        raise ValueError("polyline.points must have ≥ 2 points")
    geoms = [_line(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    def cons(real_ids: list[int]):
        tuples: list[tuple] = []
        for i in range(len(real_ids) - 1):
            tuples.append(("Coincident", real_ids[i], 2, real_ids[i + 1], 1))
        if close:
            tuples.append(("Coincident", real_ids[-1], 2, real_ids[0], 1))
        # Anchor the first point; pin every vertex to its literal coordinates
        # so DOF=0 without the caller having to add dimensions.
        for i, gid in enumerate(real_ids):
            x, y = pts[i]
            tuples.append(("DistanceX", _ROOT_GEO, _ORIGIN_PT, gid, 1, float(x)))
            tuples.append(("DistanceY", _ROOT_GEO, _ORIGIN_PT, gid, 1, float(y)))
        # Last vertex (only if open). Closed profiles reuse pts[0].
        if not close and real_ids:
            x, y = pts[-1]
            tuples.append(("DistanceX", _ROOT_GEO, _ORIGIN_PT, real_ids[-1], 2, float(x)))
            tuples.append(("DistanceY", _ROOT_GEO, _ORIGIN_PT, real_ids[-1], 2, float(y)))
        return tuples, []

    return geoms, cons, {}


_BUILDERS = {
    "rectangle": _rect,
    "circle": _circ,
    "regular_polygon": _regular_polygon,
    "slot": _slot,
    "polyline": _polyline,
}


def build(sk, profile: dict) -> dict:
    """Build a profile on the given sketch. Returns diagnostics (DOF, etc)
    and a `named_constraints` map for dimensional constraints that macros can
    later bind to named parameters via `setExpression`.
    """
    import Sketcher  # noqa: F401 — resolved inside FreeCAD

    kind = (profile.get("kind") or "").lower()
    if kind not in _BUILDERS:
        raise ValueError(f"Unknown profile kind {kind!r}. Known: {sorted(_BUILDERS)}")

    geoms, make_cons, _meta = _BUILDERS[kind](profile)

    # Add geometry one by one so we capture the real GeoIds the sketch assigns.
    real_ids: list[int] = []
    for g in geoms:
        real_ids.append(sk.addGeometry(g, False))

    tuples, dims = make_cons(real_ids)

    # Batch the non-dimensional constraints first, then the dimensional ones,
    # so FreeCAD's solver only fights the geometry once.
    non_dim = [Sketcher.Constraint(*t) for t in tuples]
    con_ids = sk.addConstraint(non_dim) if non_dim else []
    if isinstance(con_ids, int):
        con_ids = [con_ids]

    named_constraints: dict[str, int] = {}
    for label, args in dims:
        cid = sk.addConstraint(Sketcher.Constraint(*args))
        named_constraints[label] = cid
        try:
            sk.renameConstraint(cid, label)
        except Exception:
            pass

    try:
        sk.solve()
    except Exception:
        pass

    return {
        "kind": kind,
        "geo_ids": real_ids,
        "constraint_ids": list(con_ids) + list(named_constraints.values()),
        "named_constraints": named_constraints,
        "dof": int(getattr(sk, "DoF", -1)),
        "malformed": list(getattr(sk, "MalformedConstraints", []) or []),
        "conflicting": list(getattr(sk, "ConflictingConstraints", []) or []),
        "redundant": list(getattr(sk, "RedundantConstraints", []) or []),
    }


def available_kinds() -> list[str]:
    return sorted(_BUILDERS)
