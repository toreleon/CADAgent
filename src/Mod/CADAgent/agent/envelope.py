# SPDX-License-Identifier: LGPL-2.1-or-later
"""Uniform result envelope for v2 native handlers.

Every native v2 handler returns an envelope of the same shape so the agent
doesn't have to learn per-tool result schemas:

    {
      "ok": true,
      "kind": "partdesign.pad",
      "created": [{"name": "Pad001", "type": "PartDesign::Pad",
                    "bbox": {...}, "volume": 1.23, "valid": true}],
      "modified": [...],
      "deleted":  [...],
      "context":  {"active_doc": "Bracket", "active_body": "Body",
                    "active_sketch": null},
      "warnings": [...],
      "error": null,
      # plus any kind-specific fields (e.g. "health" for sketch handlers)
    }

On failure:

    {
      "ok": false,
      "kind": "partdesign.pad",
      "created": [], "modified": [], "deleted": [],
      "context": {...},
      "warnings": [...],
      "error": {"kind": "sketch_malformed", "message": "...",
                 "hint": "...", "health": {...}, "recover_tools": [...]}
    }

The legacy ``ok()`` / ``errors.fail()`` helpers stay in place for v1
passthrough handlers during the migration; this module is additive.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

import FreeCAD as App

from . import errors
from .tools._shared import _LAST_RESULT


def _safe_shape_summary(obj) -> dict[str, Any]:
    """Return bbox / volume / valid for an object that has a .Shape, best-effort."""
    out: dict[str, Any] = {"name": obj.Name, "type": obj.TypeId}
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return out
    try:
        bb = shape.BoundBox
        out["bbox"] = {
            "xmin": bb.XMin, "ymin": bb.YMin, "zmin": bb.ZMin,
            "xmax": bb.XMax, "ymax": bb.YMax, "zmax": bb.ZMax,
            "length": bb.XLength, "width": bb.YLength, "height": bb.ZLength,
        }
    except Exception as exc:  # bbox can raise on nullshape
        out["bbox_error"] = str(exc)
    try:
        out["volume"] = float(shape.Volume)
    except Exception as exc:
        out["volume_error"] = str(exc)
    try:
        out["valid"] = bool(shape.isValid())
    except Exception as exc:
        # isValid() raising is a real failure, not an "unknown".
        out["valid"] = False
        out["valid_error"] = str(exc)
    return out


def _active_context_snapshot(doc) -> dict[str, Any]:
    """Cheap active-state snapshot the agent can read without another tool call."""
    ctx: dict[str, Any] = {
        "active_doc": doc.Name if doc is not None else None,
        "active_body": None,
        "active_sketch": None,
    }
    try:
        import FreeCADGui as Gui
        try:
            import PartDesignGui  # type: ignore
            body = PartDesignGui.getActiveBody(False)
            if body is not None and (doc is None or body.Document is doc):
                ctx["active_body"] = body.Name
        except Exception:
            pass
        # No direct "active sketch" API in the core; skip for now.
    except ImportError:
        pass
    return ctx


def _describe(doc, names: Iterable[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if doc is None:
        return items
    for name in names or ():
        obj = doc.getObject(name)
        if obj is None:
            items.append({"name": name, "missing": True})
            continue
        items.append(_safe_shape_summary(obj))
    return items


def ok_envelope(
    kind: str,
    *,
    doc=None,
    created: Iterable[str] = (),
    modified: Iterable[str] = (),
    deleted: Iterable[str] = (),
    warnings: Iterable[str] = (),
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a success envelope. Returns the MCP ``{content: [...]}`` dict."""
    resolved_doc = doc if doc is not None else App.ActiveDocument
    payload: dict[str, Any] = {
        "ok": True,
        "kind": kind,
        "created": _describe(resolved_doc, created),
        "modified": _describe(resolved_doc, modified),
        "deleted": list(deleted),
        "context": _active_context_snapshot(resolved_doc),
        "warnings": list(warnings),
        "error": None,
    }
    if extras:
        for k, v in extras.items():
            if k not in payload:
                payload[k] = v
    _LAST_RESULT["summary"] = {
        "tool": _LAST_RESULT.get("tool"),
        "ok": True,
        "kind": kind,
        "created": [c.get("name") for c in payload["created"] if isinstance(c, dict)],
        "warnings": payload["warnings"],
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def err_envelope(
    kind: str,
    *,
    error_kind: str,
    message: str | None = None,
    hint: str | None = None,
    doc=None,
    warnings: Iterable[str] = (),
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a failure envelope using the errors taxonomy for copy/hints."""
    recipe = errors._RECIPES.get(error_kind, errors._RECIPES["internal_error"])
    error_obj: dict[str, Any] = {
        "kind": error_kind,
        "message": message or recipe["message"],
        "hint": hint or recipe["hint"],
        "recover_tools": list(recipe["recover_tools"]),
    }
    if extras:
        # Kind-specific diagnostic fields (e.g. "health": {...}, "dof": 3) ride
        # inside the error object so the agent can see them without searching.
        for k, v in extras.items():
            if k not in error_obj:
                error_obj[k] = v
    resolved_doc = doc if doc is not None else App.ActiveDocument
    payload: dict[str, Any] = {
        "ok": False,
        "kind": kind,
        "created": [],
        "modified": [],
        "deleted": [],
        "context": _active_context_snapshot(resolved_doc),
        "warnings": list(warnings),
        "error": error_obj,
    }
    _LAST_RESULT["summary"] = {
        "tool": _LAST_RESULT.get("tool"),
        "ok": False,
        "kind": kind,
        "error": error_obj,
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        "is_error": True,
    }


__all__ = ["ok_envelope", "err_envelope"]
