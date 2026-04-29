# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI / FreeCAD document lifecycle tools.

These let the agent manage FreeCAD documents through the live GUI — list,
create, open, switch, reload — analogous to ``cd`` / ``mkdir`` / ``ls``
in a terminal session. Geometry editing still happens via
``Bash → FreeCADCmd`` (the CLI contract); these tools just cover the doc
lifecycle so the agent isn't stuck if no document is open.

All mutations are marshaled to the Qt main thread via
:mod:`agent.gui_thread`. This module imports ``FreeCAD`` at module load,
so do not import it from the standalone CLI runtime.
"""

from __future__ import annotations

import os
import tempfile
import traceback
from typing import Any

import FreeCAD as App
from claude_agent_sdk import tool

from .. import gui_thread
from ..worker import client as worker_client
from ._common import READ_ONLY, err, ok


def _doc_summary(doc) -> dict:
    return {
        "name": getattr(doc, "Name", "") or "",
        "label": getattr(doc, "Label", "") or "",
        "path": getattr(doc, "FileName", "") or "",
        "object_count": len(getattr(doc, "Objects", []) or []),
    }


@tool(
    "gui_documents_list",
    "List every FreeCAD document currently open in the GUI, plus which one is active. The active doc is the agent's current workspace; use ``gui_set_active_document`` to switch.",
    {"type": "object", "properties": {}, "required": []},
    annotations=READ_ONLY,
)
async def gui_documents_list(args):
    try:
        def _read():
            docs = list(App.listDocuments().values())
            active = App.ActiveDocument
            return {
                "documents": [_doc_summary(d) for d in docs],
                "active": _doc_summary(active) if active is not None else None,
            }
        return ok(gui_thread.run_sync(_read))
    except Exception as exc:
        return err(str(exc), traceback=traceback.format_exc(limit=4))


@tool(
    "gui_active_document",
    "Return the active FreeCAD document (name, label, on-disk path, object count), or null if no document is open.",
    {"type": "object", "properties": {}, "required": []},
    annotations=READ_ONLY,
)
async def gui_active_document(args):
    try:
        def _read():
            doc = App.ActiveDocument
            return {"document": _doc_summary(doc) if doc is not None else None}
        return ok(gui_thread.run_sync(_read))
    except Exception as exc:
        return err(str(exc), traceback=traceback.format_exc(limit=4))


def _resolve_path(path: str | None, *, default_stem: str) -> str:
    """Return an absolute .FCStd path; auto-pick a temp path if none given."""
    if path and isinstance(path, str) and path.strip():
        p = os.path.expanduser(path.strip())
        if not p.lower().endswith(".fcstd"):
            p += ".FCStd"
        return os.path.abspath(p)
    fd, tmp = tempfile.mkstemp(prefix=f"{default_stem}-", suffix=".FCStd")
    os.close(fd)
    os.unlink(tmp)
    return tmp


@tool(
    "gui_new_document",
    "Create a new empty FreeCAD document, save it to ``path`` (or to a unique temp path if omitted), and make it the active doc. Returns the on-disk path so subsequent memory_/plan_ tools can address it.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "label": {"type": "string"},
        },
        "required": [],
    },
)
async def gui_new_document(args):
    try:
        path = _resolve_path((args or {}).get("path"), default_stem="cadagent-doc")
        label = (args or {}).get("label") or ""

        def _create():
            doc = App.newDocument(label or "Unnamed")
            if label:
                doc.Label = label
            doc.saveAs(path)
            App.setActiveDocument(doc.Name)
            return _doc_summary(doc)

        return ok({"document": gui_thread.run_sync(_create, timeout=60.0)})
    except Exception as exc:
        return err(str(exc), traceback=traceback.format_exc(limit=4))


@tool(
    "gui_open_document",
    "Open an existing .FCStd in the GUI (or activate it if already open) and make it the active doc.",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)
async def gui_open_document(args):
    try:
        raw = (args or {}).get("path") or ""
        if not raw.strip():
            raise ValueError("'path' is required")
        path = os.path.abspath(os.path.expanduser(raw.strip()))
        if not os.path.exists(path):
            raise FileNotFoundError(path)

        def _open():
            for d in App.listDocuments().values():
                if (getattr(d, "FileName", "") or "") == path:
                    App.setActiveDocument(d.Name)
                    return _doc_summary(d)
            doc = App.openDocument(path)
            App.setActiveDocument(doc.Name)
            return _doc_summary(doc)

        return ok({"document": gui_thread.run_sync(_open, timeout=60.0)})
    except Exception as exc:
        return err(str(exc), traceback=traceback.format_exc(limit=4))


@tool(
    "gui_set_active_document",
    "Switch the active document to one already open in the GUI, by document name (the internal ``Name`` attribute). Use ``gui_documents_list`` first to see candidates.",
    {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)
async def gui_set_active_document(args):
    try:
        name = (args or {}).get("name") or ""
        if not name:
            raise ValueError("'name' is required")

        def _activate():
            if name not in App.listDocuments():
                raise ValueError(
                    f"no open document named {name!r}; "
                    f"open it via gui_open_document first"
                )
            App.setActiveDocument(name)
            return _doc_summary(App.ActiveDocument)

        return ok({"document": gui_thread.run_sync(_activate, timeout=30.0)})
    except Exception as exc:
        return err(str(exc), traceback=traceback.format_exc(limit=4))


@tool(
    "gui_reload_active_document",
    "Re-open the active document from disk. The dock auto-runs this at end of turn; only call it manually if a Bash → FreeCADCmd subprocess wrote changes mid-turn and you need to re-read them through GUI tools.",
    {"type": "object", "properties": {}, "required": []},
)
async def gui_reload_active_document(args):
    try:
        def _reload():
            doc = App.ActiveDocument
            if doc is None:
                return {"document": None}
            path = getattr(doc, "FileName", "") or ""
            if not path or not os.path.exists(path):
                return {"document": _doc_summary(doc)}
            name = doc.Name
            App.closeDocument(name)
            new_doc = App.openDocument(path)
            App.setActiveDocument(new_doc.Name)
            try:
                new_doc.recompute()
            except Exception:
                pass
            return {"document": _doc_summary(new_doc)}

        return ok(gui_thread.run_sync(_reload, timeout=60.0))
    except Exception as exc:
        return err(str(exc), traceback=traceback.format_exc(limit=4))


@tool(
    "gui_inspect_live",
    (
        "Fast live introspection of a .FCStd via a long-lived worker "
        "subprocess. The worker boots FreeCAD once per session, so "
        "repeated inspects cost a JSON round-trip instead of a fresh "
        "FreeCADCmd fork. Pass ``path`` the first time; subsequent "
        "calls against the same doc can omit it. Pass ``obj_name`` to "
        "inspect one object; omit it for the full tree. ``props`` is an "
        "optional list of property names to read (e.g. [\"Length\", "
        "\"Placement\"]) — omit for cheap name/label/type only."
    ),
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "obj_name": {"type": "string"},
            "props": {"type": "array", "items": {"type": "string"}},
        },
        "required": [],
    },
    annotations=READ_ONLY,
)
async def gui_inspect_live(args):
    try:
        a = args or {}
        path = (a.get("path") or "").strip()
        obj_name = a.get("obj_name") or None
        props = a.get("props") or None

        worker = await worker_client.get_shared()
        if path:
            expanded = os.path.abspath(os.path.expanduser(path))
            if not os.path.exists(expanded):
                raise FileNotFoundError(expanded)
            await worker.call("doc.open", path=expanded)

        params: dict[str, Any] = {}
        if obj_name:
            params["obj_name"] = obj_name
        if props:
            params["props"] = list(props)
        result = await worker.call("doc.inspect", **params)
        return ok(result)
    except worker_client.WorkerError as exc:
        return err(f"worker: {exc}")
    except Exception as exc:
        return err(str(exc), traceback=traceback.format_exc(limit=4))


TOOL_FUNCS = [
    gui_documents_list,
    gui_active_document,
    gui_new_document,
    gui_open_document,
    gui_set_active_document,
    gui_reload_active_document,
    gui_inspect_live,
]

TOOL_NAMES = [f.name if hasattr(f, "name") else f.__name__ for f in TOOL_FUNCS]


def allowed_tool_names(server_name: str = "cad") -> list[str]:
    return [f"mcp__{server_name}__{n}" for n in TOOL_NAMES]


__all__ = [
    "TOOL_FUNCS",
    "TOOL_NAMES",
    "allowed_tool_names",
    "gui_active_document",
    "gui_documents_list",
    "gui_inspect_live",
    "gui_new_document",
    "gui_open_document",
    "gui_reload_active_document",
    "gui_set_active_document",
]
