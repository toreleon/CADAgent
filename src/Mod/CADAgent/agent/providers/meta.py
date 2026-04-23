# SPDX-License-Identifier: LGPL-2.1-or-later
"""Meta providers — let the agent introspect the verb/kind registry.

``cad_inspect(kind="schema.describe", params={"of_kind": "partdesign.pad"})``
returns the full schema + one canonical example for any registered kind.
This is the model's escape hatch when it isn't sure how to call something:
one read-only call surfaces the exact field names, types, and a concrete
example — no need to guess from the verb tool's description blurb.
"""

from __future__ import annotations

import json
from typing import Any

from .. import registry
from ..envelope import err_envelope


def _model_json_schema(model) -> dict | None:
    if model is None:
        return None
    try:
        return model.model_json_schema()
    except Exception as exc:
        return {"error": f"model_json_schema() failed: {exc}"}


def _find_kind(of_kind: str) -> tuple[str, registry.Kind] | None:
    """Locate a kind by name across all verbs. Returns (verb, Kind) or None."""
    for verb in registry.VERBS:
        rec = registry.get(verb, of_kind)
        if rec is not None:
            return verb, rec
    return None


def _describe(doc, params: dict[str, Any]) -> dict:
    of_kind = params.get("of_kind") or params.get("kind_name") or params.get("target")
    if not of_kind or not isinstance(of_kind, str):
        return err_envelope(
            "schema.describe",
            error_kind="invalid_argument",
            message="schema.describe requires 'of_kind' (the kind name to describe).",
            hint="Pass params={'of_kind': 'partdesign.pad'}.",
        )
    found = _find_kind(of_kind)
    if found is None:
        available = sorted(k.kind for k in registry.all_kinds())
        return err_envelope(
            "schema.describe",
            error_kind="invalid_argument",
            message=f"Unknown kind {of_kind!r}.",
            hint="Pass params.of_kind equal to one of the names listed in 'available'.",
            extras={"available": available[:200]},
        )
    verb, rec = found
    body = {
        "ok": True,
        "kind": "schema.describe",
        "created": [], "modified": [], "deleted": [],
        "context": {},
        "warnings": [],
        "error": None,
        "describes": {
            "verb": verb,
            "kind": rec.kind,
            "description": rec.description,
            "read_only": not rec.is_mutating,
            "params_schema": rec.params_schema,
            "json_schema": _model_json_schema(rec.model),
            "example": rec.example,
            "implementation": "native" if rec.native
                              else ("passthrough" if rec.passthrough else "legacy"),
        },
    }
    return {"content": [{"type": "text", "text": json.dumps(body, default=str)}]}


registry.register(
    verb="inspect",
    kind="schema.describe",
    description=(
        "Return the full param schema (and an example) for any registered "
        "kind. Use this when a call keeps failing with 'invalid_argument' or "
        "when you're unsure which fields a kind expects. Pass "
        "params={'of_kind': '<kind name>'}."
    ),
    params_schema={"of_kind": "str"},
    execute=_describe,
    native=True,
    read_only=True,
    example={"of_kind": "partdesign.pad"},
)


# inspect.context — one-call active-state snapshot. Removes the "which body
# am I padding into?" guessing that today forces the agent to chain several
# inspect calls or assume the wrong Body.

def _context(doc, params: dict[str, Any]) -> dict:
    from ..envelope import ok_envelope
    import FreeCAD as App

    resolved = doc if doc is not None else App.ActiveDocument
    extras: dict[str, Any] = {
        "documents": list(App.listDocuments().keys()),
        "units": "mm",  # FreeCAD internal unit for lengths; informational.
    }
    if resolved is not None:
        # Compact object summary — name/type/visible so the agent can pick a
        # target without another cad_inspect round-trip.
        objs: list[dict[str, Any]] = []
        for obj in resolved.Objects:
            item = {"name": obj.Name, "label": obj.Label, "type": obj.TypeId}
            try:
                vo = getattr(obj, "ViewObject", None)
                if vo is not None:
                    item["visible"] = bool(vo.Visibility)
            except Exception:
                pass
            objs.append(item)
        extras["objects"] = objs
        # The most recent mutating tool result (echoed from _LAST_RESULT).
        from ..tools._shared import _LAST_RESULT
        extras["last_result"] = _LAST_RESULT.get("summary")
    return ok_envelope("context", doc=resolved, extras=extras)


registry.register(
    verb="inspect",
    kind="context",
    description=(
        "Return a single snapshot of the active state: active document, "
        "active Body, object list (name/type/visible), and the previous "
        "tool result. Call this once at the start of a turn instead of "
        "chaining document.active + object.list + selection.get."
    ),
    params_schema={"doc": "str?"},
    execute=_context,
    native=True,
    read_only=True,
    example={},
)
