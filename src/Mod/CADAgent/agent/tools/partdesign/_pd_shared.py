# SPDX-License-Identifier: LGPL-2.1-or-later
"""Helpers shared across PartDesign tool submodules.

Keeps body/sketch/support/edge-resolution logic in one place so `body.py`,
`sketch.py`, `pad_pocket.py`, and `dress_ups.py` don't each reinvent it.
"""

from __future__ import annotations

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False


PLANE_MAP = {
    "XY": "XY_Plane",
    "XZ": "XZ_Plane",
    "YZ": "YZ_Plane",
}


def resolve_body(doc, name):
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


def resolve_sketch(doc, name):
    obj = doc.getObject(name)
    if obj is None or "Sketcher::SketchObject" not in obj.TypeId:
        raise ValueError(f"{name!r} is not a Sketch.")
    return obj


def resolve_support(doc, body, plane_spec: str):
    """Return the (feature, subnames) tuple to use as AttachmentSupport."""
    if plane_spec in PLANE_MAP:
        origin = body.Origin
        plane = origin.getObject(PLANE_MAP[plane_spec])
        if plane is None:
            for p in origin.OriginFeatures:
                if p.Name.endswith(PLANE_MAP[plane_spec]):
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


def add_feature(body, type_id: str, name: str):
    return body.newObject(type_id, name)


def edge_refs_to_base(doc, edge_refs):
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


def body_of(obj):
    """Return the PartDesign::Body parenting `obj`, or None."""
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None
