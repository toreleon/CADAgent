# SPDX-License-Identifier: LGPL-2.1-or-later
"""Structured error taxonomy for CAD Agent tools.

Every tool funnels failures through `fail(kind, ...)` so the agent sees a
stable schema with a human `message`, a machine `hint`, and a list of
`recover_tools` to try next. This is what turns "your sketch is wrong" into
"add 2 Distance constraints, then retry pad".
"""

from __future__ import annotations

import json
from typing import Any


# Catalog of error kinds. Keep small and stable — the system prompt teaches
# the agent to read `kind` and `recover_tools`, so renaming breaks the agent.
_RECIPES: dict[str, dict[str, Any]] = {
    "no_active_document": {
        "message": "No active FreeCAD document.",
        "hint": "Call create_document first, then retry.",
        "recover_tools": ["mcp__cad__create_document"],
    },
    "no_active_body": {
        "message": "No active PartDesign::Body in the document.",
        "hint": "Call create_body (or pass body='Body001') before creating sketches or features.",
        "recover_tools": ["mcp__cad__create_body"],
    },
    "sketch_malformed": {
        "message": "Sketch has malformed constraints and cannot be used as a pad/pocket profile.",
        "hint": "Remove the constraints listed in `malformed`, then retry.",
        "recover_tools": ["mcp__cad__add_sketch_constraint", "mcp__cad__close_sketch"],
    },
    "sketch_underconstrained": {
        "message": "Sketch has remaining degrees of freedom; the solver left geometry unfixed.",
        "hint": "Add dimensional constraints (Distance, DistanceX, DistanceY, Radius) until DOF=0 before padding.",
        "recover_tools": ["mcp__cad__add_sketch_constraint", "mcp__cad__close_sketch"],
    },
    "sketch_overconstrained": {
        "message": "Sketch has conflicting or redundant constraints.",
        "hint": "Remove one of the conflicting constraints listed in `conflicting`.",
        "recover_tools": ["mcp__cad__add_sketch_constraint", "mcp__cad__close_sketch"],
    },
    "invalid_solid": {
        "message": "Feature produced an invalid solid (self-intersection, open shell, etc).",
        "hint": "Inspect the inputs — in particular the sketch profile — and rebuild with a cleaner sketch.",
        "recover_tools": ["mcp__cad__close_sketch", "mcp__cad__verify_feature"],
    },
    "topology_reference_missing": {
        "message": "A topology reference (face/edge name) no longer exists after recompute.",
        "hint": "Re-read the feature with get_object to find current Face/Edge names, then retry.",
        "recover_tools": ["mcp__cad__get_object", "mcp__cad__get_selection"],
    },
    "feature_recompute_failed": {
        "message": "Feature recompute raised an error.",
        "hint": "Check the feature's inputs and the message; most often a sketch profile or a missing reference.",
        "recover_tools": ["mcp__cad__get_object"],
    },
    "permission_denied": {
        "message": "User rejected the permission prompt.",
        "hint": "Do not retry the same action. Ask the user what to do differently.",
        "recover_tools": [],
    },
    "unknown_parameter": {
        "message": "Named parameter is not defined in project memory.",
        "hint": "Call set_parameter to define it before binding an expression to it.",
        "recover_tools": ["mcp__cad__set_parameter", "mcp__cad__get_parameters"],
    },
    "expression_syntax": {
        "message": "Expression could not be parsed by FreeCAD's expression engine.",
        "hint": "Use the 'Parameters.Name' form; avoid spaces and units in the expression string.",
        "recover_tools": ["mcp__cad__set_datum"],
    },
    "invalid_argument": {
        "message": "Tool argument failed validation.",
        "hint": "See `details` for the specific field.",
        "recover_tools": [],
    },
    "internal_error": {
        "message": "Unhandled internal error inside the CAD tool.",
        "hint": "Surface this to the user; do not retry blindly.",
        "recover_tools": [],
    },
}


def fail(kind: str, **details: Any) -> dict:
    """Build a structured error payload for an MCP tool.

    `details` are merged into the top-level payload so tool-specific fields
    (e.g. sketch name, DOF, malformed ids) travel alongside the canned copy.
    Extra keys override the recipe defaults — pass `hint=...` or
    `recover_tools=[...]` to override per-call.
    """
    recipe = _RECIPES.get(kind, _RECIPES["internal_error"])
    payload: dict[str, Any] = {
        "ok": False,
        "error": kind,
        "message": recipe["message"],
        "hint": recipe["hint"],
        "recover_tools": list(recipe["recover_tools"]),
    }
    payload.update(details)
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        "is_error": True,
    }


def classify_exception(exc: BaseException) -> str:
    """Best-effort mapping from a raw Python exception to an error kind."""
    msg = (str(exc) or exc.__class__.__name__).lower()
    if "no active" in msg and "document" in msg:
        return "no_active_document"
    if "no active" in msg and "body" in msg:
        return "no_active_body"
    if "malformed" in msg:
        return "sketch_malformed"
    if "conflict" in msg or "redundant" in msg:
        return "sketch_overconstrained"
    if "expression" in msg:
        return "expression_syntax"
    if "recompute" in msg:
        return "feature_recompute_failed"
    return "internal_error"
