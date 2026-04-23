# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native PartDesign providers — pad and pocket.

First set of kinds migrated off ``v1_passthrough`` onto the native registry
path. Goals vs the v1 tools in ``agent/tools/partdesign/pad_pocket.py``:

  - Uniform envelope (``agent.envelope.ok_envelope`` / ``err_envelope``).
  - Pydantic-validated args: field ``type`` (not the Python-reserved-word
    workaround ``type_``), explicit ``Literal`` enum, positive ``length``.
  - No silent ``sk.solve()`` swallowing: a solver exception becomes a
    ``sketch_malformed`` error with the exception message as ``hint``.
  - Return the real ``feat.Name`` from FreeCAD after ``newObject`` — not the
    caller's requested name — so the agent can reference the object on the
    next turn even when FreeCAD appended a numeric suffix.
  - Pocket rejects missing ``length`` *and* missing ``through_all`` with a
    structured ``invalid_argument`` (Pydantic root validator) instead of a
    generic ``ValueError``.
  - Postflight: when ``is_valid_solid`` turns out False, envelope carries
    ``error.kind="invalid_solid"`` so the hooks layer can hint a ``verify``.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .. import registry
from ..envelope import err_envelope, ok_envelope
from ..tools._shared import sketch_health, with_transaction
from ..tools.partdesign._pd_shared import add_feature, body_of, resolve_sketch


PadType = Literal["Length", "TwoLengths", "ThroughAll", "UpToFirst", "UpToLast", "UpToFace"]


class PadParams(BaseModel):
    sketch: str = Field(..., description="Name of the sketch to pad.")
    length: float = Field(..., gt=0, description="Pad length in mm.")
    type: PadType = Field(
        "Length", description="Pad type; 'Length' is the common default."
    )
    midplane: bool = False
    reversed: bool = False
    name: str = Field("Pad", description="Desired feature name; FreeCAD may suffix it.")
    doc: Optional[str] = None

    model_config = {"extra": "forbid"}


class PocketParams(BaseModel):
    sketch: str = Field(..., description="Name of the sketch to pocket.")
    length: Optional[float] = Field(None, gt=0, description="Depth in mm (required unless through_all=true).")
    through_all: bool = False
    reversed: bool = False
    name: str = Field("Pocket", description="Desired feature name; FreeCAD may suffix it.")
    doc: Optional[str] = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _depth_or_through(self):
        if not self.through_all and self.length is None:
            raise ValueError("pocket needs either 'length' (mm, >0) or through_all=true")
        return self


def _sketch_precheck(kind: str, sk) -> dict | None:
    """Run solver + health on ``sk`` and, if anything is wrong, return an
    ``err_envelope`` dict. Returns ``None`` when the sketch is pad-ready.
    """
    try:
        sk.solve()
    except Exception as exc:
        return err_envelope(
            kind,
            error_kind="sketch_malformed",
            hint=f"sketch.solve() raised: {exc}",
            extras={"health": sketch_health(sk), "sketch": sk.Name},
        )
    health = sketch_health(sk)
    if health["malformed"]:
        return err_envelope(kind, error_kind="sketch_malformed",
                            extras={"health": health, "sketch": sk.Name})
    if health["conflicting"] or health["redundant"]:
        return err_envelope(kind, error_kind="sketch_overconstrained",
                            extras={"health": health, "sketch": sk.Name})
    if health["dof"] > 0:
        return err_envelope(
            kind, error_kind="sketch_underconstrained",
            hint=f"Sketch has {health['dof']} DOF; add dimensional constraints before padding.",
            extras={"health": health, "sketch": sk.Name},
        )
    return None


def _pad(doc, params: dict[str, Any]) -> dict:
    kind = "partdesign.pad"
    sk = resolve_sketch(doc, params["sketch"])
    body = body_of(sk)
    if body is None:
        return err_envelope(
            kind, error_kind="no_active_body",
            message=f"Sketch {sk.Name!r} is not inside a PartDesign::Body.",
            hint="Move the sketch into a Body or recreate it with create:partdesign.sketch(body=...).",
            doc=doc,
        )
    precheck = _sketch_precheck(kind, sk)
    if precheck is not None:
        return precheck

    def work():
        feat = add_feature(body, "PartDesign::Pad", params["name"])
        feat.Profile = sk
        feat.Length = float(params["length"])
        feat.Type = params["type"]
        midplane = bool(params["midplane"])
        if "SideType" in feat.PropertiesList:
            feat.SideType = "Symmetric" if midplane else "One side"
        elif "Midplane" in feat.PropertiesList:
            feat.Midplane = midplane
        if "Reversed" in feat.PropertiesList:
            feat.Reversed = bool(params["reversed"])
        doc.recompute()
        return feat

    feat = with_transaction(doc, f"pad {params['name']}", work)
    # Use the FreeCAD-assigned name — FreeCAD appends 001/002/… on collision
    # and the agent needs the real name to reference the feature later.
    envelope = ok_envelope(kind, doc=doc, created=[feat.Name], extras={"body": body.Name})
    # Re-open to append health / validity diagnostic so the hooks layer can
    # surface a hint when the pad ran but the solid is invalid.
    import json as _json
    body_payload = _json.loads(envelope["content"][0]["text"])
    created = body_payload["created"][0] if body_payload["created"] else {}
    if created.get("valid") is False:
        return err_envelope(
            kind, error_kind="invalid_solid",
            message="Pad ran but produced an invalid solid.",
            hint="Inspect the sketch profile; close it, then retry.",
            doc=doc,
            extras={"feature": feat.Name, "bbox": created.get("bbox"),
                    "volume": created.get("volume")},
        )
    return envelope


def _pocket(doc, params: dict[str, Any]) -> dict:
    kind = "partdesign.pocket"
    sk = resolve_sketch(doc, params["sketch"])
    body = body_of(sk)
    if body is None:
        return err_envelope(
            kind, error_kind="no_active_body",
            message=f"Sketch {sk.Name!r} is not inside a PartDesign::Body.",
            doc=doc,
        )
    precheck = _sketch_precheck(kind, sk)
    if precheck is not None:
        return precheck

    def work():
        feat = add_feature(body, "PartDesign::Pocket", params["name"])
        feat.Profile = sk
        if params["through_all"]:
            feat.Type = "ThroughAll"
        else:
            feat.Type = "Length"
            feat.Length = float(params["length"])
        if "Reversed" in feat.PropertiesList:
            feat.Reversed = bool(params["reversed"])
        doc.recompute()
        return feat

    feat = with_transaction(doc, f"pocket {params['name']}", work)
    return ok_envelope(kind, doc=doc, created=[feat.Name], extras={"body": body.Name})


registry.register(
    verb="create",
    kind="partdesign.pad",
    description=(
        "Extrude a sketch into a PartDesign::Pad. length in mm, type defaults "
        "to 'Length'. Returns the actual feature name (FreeCAD may append 001/002)."
    ),
    params_schema={
        "sketch": "str", "length": "float", "type": "str?",
        "midplane": "bool?", "reversed": "bool?", "name": "str?", "doc": "str?",
    },
    execute=_pad,
    native=True,
    model=PadParams,
    example={"sketch": "Sketch", "length": 20, "type": "Length"},
)


registry.register(
    verb="create",
    kind="partdesign.pocket",
    description=(
        "Subtract a sketch extrusion (PartDesign::Pocket). Specify length in "
        "mm OR through_all=true."
    ),
    params_schema={
        "sketch": "str", "length": "float?", "through_all": "bool?",
        "reversed": "bool?", "name": "str?", "doc": "str?",
    },
    execute=_pocket,
    native=True,
    model=PocketParams,
    example={"sketch": "Sketch001", "through_all": True},
)
