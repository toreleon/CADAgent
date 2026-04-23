# SPDX-License-Identifier: LGPL-2.1-or-later
"""Document-level custom tools: open/create/recompute/export."""

from __future__ import annotations

import traceback

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from claude_agent_sdk import tool
from mcp.types import ToolAnnotations

_READ_ONLY = ToolAnnotations(readOnlyHint=True)

from ..gui_thread import run_sync
from ._shared import ok, err, on_gui, resolve_doc, summarise_object


@tool("list_documents", "List the names of all open FreeCAD documents.", {}, annotations=_READ_ONLY)
async def list_documents(args):
    def work():
        names = list(App.listDocuments().keys())
        active = App.ActiveDocument.Name if App.ActiveDocument else None
        return {"documents": names, "active": active}
    try:
        return ok(on_gui(work))
    except Exception as exc:
        return err(str(exc))


@tool(
    "get_active_document",
    "Return the active document name and a short summary of its objects.",
    {},
    annotations=_READ_ONLY,
)
async def get_active_document(args):
    def work():
        doc = App.ActiveDocument
        if doc is None:
            return {"active": None, "objects": []}
        return {
            "active": doc.Name,
            "label": doc.Label,
            "objects": [summarise_object(o) for o in doc.Objects],
        }
    try:
        return ok(on_gui(work))
    except Exception as exc:
        return err(str(exc))


@tool(
    "create_document",
    "Create a new FreeCAD document and make it active. Returns the document name.",
    {"name": str},
)
async def create_document(args):
    def work():
        doc = App.newDocument(args["name"])
        return {"name": doc.Name, "label": doc.Label}
    try:
        return ok(on_gui(work))
    except Exception as exc:
        return err(str(exc))


@tool(
    "recompute_and_fit",
    "Recompute the document and fit the 3D view to all objects.",
    {"doc": str},
    annotations=_READ_ONLY,
)
async def recompute_and_fit(args):
    def work():
        doc = resolve_doc(args.get("doc"))
        doc.recompute()
        if _HAS_GUI:
            try:
                view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
                if view is not None and hasattr(view, "fitAll"):
                    view.fitAll()
                else:
                    Gui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
        return {"recomputed": doc.Name}
    try:
        return ok(on_gui(work))
    except Exception as exc:
        return err(str(exc))


@tool(
    "export_step",
    "Export named objects to a STEP file at the given path.",
    {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Object names to export.",
            },
            "path": {"type": "string", "description": "Output STEP file path."},
            "doc": {
                "type": "string",
                "description": "Document name (optional; defaults to active).",
            },
        },
        "required": ["names", "path"],
    },
)
async def export_step(args):
    def work():
        doc = resolve_doc(args.get("doc"))
        objs = []
        for n in args["names"]:
            o = doc.getObject(n)
            if o is None:
                raise ValueError(f"No object named {n!r}.")
            objs.append(o)
        import Import  # FreeCAD's STEP/IGES importer/exporter
        Import.export(objs, args["path"])
        return {"exported": args["path"], "objects": args["names"]}
    try:
        return ok(on_gui(work))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "run_python",
    (
        "Execute arbitrary Python in FreeCAD's console (via Gui.doCommand). "
        "Use only when primitive tools can't express the request. "
        "The code runs on the GUI thread inside a transaction; App, "
        "FreeCAD, FreeCADGui and Part are already importable."
    ),
    {"code": str, "label": str},
)
async def run_python(args):
    code = args.get("code") or ""
    label = args.get("label") or "run_python"
    if not code.strip():
        return err("Empty code.")

    def work():
        doc = App.ActiveDocument
        tx_owner = doc
        if tx_owner is not None:
            tx_owner.openTransaction(f"CADAgent: {label}")
        try:
            if _HAS_GUI:
                for line in code.splitlines():
                    Gui.doCommand(line)
            else:
                exec(code, {"App": App, "FreeCAD": App})
            if tx_owner is not None:
                tx_owner.commitTransaction()
                tx_owner.recompute()
            return {"ran": True, "label": label}
        except Exception:
            if tx_owner is not None:
                tx_owner.abortTransaction()
            raise

    try:
        return ok(run_sync(work))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


TOOL_FUNCS = [
    list_documents,
    get_active_document,
    create_document,
    recompute_and_fit,
    export_step,
    run_python,
]

TOOL_NAMES = [
    "list_documents",
    "get_active_document",
    "create_document",
    "recompute_and_fit",
    "export_step",
    "run_python",
]


