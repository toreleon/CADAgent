# SPDX-License-Identifier: LGPL-2.1-or-later
"""Geometry introspection over a tiny query DSL.

One worker handler, ``inspect.query``, parses small whitespace-separated
queries the agent sends as plain strings and returns structured JSON. The
DSL exists so the agent (and the auto-probe hook) can ask cheap questions
without writing FreeCADCmd Bash scripts:

    bbox                          → whole-doc bounding box
    bbox of central_hub           → one object's bbox
    face_types                    → {Plane: 12, Cylinder: 4, Sphere: 1, ...}
    face_types of body
    holes diameter=15             → cylindrical concave faces matching Ø15
    holes diameter=8 axis=z       → ... aligned with Z
    bosses diameter=30            → cylindrical convex faces matching Ø30
    slots width=8 length=20       → obround through-cuts
    fillets radius=10             → toroidal faces matching the radius
    spheres radius=250            → spherical face patches
    solids                        → per-solid validity + face/edge counts
    section z=35                  → cross-section area / perimeter / bbox
    mass                          → volume / centerOfMass / inertia
    mass of body

Tolerances default to 0.5 mm for diameters/lengths and 1.0 mm for big
sphere radii (the dome case). Override with ``tol=NN``.
"""

from __future__ import annotations

import math
from typing import Any

import FreeCAD as App  # type: ignore[import-not-found]
import Part  # type: ignore[import-not-found]

from .. import registry
from . import document as _doc


# ---------------------------------------------------------------------------
# query parser (very small)
# ---------------------------------------------------------------------------


def _parse(query: str) -> tuple[str, str | None, dict[str, str]]:
    """Return (kind, target_object_or_None, opts_dict).

    ``query`` is whitespace-separated tokens. The first token is the kind.
    Tokens of the form ``KEY=VALUE`` go into ``opts``. The two tokens
    ``of NAME`` (anywhere after the kind) bind ``target = NAME``.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("inspect.query: empty query")
    tokens = query.strip().split()
    kind = tokens[0].lower()
    target: str | None = None
    opts: dict[str, str] = {}
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t == "of" and i + 1 < len(tokens):
            target = tokens[i + 1]
            i += 2
            continue
        if "=" in t:
            k, v = t.split("=", 1)
            opts[k.strip().lower()] = v.strip()
        i += 1
    return kind, target, opts


def _opt_float(opts: dict[str, str], name: str) -> float | None:
    v = opts.get(name)
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"inspect.query: option {name}= must be a number, got {v!r}")


def _tol(opts: dict[str, str], default: float) -> float:
    v = _opt_float(opts, "tol")
    return default if v is None else v


def _opt_axis(opts: dict[str, str]) -> tuple[float, float, float] | None:
    v = opts.get("axis")
    if not v:
        return None
    s = v.strip().lower()
    if s in ("x", "+x"):
        return (1.0, 0.0, 0.0)
    if s == "-x":
        return (-1.0, 0.0, 0.0)
    if s in ("y", "+y"):
        return (0.0, 1.0, 0.0)
    if s == "-y":
        return (0.0, -1.0, 0.0)
    if s in ("z", "+z"):
        return (0.0, 0.0, 1.0)
    if s == "-z":
        return (0.0, 0.0, -1.0)
    parts = [p for p in s.replace(",", " ").split() if p]
    if len(parts) == 3:
        try:
            x, y, z = (float(p) for p in parts)
            n = math.sqrt(x * x + y * y + z * z)
            if n == 0:
                return None
            return (x / n, y / n, z / n)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# helpers — pulling shapes out of the doc
# ---------------------------------------------------------------------------


_INF_THRESHOLD = 1e9  # FreeCAD datum lines/planes report bbox dims ~1e30


def _has_finite_bbox(shape: Any) -> bool:
    try:
        b = shape.BoundBox
        for v in (b.XLength, b.YLength, b.ZLength):
            if v != v or abs(v) > _INF_THRESHOLD:  # NaN or essentially infinite
                return False
        return True
    except Exception:
        return False


def _all_part_features(doc: Any) -> list[Any]:
    """Real solids/faces only — skip Origin datum lines/planes whose Shape
    has an infinite bbox and would otherwise poison the all-doc bounds."""
    out = []
    for o in doc.Objects:
        s = getattr(o, "Shape", None)
        if s is None or s.isNull():
            continue
        if not _has_finite_bbox(s):
            continue
        # Skip pure construction objects with no faces and no solids — they
        # contribute nothing to envelope/topology metrics.
        if len(s.Faces) == 0 and len(s.Solids) == 0:
            continue
        out.append(o)
    return out


def _shapes(doc: Any, target: str | None) -> list[tuple[str, Any]]:
    if target:
        obj = doc.getObject(target)
        if obj is None or getattr(obj, "Shape", None) is None or obj.Shape.isNull():
            raise KeyError(f"no object with non-null shape: {target!r}")
        return [(obj.Name, obj.Shape)]
    return [(o.Name, o.Shape) for o in _all_part_features(doc)]


def _surface_kind(face: Any) -> str:
    """Return a stable short string for the face's surface kind.

    FreeCAD class names vary slightly by version (``Toroid`` vs ``Torus``);
    we normalize to: Plane, Cylinder, Sphere, Torus, Cone, BSpline, Other.
    """
    surf = getattr(face, "Surface", None)
    name = type(surf).__name__ if surf is not None else ""
    if name == "Plane":
        return "Plane"
    if name == "Cylinder":
        return "Cylinder"
    if name == "Sphere":
        return "Sphere"
    if name in ("Toroid", "Torus"):
        return "Torus"
    if name == "Cone":
        return "Cone"
    if "BSpline" in name or "Bezier" in name:
        return "BSpline"
    return name or "Other"


def _vec(v: Any) -> list[float]:
    return [float(v.x), float(v.y), float(v.z)]


def _approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _axis_match(a: tuple[float, float, float], b: tuple[float, float, float], tol: float = 0.05) -> bool:
    dot = abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])
    return dot >= 1.0 - tol


# ---------------------------------------------------------------------------
# kind handlers
# ---------------------------------------------------------------------------


def _bbox_of_shape(shape: Any) -> dict[str, Any]:
    b = shape.BoundBox
    return {
        "xmin": float(b.XMin), "ymin": float(b.YMin), "zmin": float(b.ZMin),
        "xmax": float(b.XMax), "ymax": float(b.YMax), "zmax": float(b.ZMax),
        "size": [float(b.XLength), float(b.YLength), float(b.ZLength)],
    }


def _kind_bbox(doc: Any, target: str | None, opts: dict[str, str]) -> dict[str, Any]:
    if target:
        shapes = _shapes(doc, target)
        return {"object": target, **_bbox_of_shape(shapes[0][1])}
    feats = _all_part_features(doc)
    if not feats:
        return {"empty": True}
    union = feats[0].Shape
    for f in feats[1:]:
        try:
            union = union.fuse(f.Shape)
        except Exception:
            # If a fuse fails just take the cumulative bbox manually
            pass
    # Cumulative bbox is more robust than a real fuse for measurement purposes.
    b = App.BoundBox()
    for f in feats:
        b.add(f.Shape.BoundBox)
    return {
        "object": "<all>",
        "xmin": float(b.XMin), "ymin": float(b.YMin), "zmin": float(b.ZMin),
        "xmax": float(b.XMax), "ymax": float(b.YMax), "zmax": float(b.ZMax),
        "size": [float(b.XLength), float(b.YLength), float(b.ZLength)],
    }


def _kind_face_types(doc: Any, target: str | None, opts: dict[str, str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for _, shape in _shapes(doc, target):
        for face in shape.Faces:
            k = _surface_kind(face)
            counts[k] = counts.get(k, 0) + 1
    return {"counts": counts, "total_faces": sum(counts.values())}


def _cyl_face_records(shape: Any) -> list[dict[str, Any]]:
    """Enumerate cylindrical faces with concavity classification.

    Concave (=hole) is detected by comparing the face's outward normal at a
    sample point with the vector from the cylinder axis to that point. If
    they point in opposite directions the surface curves inward → hole.
    """
    out: list[dict[str, Any]] = []
    for face in shape.Faces:
        if _surface_kind(face) != "Cylinder":
            continue
        surf = face.Surface  # Part.Cylinder
        radius = float(surf.Radius)
        axis = _vec(surf.Axis)
        center = _vec(surf.Center)
        # Sample mid-parameter point.
        try:
            u0, u1, v0, v1 = face.ParameterRange
            u = 0.5 * (u0 + u1)
            v = 0.5 * (v0 + v1)
            p = face.valueAt(u, v)
            nrm = face.normalAt(u, v)
        except Exception:
            continue
        # Vector from cylinder axis line to p (radial outward direction).
        # Project (p - center) onto plane perpendicular to axis.
        ax = App.Vector(*axis)
        c = App.Vector(*center)
        d = p - c
        radial = d - ax * (d.dot(ax))
        if radial.Length == 0:
            continue
        radial.normalize()
        try:
            nrm.normalize()
        except Exception:
            pass
        is_hole = nrm.dot(radial) < 0  # normal points toward axis → concave
        # Effective center along the cylinder axis for the face midpoint.
        proj = c + ax * ((p - c).dot(ax))
        try:
            depth = float(face.BoundBox.DiagonalLength)
        except Exception:
            depth = 0.0
        out.append({
            "diameter": 2.0 * radius,
            "radius": radius,
            "axis": axis,
            "center": _vec(proj),
            "depth": depth,
            "is_hole": bool(is_hole),
        })
    return out


def _kind_holes_or_bosses(doc: Any, target: str | None, opts: dict[str, str], *, want_hole: bool) -> dict[str, Any]:
    diameter = _opt_float(opts, "diameter")
    tol = _tol(opts, 0.5)
    axis_match = _opt_axis(opts)
    found: list[dict[str, Any]] = []
    for _, shape in _shapes(doc, target):
        for rec in _cyl_face_records(shape):
            if rec["is_hole"] != want_hole:
                continue
            if diameter is not None and not _approx(rec["diameter"], diameter, tol):
                continue
            if axis_match is not None and not _axis_match(tuple(rec["axis"]), axis_match):
                continue
            found.append(rec)
    return {"count": len(found), "items": found}


def _kind_slots(doc: Any, target: str | None, opts: dict[str, str]) -> dict[str, Any]:
    """Slot = two parallel concave half-cylinders connected by two planar caps.

    We find concave cylinder pairs whose axes are parallel and whose centers
    are separated by ``length - width`` (slot center-to-center separation).
    Width = 2*radius. Length is the separation plus the width. We dedupe
    cylinder records by (center, axis) so an end-cap arc that shows up as
    multiple OCC face patches doesn't pair with itself.

    Tolerance default is 1.0mm (looser than other queries) because OCC's
    boolean fillets can shift end-cap centers by a few tenths.
    """
    width = _opt_float(opts, "width")
    length = _opt_float(opts, "length")
    tol = _tol(opts, 1.0)
    found: list[dict[str, Any]] = []
    for _, shape in _shapes(doc, target):
        records = [r for r in _cyl_face_records(shape) if r["is_hole"]]
        # Dedupe: a concave half-cylinder cap can appear as multiple face
        # patches sharing the same axis-projected center. Keep one per
        # (rounded center, diameter) bucket.
        seen: dict[tuple, dict[str, Any]] = {}
        for r in records:
            key = (
                round(r["center"][0], 2), round(r["center"][1], 2), round(r["center"][2], 2),
                round(r["diameter"], 2),
            )
            seen.setdefault(key, r)
        cyls = list(seen.values())
        if width is not None:
            cyls = [r for r in cyls if _approx(r["diameter"], width, tol)]
        used: set[int] = set()
        for i, a in enumerate(cyls):
            if i in used:
                continue
            best: tuple[float, int] | None = None  # (length_diff, j)
            for j in range(i + 1, len(cyls)):
                if j in used:
                    continue
                b = cyls[j]
                if not _approx(a["diameter"], b["diameter"], tol):
                    continue
                if not _axis_match(tuple(a["axis"]), tuple(b["axis"])):
                    continue
                ca = App.Vector(*a["center"])
                cb = App.Vector(*b["center"])
                ax = App.Vector(*a["axis"])
                delta = ca - cb
                # Distance perpendicular to the cylinder axis — i.e. along
                # the slot's long axis. We must NOT use the raw 3D length
                # because the face midpoints can sit at different Z when
                # the slot is cut through a non-flat top (e.g. a dome).
                perp = delta - ax * (delta.dot(ax))
                sep = perp.Length
                this_length = sep + a["diameter"]
                if length is not None:
                    diff = abs(this_length - length)
                    if diff > tol:
                        continue
                    if best is None or diff < best[0]:
                        best = (diff, j)
                else:
                    best = (0.0, j)
                    break
            if best is None:
                continue
            j = best[1]
            b = cyls[j]
            ca = App.Vector(*a["center"])
            cb = App.Vector(*b["center"])
            ax = App.Vector(*a["axis"])
            delta = ca - cb
            perp = delta - ax * (delta.dot(ax))
            this_length = perp.Length + a["diameter"]
            used.add(i); used.add(j)
            center = (ca + cb).multiply(0.5)
            long_axis = (cb - ca)
            if long_axis.Length > 0:
                long_axis.normalize()
            found.append({
                "width": a["diameter"],
                "length": this_length,
                "center": _vec(center),
                "long_axis": _vec(long_axis) if long_axis.Length else [0.0, 0.0, 0.0],
                "axis": a["axis"],
            })
    return {"count": len(found), "items": found}


def _kind_fillets(doc: Any, target: str | None, opts: dict[str, str]) -> dict[str, Any]:
    """Fillet = toroidal face. Radius = MinorRadius."""
    radius = _opt_float(opts, "radius")
    tol = _tol(opts, 0.5)
    found: list[dict[str, Any]] = []
    for _, shape in _shapes(doc, target):
        for face in shape.Faces:
            if _surface_kind(face) != "Torus":
                continue
            surf = face.Surface
            r_minor = float(getattr(surf, "MinorRadius", 0.0))
            r_major = float(getattr(surf, "MajorRadius", 0.0))
            if radius is not None and not _approx(r_minor, radius, tol):
                continue
            try:
                center = _vec(surf.Center)
            except Exception:
                center = [0.0, 0.0, 0.0]
            found.append({
                "radius": r_minor,
                "major_radius": r_major,
                "center": center,
            })
    return {"count": len(found), "items": found}


def _kind_spheres(doc: Any, target: str | None, opts: dict[str, str]) -> dict[str, Any]:
    radius = _opt_float(opts, "radius")
    tol = _tol(opts, 1.0)
    found: list[dict[str, Any]] = []
    for _, shape in _shapes(doc, target):
        for face in shape.Faces:
            if _surface_kind(face) != "Sphere":
                continue
            surf = face.Surface
            r = float(getattr(surf, "Radius", 0.0))
            if radius is not None and not _approx(r, radius, tol):
                continue
            try:
                center = _vec(surf.Center)
            except Exception:
                center = [0.0, 0.0, 0.0]
            found.append({"radius": r, "center": center})
    return {"count": len(found), "items": found}


def _kind_solids(doc: Any, target: str | None, opts: dict[str, str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for name, shape in _shapes(doc, target):
        try:
            volume = float(shape.Volume)
        except Exception:
            volume = 0.0
        items.append({
            "name": name,
            "isValid": bool(shape.isValid()),
            "isClosed": bool(shape.isClosed()) if hasattr(shape, "isClosed") else None,
            "n_faces": len(shape.Faces),
            "n_edges": len(shape.Edges),
            "n_vertices": len(shape.Vertexes),
            "n_solids": len(shape.Solids),
            "volume": volume,
        })
    return {"count": len(items), "items": items}


def _kind_section(doc: Any, target: str | None, opts: dict[str, str]) -> dict[str, Any]:
    plane = (opts.get("plane") or "xy").lower()
    z = _opt_float(opts, "z") or 0.0
    x = _opt_float(opts, "x") or 0.0
    y = _opt_float(opts, "y") or 0.0
    if plane == "xy":
        normal = App.Vector(0, 0, 1); origin = App.Vector(0, 0, z)
    elif plane == "xz":
        normal = App.Vector(0, 1, 0); origin = App.Vector(0, y, 0)
    elif plane == "yz":
        normal = App.Vector(1, 0, 0); origin = App.Vector(x, 0, 0)
    else:
        raise ValueError(f"inspect.query: unknown plane {plane!r}")
    items: list[dict[str, Any]] = []
    for name, shape in _shapes(doc, target):
        try:
            section = shape.section(Part.Plane(origin, normal).toShape())
        except Exception as exc:
            items.append({"name": name, "error": str(exc)})
            continue
        b = section.BoundBox
        items.append({
            "name": name,
            "n_edges": len(section.Edges),
            "perimeter": float(sum(e.Length for e in section.Edges)),
            "bbox": [float(b.XLength), float(b.YLength), float(b.ZLength)],
        })
    return {"plane": plane, "items": items}


def _kind_mass(doc: Any, target: str | None, opts: dict[str, str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for name, shape in _shapes(doc, target):
        try:
            volume = float(shape.Volume)
        except Exception:
            volume = 0.0
        try:
            com = _vec(shape.CenterOfMass)
        except Exception:
            com = [0.0, 0.0, 0.0]
        try:
            area = float(shape.Area)
        except Exception:
            area = 0.0
        items.append({
            "name": name,
            "volume": volume,
            "area": area,
            "center_of_mass": com,
        })
    return {"items": items}


_KIND_HANDLERS = {
    "bbox": _kind_bbox,
    "face_types": _kind_face_types,
    "holes": lambda d, t, o: _kind_holes_or_bosses(d, t, o, want_hole=True),
    "bosses": lambda d, t, o: _kind_holes_or_bosses(d, t, o, want_hole=False),
    "slots": _kind_slots,
    "fillets": _kind_fillets,
    "spheres": _kind_spheres,
    "solids": _kind_solids,
    "section": _kind_section,
    "mass": _kind_mass,
}


def kinds() -> list[str]:
    return sorted(_KIND_HANDLERS)


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


@registry.handler("inspect.query")
def inspect_query(query: str) -> dict[str, Any]:
    """Run a single DSL query against the worker's current document."""
    kind, target, opts = _parse(query)
    fn = _KIND_HANDLERS.get(kind)
    if fn is None:
        raise ValueError(
            f"inspect.query: unknown kind {kind!r}; one of {kinds()}"
        )
    doc = _doc.current_doc()
    return {"kind": kind, "target": target, "result": fn(doc, target, opts)}


@registry.handler("inspect.probe")
def inspect_probe() -> dict[str, Any]:
    """Cheap standard probe used by the auto-inspect hook.

    Returns ``bbox``, ``face_types`` and ``solids`` in one round-trip so
    the hook only crosses the JSON pipe once per Bash mutation.
    """
    doc = _doc.current_doc()
    return {
        "bbox": _kind_bbox(doc, None, {}),
        "face_types": _kind_face_types(doc, None, {}),
        "solids": _kind_solids(doc, None, {}),
    }
