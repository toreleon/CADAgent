# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native Sketcher providers.

PR 3 of the tool-layer generalize pass: port the five sketch ops off the
v1 passthrough onto Pydantic-validated native handlers that return the
uniform envelope.

  create:partdesign.sketch              — blank sketch on a plane/face
  create:partdesign.sketch_from_profile — fully-constrained profile sketch
  modify:sketcher.geometry.add          — add geometry (line/circle/…)
  modify:sketcher.constraint.add        — add a constraint
  verify:sketcher.close                 — solve + report health

Every envelope carries a ``health`` extra with ``dof/malformed/conflicting/
redundant`` so the agent can see the sketch state without a second verify
call. Sketch-from-profile surfaces ``sketch_malformed`` / ``sketch_underconstrained``
through the error path when the profile did not resolve to DoF=0.

Constraint refs: two accepted forms.

  1. ``refs: list[int]`` (raw, canonical) — flat positional args for
     ``Sketcher.Constraint``. See docstring of the old v1 module for the
     layout; kept for backward compatibility and for the SKETCHER subagent.
  2. ``anchors: list[{geo_id, pos}]`` (ergonomic) — each anchor names a
     geometry + one of ``edge|start|end|center`` (1:1 with PointPos
     0/1/2/3). Translated to the raw tuple internally. Lets the agent
     reason about "line's end point" instead of "int position 2".

If both are supplied ``anchors`` wins.
"""

from __future__ import annotations

from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from .. import registry
from ..envelope import err_envelope, ok_envelope
from ..tools import profiles
from ..tools._shared import sketch_health, with_transaction
from ..tools.partdesign._pd_shared import resolve_body, resolve_sketch, resolve_support


# Sketcher::Constraint PointPos convention: 0=edge, 1=start, 2=end, 3=center.
_POS_MAP = {"edge": 0, "start": 1, "end": 2, "center": 3}


# ---------------------------------------------------------------------------
# create:partdesign.sketch — blank sketch
# ---------------------------------------------------------------------------

class SketchParams(BaseModel):
    plane: str = Field(
        ...,
        description="'XY'|'XZ'|'YZ' (body origin plane) or 'Feature.FaceN'.",
    )
    body: Optional[str] = Field(None, description="Body name; defaults to active.")
    name: str = Field("Sketch", description="Preferred sketch name; FreeCAD may suffix.")
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}


def _create_sketch(doc, params: dict[str, Any]) -> dict:
    kind = "partdesign.sketch"
    body = resolve_body(doc, params.get("body"))
    plane = params["plane"]
    name = params["name"]

    def work():
        sk = body.newObject("Sketcher::SketchObject", name)
        support = resolve_support(doc, body, plane)
        if "AttachmentSupport" in sk.PropertiesList:
            sk.AttachmentSupport = support
        else:
            sk.Support = support
        sk.MapMode = "FlatFace"
        doc.recompute()
        return sk

    sk = with_transaction(doc, f"create_sketch {name}", work)
    return ok_envelope(
        kind, doc=doc, created=[sk.Name],
        extras={"body": body.Name, "plane": plane, "health": sketch_health(sk)},
    )


registry.register(
    verb="create",
    kind="partdesign.sketch",
    description=(
        "Create a blank Sketcher sketch on a plane or face. plane='XY'|'XZ'|"
        "'YZ' for the body origin, or 'Feature.FaceN'. body defaults to the "
        "active body."
    ),
    params_schema={"plane": "str", "body": "str?", "name": "str?", "doc": "str?"},
    execute=_create_sketch,
    native=True,
    model=SketchParams,
    example={"plane": "XY"},
)


# ---------------------------------------------------------------------------
# create:partdesign.sketch_from_profile
# ---------------------------------------------------------------------------

class SketchFromProfileParams(BaseModel):
    plane: str = Field(..., description="'XY'|'XZ'|'YZ' or 'Feature.FaceN'.")
    profile: dict[str, Any] = Field(
        ..., description="Structured profile dict; see profiles.build.",
    )
    body: Optional[str] = None
    name: str = "Sketch"
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}


def _sketch_from_profile(doc, params: dict[str, Any]) -> dict:
    kind = "partdesign.sketch_from_profile"
    body = resolve_body(doc, params.get("body"))
    plane = params["plane"]
    name = params["name"]
    profile = params["profile"]

    if not isinstance(profile, dict) or not profile.get("kind"):
        return err_envelope(
            kind, error_kind="invalid_argument",
            message="profile must be a dict with a 'kind' key.",
            hint="cad_inspect(kind='schema.describe', params={'of_kind': 'partdesign.sketch_from_profile'}) for examples.",
            doc=doc,
        )

    def work():
        sk = body.newObject("Sketcher::SketchObject", name)
        support = resolve_support(doc, body, plane)
        if "AttachmentSupport" in sk.PropertiesList:
            sk.AttachmentSupport = support
        else:
            sk.Support = support
        sk.MapMode = "FlatFace"
        info = profiles.build(sk, profile)
        doc.recompute()
        return sk, info

    sk, info = with_transaction(doc, f"sketch_from_profile {name}", work)
    health = sketch_health(sk)
    extras = {
        "body": body.Name, "plane": plane,
        "profile": profile.get("kind"),
        "named_constraints": info.get("named_constraints", {}),
        "health": health,
    }
    if health["malformed"] or health["conflicting"]:
        return err_envelope(
            kind, error_kind="sketch_malformed",
            doc=doc,
            extras={"sketch": sk.Name, **extras},
        )
    if health["dof"] and health["dof"] > 0:
        return err_envelope(
            kind, error_kind="sketch_underconstrained",
            hint=f"Profile resolved with {health['dof']} DoF; check profile params.",
            doc=doc,
            extras={"sketch": sk.Name, **extras},
        )
    return ok_envelope(kind, doc=doc, created=[sk.Name], extras=extras)


registry.register(
    verb="create",
    kind="partdesign.sketch_from_profile",
    description=(
        "Create a fully-constrained sketch (DoF=0) from a structured profile. "
        "profile.kind ∈ {rectangle, circle, regular_polygon, slot, polyline}. "
        "Dimensional constraints are named so you can bind them to "
        "Parameters.<name> via modify:datum.set."
    ),
    params_schema={"plane": "str", "profile": "dict", "body": "str?", "name": "str?", "doc": "str?"},
    execute=_sketch_from_profile,
    native=True,
    model=SketchFromProfileParams,
    example={
        "plane": "XY",
        "profile": {"kind": "rectangle", "width": 20, "height": 10, "center": [0, 0]},
    },
)


# ---------------------------------------------------------------------------
# modify:sketcher.geometry.add
# ---------------------------------------------------------------------------

class GeometryAddParams(BaseModel):
    sketch: str
    kind: str = Field(..., description="line | circle | arc | rectangle | polyline | regular_polygon | slot")
    params: dict[str, Any]
    construction: bool = False
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}


def _make_raw_geometry(kind: str, params: dict):
    import FreeCAD as App
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
        return [Part.Circle(App.Vector(float(c[0]), float(c[1]), 0.0),
                            App.Vector(0.0, 0.0, 1.0), r)]
    if kind == "arc":
        import math
        c = params["center"]; r = float(params["radius"])
        a0 = math.radians(float(params["start_angle"]))
        a1 = math.radians(float(params["end_angle"]))
        circ = Part.Circle(App.Vector(float(c[0]), float(c[1]), 0.0),
                           App.Vector(0.0, 0.0, 1.0), r)
        return [Part.ArcOfCircle(circ, a0, a1)]
    raise ValueError(f"Unknown raw geometry kind {kind!r}; use a profile kind for composites.")


def _geometry_add(doc, params: dict[str, Any]) -> dict:
    kind_name = "sketcher.geometry.add"
    sk = resolve_sketch(doc, params["sketch"])
    g_kind = params["kind"]
    g_params = params["params"]
    construction = params["construction"]
    profile_kinds = {"rectangle", "circle", "regular_polygon", "slot", "polyline"}

    def work():
        if g_kind.lower() in profile_kinds and not construction:
            prof = dict(g_params); prof["kind"] = g_kind.lower()
            info = profiles.build(sk, prof)
            doc.recompute()
            return info
        geoms = _make_raw_geometry(g_kind, g_params)
        geo_ids = [sk.addGeometry(g, construction) for g in geoms]
        doc.recompute()
        return {"geo_ids": geo_ids, "constraint_ids": []}

    try:
        info = with_transaction(doc, f"add_geometry {g_kind}", work)
    except ValueError as exc:
        return err_envelope(
            kind_name, error_kind="invalid_argument",
            message=str(exc), doc=doc, extras={"sketch": sk.Name},
        )
    return ok_envelope(
        kind_name, doc=doc, modified=[sk.Name],
        extras={
            "sketch": sk.Name,
            "geo_ids": info.get("geo_ids", []),
            "constraint_ids": info.get("constraint_ids", []),
            "named_constraints": info.get("named_constraints", {}),
            "health": sketch_health(sk),
        },
    )


registry.register(
    verb="modify",
    kind="sketcher.geometry.add",
    description=(
        "Add geometry to a sketch. kind is one of line/circle/arc (raw) or "
        "rectangle/circle/regular_polygon/slot/polyline (composite profile; "
        "auto-constrains to DoF=0 unless construction=true). params carries "
        "kind-specific values (mm for lengths, degrees for angles)."
    ),
    params_schema={"sketch": "str", "kind": "str", "params": "dict",
                    "construction": "bool?", "doc": "str?"},
    execute=_geometry_add,
    native=True,
    model=GeometryAddParams,
    example={"sketch": "Sketch", "kind": "line",
             "params": {"start": [0, 0], "end": [10, 0]}},
)


# ---------------------------------------------------------------------------
# modify:sketcher.constraint.add  (raw refs OR ergonomic anchors)
# ---------------------------------------------------------------------------

class Anchor(BaseModel):
    geo_id: int
    pos: Literal["edge", "start", "end", "center"] = "edge"
    model_config = {"extra": "forbid"}


class ConstraintAddParams(BaseModel):
    sketch: str
    kind: str = Field(
        ...,
        description="Coincident | PointOnObject | Horizontal | Vertical | Parallel | "
                    "Perpendicular | Tangent | Equal | Symmetric | Distance | "
                    "DistanceX | DistanceY | Radius | Diameter | Angle",
    )
    refs: Optional[List[int]] = Field(
        None, description="Raw positional args for Sketcher.Constraint (advanced).",
    )
    anchors: Optional[List[Anchor]] = Field(
        None,
        description="Ergonomic form: list of {geo_id, pos in edge|start|end|center}. "
                    "Translated to refs internally. Used instead of `refs`.",
    )
    value: Optional[float] = None
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _one_of(self):
        if self.refs is None and self.anchors is None:
            raise ValueError("constraint.add requires either 'refs' or 'anchors'.")
        return self


def _anchors_to_refs(kind: str, anchors: List[Anchor]) -> List[int]:
    """Flatten anchors to the positional int list Sketcher.Constraint expects.

    For point-referencing constraints (Coincident, Distance, DistanceX/Y,
    PointOnObject, Symmetric, Tangent at endpoint) we emit (geo_id, pos)
    pairs. For pure-geometry constraints (Horizontal, Vertical, Parallel,
    Perpendicular, Equal, Parallel, Radius, Diameter) we emit only geo_ids.
    """
    pure_geom = {"horizontal", "vertical", "parallel", "perpendicular",
                 "equal", "radius", "diameter"}
    out: List[int] = []
    if kind.lower() in pure_geom:
        for a in anchors:
            out.append(a.geo_id)
    else:
        for a in anchors:
            out.append(a.geo_id)
            out.append(_POS_MAP[a.pos])
    return out


def _constraint_add(doc, params: dict[str, Any]) -> dict:
    kind_name = "sketcher.constraint.add"
    sk = resolve_sketch(doc, params["sketch"])
    c_kind = params["kind"]
    value = params.get("value")

    refs: List[int]
    if params.get("anchors"):
        refs = _anchors_to_refs(c_kind, [Anchor(**a) if isinstance(a, dict) else a
                                           for a in params["anchors"]])
    else:
        refs = [int(x) for x in params["refs"]]

    def work():
        import Sketcher
        parts: list[Any] = [c_kind, *refs]
        if value is not None:
            parts.append(float(value))
        cid = sk.addConstraint(Sketcher.Constraint(*parts))
        doc.recompute()
        return cid

    try:
        cid = with_transaction(doc, f"constraint {c_kind}", work)
    except Exception as exc:
        return err_envelope(
            kind_name, error_kind="invalid_argument",
            message=str(exc),
            hint="Check refs/anchors shape; 'kind' and positional layout must match Sketcher.Constraint.",
            doc=doc,
            extras={"sketch": sk.Name, "health": sketch_health(sk)},
        )
    return ok_envelope(
        kind_name, doc=doc, modified=[sk.Name],
        extras={
            "sketch": sk.Name,
            "constraint_id": cid,
            "refs_used": refs,
            "health": sketch_health(sk),
        },
    )


registry.register(
    verb="modify",
    kind="sketcher.constraint.add",
    description=(
        "Add a sketch constraint. Pass either `refs` (raw flat int list, "
        "advanced) or `anchors` (list of {geo_id, pos: edge|start|end|center}). "
        "Use `value` for dimensional kinds (Distance, Radius, Angle)."
    ),
    params_schema={"sketch": "str", "kind": "str", "refs": "list[int]?",
                    "anchors": "list[dict]?", "value": "float?", "doc": "str?"},
    execute=_constraint_add,
    native=True,
    model=ConstraintAddParams,
    example={"sketch": "Sketch", "kind": "Coincident",
             "anchors": [{"geo_id": 0, "pos": "end"}, {"geo_id": 1, "pos": "start"}]},
)


# ---------------------------------------------------------------------------
# verify:sketcher.close
# ---------------------------------------------------------------------------

class CloseParams(BaseModel):
    sketch: str
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}


def _close_sketch(doc, params: dict[str, Any]) -> dict:
    kind_name = "sketcher.close"
    sk = resolve_sketch(doc, params["sketch"])

    def work():
        solve_err = None
        try:
            sk.solve()
        except Exception as exc:
            solve_err = str(exc)
        doc.recompute()
        return solve_err

    solve_err = with_transaction(doc, f"close_sketch {sk.Name}", work)
    health = sketch_health(sk)
    extras = {"sketch": sk.Name, "health": health}
    if solve_err:
        return err_envelope(
            kind_name, error_kind="sketch_malformed",
            hint=f"sketch.solve() raised: {solve_err}",
            doc=doc, extras=extras,
        )
    return ok_envelope(kind_name, doc=doc, modified=[sk.Name], extras=extras)


registry.register(
    verb="verify",
    kind="sketcher.close",
    description=(
        "Solve a sketch and report health (dof, conflicting, redundant, "
        "malformed). Returns an error envelope when solve raises."
    ),
    params_schema={"sketch": "str", "doc": "str?"},
    execute=_close_sketch,
    native=True,
    model=CloseParams,
    example={"sketch": "Sketch"},
)
