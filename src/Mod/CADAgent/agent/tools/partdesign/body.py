# SPDX-License-Identifier: LGPL-2.1-or-later
"""PartDesign::Body creation + feature datum editing."""

from __future__ import annotations

import traceback

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from claude_agent_sdk import tool

from ...gui_thread import run_sync
from .._shared import ok, err, resolve_doc, summarise_result, with_transaction


@tool(
    "create_body",
    "Create a new PartDesign::Body and make it active. Returns the body name.",
    {"label": str, "doc": str},
)
async def create_body(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        label = args.get("label") or "Body"

        def work():
            body = doc.addObject("PartDesign::Body", label)
            doc.recompute()
            # Setting the active body touches GuiDocument internals that crash
            # when the Gui document isn't fully wired (e.g. brand-new doc).
            # Guard defensively; the body is still usable without being active.
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
        summary = summarise_result(doc, [body.Name])
        summary["label"] = body.Label
        summary["active_body"] = body.Name
        return summary

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "set_datum",
    (
        "Edit a feature property in-place. If value_or_expr is a string and "
        "looks like an expression (contains '.', '+', '*' etc), bind it as an "
        "expression (e.g. 'Parameters.Thickness'). Otherwise set the value "
        "directly. Use to bind a Pad.Length to a named parameter."
    ),
    {
        "type": "object",
        "properties": {
            "feature": {"type": "string"},
            "property_": {"type": "string", "description": "Property name, e.g. 'Length'"},
            "value_or_expr": {},
            "doc": {"type": "string"},
        },
        "required": ["feature", "property_", "value_or_expr"],
    },
)
async def set_datum(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        feat = doc.getObject(args["feature"])
        if feat is None:
            raise ValueError(f"No object named {args['feature']!r}.")
        prop = args["property_"]
        val = args["value_or_expr"]
        if prop not in feat.PropertiesList:
            raise ValueError(f"{feat.Name} has no property {prop!r}.")

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
            return {"feature": feat.Name, "property": prop, "set": str(val), "expression": is_expr}

        return with_transaction(doc, f"set_datum {feat.Name}.{prop}", work)

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


TOOL_FUNCS = [create_body, set_datum]
TOOL_NAMES = ["create_body", "set_datum"]


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in TOOL_NAMES]
