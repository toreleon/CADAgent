# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pad and Pocket MCP tools."""

from __future__ import annotations

import traceback

from claude_agent_sdk import tool

from ... import errors
from ...gui_thread import run_sync
from .._shared import (
    ok,
    resolve_doc,
    sketch_health,
    summarise_result,
    with_transaction,
)
from ._pd_shared import add_feature, body_of, resolve_sketch


_PAD_TYPES = {"Length", "TwoLengths", "ThroughAll", "UpToFirst", "UpToLast", "UpToFace"}


@tool(
    "pad",
    (
        "Create a PartDesign::Pad extruding a sketch. type defaults to "
        "'Length'. length is in mm. midplane/reversed are booleans."
    ),
    {
        "type": "object",
        "properties": {
            "sketch": {"type": "string"},
            "length": {"type": "number"},
            "type_": {"type": "string", "description": "Pad type"},
            "midplane": {"type": "boolean"},
            "reversed": {"type": "boolean"},
            "name": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["sketch", "length"],
    },
)
async def pad(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        sk = resolve_sketch(doc, args["sketch"])
        body = body_of(sk)
        if body is None:
            raise ValueError(f"Sketch {sk.Name} is not inside a PartDesign::Body.")
        pad_type = args.get("type_") or "Length"
        if pad_type not in _PAD_TYPES:
            raise ValueError(f"Unknown pad type {pad_type!r}. Use one of {sorted(_PAD_TYPES)}.")
        name = args.get("name") or "Pad"

        # Gate on sketch health before touching the document — a broken sketch
        # would otherwise silently produce an invalid solid (triangle-prism bug).
        try:
            sk.solve()
        except Exception:
            pass
        health = sketch_health(sk)
        if health["malformed"]:
            return {"__error__": errors.fail("sketch_malformed", sketch=sk.Name, **health)}
        if health["conflicting"] or health["redundant"]:
            return {"__error__": errors.fail("sketch_overconstrained", sketch=sk.Name, **health)}
        if health["dof"] > 0:
            return {"__error__": errors.fail(
                "sketch_underconstrained", sketch=sk.Name,
                hint=f"Sketch has {health['dof']} DOF; add dimensional constraints before padding.",
                **health,
            )}

        def work():
            feat = add_feature(body, "PartDesign::Pad", name)
            feat.Profile = sk
            feat.Length = float(args["length"])
            feat.Type = pad_type
            midplane = bool(args.get("midplane", False))
            if "SideType" in feat.PropertiesList:
                feat.SideType = "Symmetric" if midplane else "One side"
            elif "Midplane" in feat.PropertiesList:
                feat.Midplane = midplane
            if "Reversed" in feat.PropertiesList:
                feat.Reversed = bool(args.get("reversed", False))
            doc.recompute()
            return feat

        feat = with_transaction(doc, f"pad {name}", work)
        summary = summarise_result(doc, [feat.Name])
        summary["body"] = body.Name
        if not summary.get("is_valid_solid"):
            return {"__error__": errors.fail(
                "invalid_solid", feature=feat.Name,
                hint="Pad ran but produced an invalid solid; inspect the sketch profile.",
                **summary,
            )}
        return summary

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


@tool(
    "pocket",
    (
        "Create a PartDesign::Pocket subtracting an extrusion of a sketch. "
        "length in mm. through_all overrides length with Type='ThroughAll'."
    ),
    {
        "type": "object",
        "properties": {
            "sketch": {"type": "string"},
            "length": {"type": "number"},
            "through_all": {"type": "boolean"},
            "reversed": {"type": "boolean"},
            "name": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": ["sketch"],
    },
)
async def pocket(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        sk = resolve_sketch(doc, args["sketch"])
        body = body_of(sk)
        if body is None:
            raise ValueError(f"Sketch {sk.Name} is not inside a PartDesign::Body.")
        name = args.get("name") or "Pocket"
        through = bool(args.get("through_all", False))
        if not through and args.get("length") is None:
            raise ValueError("pocket needs either length or through_all=true.")

        try:
            sk.solve()
        except Exception:
            pass
        health = sketch_health(sk)
        if health["malformed"]:
            return {"__error__": errors.fail("sketch_malformed", sketch=sk.Name, **health)}
        if health["conflicting"] or health["redundant"]:
            return {"__error__": errors.fail("sketch_overconstrained", sketch=sk.Name, **health)}
        if health["dof"] > 0:
            return {"__error__": errors.fail(
                "sketch_underconstrained", sketch=sk.Name,
                hint=f"Sketch has {health['dof']} DOF; add dimensional constraints before pocketing.",
                **health,
            )}

        def work():
            feat = add_feature(body, "PartDesign::Pocket", name)
            feat.Profile = sk
            if through:
                feat.Type = "ThroughAll"
            else:
                feat.Type = "Length"
                feat.Length = float(args["length"])
            if "Reversed" in feat.PropertiesList:
                feat.Reversed = bool(args.get("reversed", False))
            doc.recompute()
            return feat

        feat = with_transaction(doc, f"pocket {name}", work)
        summary = summarise_result(doc, [feat.Name])
        summary["body"] = body.Name
        return summary

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


TOOL_FUNCS = [pad, pocket]
TOOL_NAMES = ["pad", "pocket"]


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in TOOL_NAMES]
