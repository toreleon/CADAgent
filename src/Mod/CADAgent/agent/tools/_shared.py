# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared helpers used across the CAD Agent tool submodules.

Keeps the `_ok` / `_err` / document-resolving / transaction / summary helpers
in one place so every tool module returns the same shape MCP payloads without
duplicating ~60 lines each. Also owns the cross-tool `_LAST_RESULT` state that
the context snapshot reads back.
"""

from __future__ import annotations

import json
from typing import Any

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from .. import errors
from ..gui_thread import run_sync


_LAST_RESULT: dict[str, Any] = {"tool": None, "summary": None}


def mark_tool(name: str) -> None:
    """Record the last tool the agent invoked (for the context snapshot)."""
    _LAST_RESULT["tool"] = name


def get_last_result_summary() -> dict | None:
    return _LAST_RESULT.get("summary")


def ok(payload: dict) -> dict:
    """Wrap a dict payload as an MCP success result.

    Also writes a compact summary into `_LAST_RESULT` so the context snapshot
    can surface the previous tool's outcome on the next turn.
    """
    out = {"ok": True}
    out.update(payload)
    text = json.dumps(out, default=str)
    _LAST_RESULT["summary"] = {
        "tool": _LAST_RESULT.get("tool"),
        "ok": True,
        "created": out.get("created"),
        "warnings": out.get("warnings"),
    }
    return {"content": [{"type": "text", "text": text}]}


def err(message: str, **extras) -> dict:
    """Legacy error path: prefer errors.fail(kind, ...) for new callers."""
    payload = errors.fail("internal_error", message=message, **extras)
    try:
        body = json.loads(payload["content"][0]["text"])
        _LAST_RESULT["summary"] = {
            "tool": _LAST_RESULT.get("tool"),
            "ok": False,
            "error": body.get("error"),
        }
    except Exception:
        pass
    return payload


def resolve_doc(doc_name: str | None):
    if doc_name:
        doc = App.getDocument(doc_name) if doc_name in App.listDocuments() else None
        if doc is None:
            raise ValueError(f"No document named {doc_name!r}. Use list_documents.")
        return doc
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError(
            "No active FreeCAD document. Call create_document first or open one."
        )
    return doc


def with_transaction(doc, label: str, fn):
    """Marshal `fn` onto the Qt GUI thread, wrapped in a single undo transaction.

    FreeCAD's document API is not thread-safe — mutating calls from the
    asyncio worker thread trigger Qt QObject thread-affinity aborts. `run_sync`
    dispatches the work to the main thread and blocks for the result.
    """
    def work():
        doc.openTransaction(f"CADAgent: {label}")
        try:
            result = fn()
            doc.commitTransaction()
            return result
        except Exception:
            doc.abortTransaction()
            raise

    return run_sync(work)


def on_gui(fn):
    """Execute `fn` on the Qt GUI thread; re-raise exceptions on the caller."""
    return run_sync(fn)


def summarise_result(doc, created: list[str], warnings: list[str] | None = None) -> dict:
    """Build the closed-loop payload every mutating tool returns.

    `created` is a list of object names produced by the operation. The helper
    computes bbox / volume / solid validity for the last-created shape-bearing
    object so the agent can immediately tell whether the operation succeeded.
    """
    bbox = None
    volume = None
    is_valid = None
    primary = None
    if doc is not None:
        for name in reversed(created or []):
            obj = doc.getObject(name)
            if obj is None:
                continue
            shape = getattr(obj, "Shape", None)
            if shape is None:
                continue
            primary = obj.Name
            try:
                bb = shape.BoundBox
                bbox = {
                    "xmin": bb.XMin, "ymin": bb.YMin, "zmin": bb.ZMin,
                    "xmax": bb.XMax, "ymax": bb.YMax, "zmax": bb.ZMax,
                    "length": bb.XLength, "width": bb.YLength, "height": bb.ZLength,
                }
                volume = float(shape.Volume)
            except Exception:
                pass
            try:
                is_valid = bool(shape.isValid())
            except Exception:
                is_valid = None
            break
    return {
        "created": list(created or []),
        "primary": primary,
        "bbox": bbox,
        "volume": volume,
        "is_valid_solid": is_valid,
        "warnings": list(warnings or []),
    }


def sketch_health(sk) -> dict:
    return {
        "dof": int(getattr(sk, "DoF", -1)),
        "malformed": list(getattr(sk, "MalformedConstraints", []) or []),
        "conflicting": list(getattr(sk, "ConflictingConstraints", []) or []),
        "redundant": list(getattr(sk, "RedundantConstraints", []) or []),
    }


def summarise_object(obj) -> dict:
    info: dict[str, Any] = {
        "name": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
    }
    try:
        if hasattr(obj, "Shape") and obj.Shape is not None:
            bb = obj.Shape.BoundBox
            info["bbox"] = {
                "xmin": bb.XMin, "ymin": bb.YMin, "zmin": bb.ZMin,
                "xmax": bb.XMax, "ymax": bb.YMax, "zmax": bb.ZMax,
            }
            info["volume"] = obj.Shape.Volume
    except Exception:
        pass
    try:
        if _HAS_GUI and obj.ViewObject is not None:
            info["visible"] = bool(obj.ViewObject.Visibility)
    except Exception:
        pass
    return info
