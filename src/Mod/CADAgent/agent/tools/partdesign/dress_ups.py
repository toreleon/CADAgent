# SPDX-License-Identifier: LGPL-2.1-or-later
"""Edge dress-up MCP tools: Fillet and Chamfer."""

from __future__ import annotations

import traceback

from claude_agent_sdk import tool

from ...gui_thread import run_sync
from .._shared import ok, err, resolve_doc, summarise_result, with_transaction
from ._pd_shared import add_feature, body_of, edge_refs_to_base


@tool(
    "fillet",
    (
        "Add a PartDesign::Fillet on the given edges. edges is a list of "
        "'Feature.EdgeN' strings; all must belong to the same feature."
    ),
    {
        "type": "object",
        "properties": {
            "edges": {"type": "array", "items": {"type": "string"}},
            "radius": {"type": "number"},
            "name": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["edges", "radius"],
    },
)
async def fillet(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        feat, subs = edge_refs_to_base(doc, args["edges"])
        body = body_of(feat)
        if body is None:
            raise ValueError(f"{feat.Name} is not inside a PartDesign::Body.")
        name = args.get("name") or "Fillet"

        def work():
            f = add_feature(body, "PartDesign::Fillet", name)
            f.Base = (feat, subs)
            f.Radius = float(args["radius"])
            doc.recompute()
            return f

        f = with_transaction(doc, f"fillet {name}", work)
        summary = summarise_result(doc, [f.Name])
        summary["body"] = body.Name
        summary["edges"] = args["edges"]
        return summary

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


@tool(
    "chamfer",
    (
        "Add a PartDesign::Chamfer on the given edges. edges is a list of "
        "'Feature.EdgeN' strings; all must belong to the same feature."
    ),
    {
        "type": "object",
        "properties": {
            "edges": {"type": "array", "items": {"type": "string"}},
            "size": {"type": "number"},
            "name": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["edges", "size"],
    },
)
async def chamfer(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        feat, subs = edge_refs_to_base(doc, args["edges"])
        body = body_of(feat)
        if body is None:
            raise ValueError(f"{feat.Name} is not inside a PartDesign::Body.")
        name = args.get("name") or "Chamfer"

        def work():
            f = add_feature(body, "PartDesign::Chamfer", name)
            f.Base = (feat, subs)
            if "Size" in f.PropertiesList:
                f.Size = float(args["size"])
            doc.recompute()
            return f

        f = with_transaction(doc, f"chamfer {name}", work)
        summary = summarise_result(doc, [f.Name])
        summary["body"] = body.Name
        summary["edges"] = args["edges"]
        return summary

    try:
        return ok(run_sync(_do))
    except Exception as exc:
        return err(f"{exc}\n{traceback.format_exc()}")


TOOL_FUNCS = [fillet, chamfer]
TOOL_NAMES = ["fillet", "chamfer"]


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in TOOL_NAMES]
