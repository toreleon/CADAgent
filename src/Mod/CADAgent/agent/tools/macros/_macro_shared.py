# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared helpers for Tier A macro MCP tools.

Each macro runs in a single `openTransaction` / `commitTransaction`, builds
geometry through `profiles.build` so sketches emerge with DOF=0, optionally
binds parameters to a Parameters spreadsheet, and finally re-presents the
result to the user (isometric view, fitted, body active).
"""

from __future__ import annotations

import FreeCAD as App

try:
    import FreeCADGui as Gui  # noqa: F401
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from ... import memory as project_memory
from ..memory import sync_parameter_to_sheet
from ..partdesign._pd_shared import resolve_support


def ensure_body(doc, label: str):
    """Return a new body inside the caller's transaction."""
    return doc.addObject("PartDesign::Body", label)


def new_sketch_on_body(doc, body, plane_spec: str, name: str):
    sk = body.newObject("Sketcher::SketchObject", name)
    support = resolve_support(doc, body, plane_spec)
    if "AttachmentSupport" in sk.PropertiesList:
        sk.AttachmentSupport = support
    else:
        sk.Support = support
    sk.MapMode = "FlatFace"
    return sk


def new_pad(body, sketch, length: float, name: str):
    pad = body.newObject("PartDesign::Pad", name)
    pad.Profile = sketch
    pad.Length = float(length)
    pad.Type = "Length"
    if "SideType" in pad.PropertiesList:
        pad.SideType = "One side"
    return pad


def present_result(doc, body=None, feature=None, sketch=None):
    """Leave the user looking at the created solid instead of an in-edit sketch.

    In practice the common failure report was "it made two triangles" when the
    model was correct but the camera was still in TOP and the sketch face stayed
    foregrounded. This helper resets edit state, hides the consumed sketch, then
    switches to an isometric fitted view.
    """
    if not _HAS_GUI:
        return
    try:
        gui_doc = Gui.getDocument(doc.Name) if hasattr(Gui, "getDocument") else Gui.ActiveDocument
    except Exception:
        gui_doc = Gui.ActiveDocument if _HAS_GUI else None
    if gui_doc is None:
        return

    try:
        if hasattr(gui_doc, "getInEdit") and gui_doc.getInEdit() is not None:
            gui_doc.resetEdit()
    except Exception:
        pass

    if body is not None:
        try:
            active_view = getattr(gui_doc, "ActiveView", None)
            if active_view is not None and hasattr(active_view, "setActiveObject"):
                active_view.setActiveObject("pdbody", body)
        except Exception:
            pass

    for obj, visible in ((sketch, False), (feature, True), (body, True)):
        if obj is None:
            continue
        try:
            view_obj = getattr(obj, "ViewObject", None)
            if view_obj is not None and hasattr(view_obj, "Visibility"):
                view_obj.Visibility = visible
        except Exception:
            pass

    try:
        Gui.Selection.clearSelection()
        if feature is not None:
            Gui.Selection.addSelection(doc.Name, feature.Name)
        elif body is not None:
            Gui.Selection.addSelection(doc.Name, body.Name)
    except Exception:
        pass

    try:
        view = getattr(gui_doc, "ActiveView", None)
        if view is not None:
            if hasattr(view, "viewIsometric"):
                view.viewIsometric()
            elif hasattr(view, "viewAxometric"):
                view.viewAxometric()
            if hasattr(view, "fitAll"):
                view.fitAll()
        else:
            Gui.runCommand("Std_ViewIsometric")
            Gui.SendMsgToActiveView("ViewFit")
    except Exception:
        pass


def set_parametric(doc, sketch, pad, named_constraints: dict[str, int],
                   param_bindings: dict[str, str],
                   pad_binding: tuple[str, str] | None) -> list[str]:
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


def write_parameter(doc, name: str, value: float, unit: str = "mm") -> None:
    project_memory.set_parameter(doc, name, value, unit, "")
    try:
        sync_parameter_to_sheet(doc, name, value, unit)
    except Exception as exc:
        App.Console.PrintWarning(
            f"CADAgent: could not sync parameter {name} to spreadsheet: {exc}\n"
        )
