# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native PartDesign providers — body, datum.set, fillet, chamfer.

PR 2 of the tool-layer generalize pass. Each handler validates with
Pydantic, returns the uniform envelope, and fixes a specific footgun the
v1 tools carried forward:

  - ``partdesign.body`` returns the real ``body.Name`` (FreeCAD may append
    001/002) and also the active-body snapshot via the envelope context.
  - ``datum.set`` replaces the ``property_`` Python-reserved-word workaround
    with a normal ``property`` field.
  - ``partdesign.fillet`` validates that every entry in ``edges`` has the
    ``Feature.EdgeN`` shape via a Pydantic validator — bad refs now fail
    with ``invalid_argument`` instead of a generic ValueError.
  - ``partdesign.chamfer`` drops the silent ``if "Size" in PropertiesList``
    guard; if the FreeCAD build exposes a different property name we fail
    loudly with ``feature_property_missing`` so the caller sees it.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Union

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from pydantic import BaseModel, Field, field_validator

from .. import registry
from ..envelope import err_envelope, ok_envelope
from ..tools._shared import with_transaction
from ..tools.partdesign._pd_shared import add_feature, body_of, edge_refs_to_base


_EDGE_REF_RE = re.compile(r"^[A-Za-z_][\w]*\.Edge\d+$")


# ---------------------------------------------------------------------------
# partdesign.body — create
# ---------------------------------------------------------------------------

class BodyParams(BaseModel):
    label: str = Field("Body", description="Label and preferred name; FreeCAD may suffix it.")
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}


def _create_body(doc, params: dict[str, Any]) -> dict:
    kind = "partdesign.body"
    label = params["label"]

    def work():
        body = doc.addObject("PartDesign::Body", label)
        doc.recompute()
        if _HAS_GUI:
            try:
                gui_doc = Gui.getDocument(doc.Name) if hasattr(Gui, "getDocument") else None
                active_view = gui_doc.ActiveView if gui_doc is not None else None
                if active_view is not None and hasattr(active_view, "setActiveObject"):
                    active_view.setActiveObject("pdbody", body)
            except Exception:
                pass
        return body

    body = with_transaction(doc, f"create_body {label}", work)
    return ok_envelope(
        kind, doc=doc, created=[body.Name],
        extras={"label": body.Label, "active_body": body.Name},
    )


registry.register(
    verb="create",
    kind="partdesign.body",
    description=(
        "Create a new PartDesign::Body and (GUI-only) make it active. "
        "created[0].name is the real FreeCAD name — FreeCAD may suffix 001/002 "
        "on label collision."
    ),
    params_schema={"label": "str?", "doc": "str?"},
    execute=_create_body,
    native=True,
    model=BodyParams,
    example={"label": "Bracket"},
)


# ---------------------------------------------------------------------------
# datum.set — modify
# ---------------------------------------------------------------------------

class DatumSetParams(BaseModel):
    feature: str = Field(..., description="Target feature or datum name.")
    property: str = Field(..., description="Property name, e.g. 'Length'.")
    # Free-form value: a number (literal) or a string (literal or expression).
    value: Union[float, int, str, bool] = Field(
        ..., description="Scalar literal, or expression string (e.g. 'Parameters.Thickness')."
    )
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}


def _datum_set(doc, params: dict[str, Any]) -> dict:
    kind = "datum.set"
    feat = doc.getObject(params["feature"])
    if feat is None:
        return err_envelope(
            kind, error_kind="invalid_argument",
            message=f"No object named {params['feature']!r}.",
            doc=doc,
        )
    prop = params["property"]
    if prop not in feat.PropertiesList:
        return err_envelope(
            kind, error_kind="invalid_argument",
            message=f"{feat.Name} has no property {prop!r}.",
            hint="Call cad_inspect(kind='object.get', params={name: feat_name}) to list properties.",
            doc=doc,
        )
    val = params["value"]

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
        return is_expr

    is_expr = with_transaction(doc, f"datum.set {feat.Name}.{prop}", work)
    return ok_envelope(
        kind, doc=doc, modified=[feat.Name],
        extras={"property": prop, "set": str(val), "expression": is_expr},
    )


registry.register(
    verb="modify",
    kind="datum.set",
    description=(
        "Set a property or bind an expression. If 'value' is a string with "
        "a '.' or arithmetic operator it's bound as an expression (e.g. "
        "'Parameters.Thickness'); otherwise it's set as a literal."
    ),
    params_schema={"feature": "str", "property": "str", "value": "any", "doc": "str?"},
    execute=_datum_set,
    native=True,
    model=DatumSetParams,
    example={"feature": "Pad", "property": "Length", "value": "Parameters.Thickness"},
)


# ---------------------------------------------------------------------------
# partdesign.fillet / partdesign.chamfer — create
# ---------------------------------------------------------------------------

class _EdgeRefs(BaseModel):
    edges: List[str] = Field(..., min_length=1)

    @field_validator("edges")
    @classmethod
    def _check_shape(cls, v: List[str]) -> List[str]:
        bad = [e for e in v if not isinstance(e, str) or not _EDGE_REF_RE.match(e)]
        if bad:
            raise ValueError(
                f"edges must be list of 'Feature.EdgeN' strings; got invalid: {bad}"
            )
        return v


class FilletParams(_EdgeRefs):
    radius: float = Field(..., gt=0, description="Fillet radius in mm.")
    name: str = Field("Fillet", description="Preferred feature name.")
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}


class ChamferParams(_EdgeRefs):
    size: float = Field(..., gt=0, description="Chamfer size in mm.")
    name: str = Field("Chamfer", description="Preferred feature name.")
    doc: Optional[str] = None
    model_config = {"extra": "forbid"}


def _dressup(doc, params: dict[str, Any], *, typeid: str, kind: str,
             size_prop: str, size_value: float) -> dict:
    try:
        feat, subs = edge_refs_to_base(doc, params["edges"])
    except ValueError as exc:
        return err_envelope(
            kind, error_kind="invalid_argument",
            message=str(exc),
            hint="All edges must live on the same feature. Use cad_inspect(kind='topology.preview', params={feature: ...}).",
            doc=doc,
        )
    body = body_of(feat)
    if body is None:
        return err_envelope(
            kind, error_kind="no_active_body",
            message=f"{feat.Name} is not inside a PartDesign::Body.",
            doc=doc,
        )

    def work():
        f = add_feature(body, typeid, params["name"])
        f.Base = (feat, subs)
        if size_prop not in f.PropertiesList:
            raise KeyError(size_prop)
        setattr(f, size_prop, float(size_value))
        doc.recompute()
        return f

    try:
        f = with_transaction(doc, f"{kind} {params['name']}", work)
    except KeyError as exc:
        return err_envelope(
            kind, error_kind="invalid_argument",
            message=f"{typeid} has no {exc.args[0]!r} property on this FreeCAD build.",
            hint="The build may use a different property name — open an issue; do not retry.",
            doc=doc,
        )
    return ok_envelope(
        kind, doc=doc, created=[f.Name],
        extras={"body": body.Name, "edges": list(params["edges"])},
    )


def _fillet(doc, params: dict[str, Any]) -> dict:
    return _dressup(
        doc, params, typeid="PartDesign::Fillet", kind="partdesign.fillet",
        size_prop="Radius", size_value=params["radius"],
    )


def _chamfer(doc, params: dict[str, Any]) -> dict:
    return _dressup(
        doc, params, typeid="PartDesign::Chamfer", kind="partdesign.chamfer",
        size_prop="Size", size_value=params["size"],
    )


registry.register(
    verb="create",
    kind="partdesign.fillet",
    description=(
        "Add a PartDesign::Fillet on one or more edges of the same feature. "
        "'edges' is a list of 'Feature.EdgeN' refs — use cad_inspect("
        "kind='topology.preview', params={feature: ...}) to discover edge ids."
    ),
    params_schema={"edges": "list[str]", "radius": "float", "name": "str?", "doc": "str?"},
    execute=_fillet,
    native=True,
    model=FilletParams,
    example={"edges": ["Pad.Edge1", "Pad.Edge2"], "radius": 2.0},
)


registry.register(
    verb="create",
    kind="partdesign.chamfer",
    description=(
        "Add a PartDesign::Chamfer. 'edges' is a list of 'Feature.EdgeN' refs; "
        "'size' is the chamfer length in mm."
    ),
    params_schema={"edges": "list[str]", "size": "float", "name": "str?", "doc": "str?"},
    execute=_chamfer,
    native=True,
    model=ChamferParams,
    example={"edges": ["Pad.Edge1"], "size": 1.5},
)
