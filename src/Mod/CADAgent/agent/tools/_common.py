# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared MCP-tool helpers: response envelopes, schema helpers, doc-arg parsing.

Every tool returns a ``content``/``isError`` envelope shaped like the SDK
wants and serialises a JSON payload inside the single text block. ``_ok`` /
``_err`` keep that contract in one place; ``_schema`` builds a JSON Schema
with ``doc`` pre-required; ``_handle`` resolves the ``doc`` arg into a
``DocHandle``.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import ToolAnnotations

from ..doc_handle import DocHandle


READ_ONLY = ToolAnnotations(readOnlyHint=True)


def ok(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps({"ok": True, **payload}, default=str)}]}


def err(message: str, **extras: Any) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps({"ok": False, "error": message, **extras}, default=str)}],
        "isError": True,
    }


def handle(args: dict) -> DocHandle:
    """Resolve the ``doc`` argument into a DocHandle, or raise."""
    path = (args or {}).get("doc")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("'doc' is required: absolute path to the .FCStd file")
    return DocHandle(path)


def schema(**properties) -> dict:
    """Build a JSON Schema with ``doc`` pre-required and extras as given.

    The SDK's dict-shorthand marks every listed property required; the verbose
    form lets us separate required from optional. Pass ``required=True`` on a
    property dict to mark it required.
    """
    required = ["doc"]
    props: dict[str, Any] = {"doc": {"type": "string"}}
    for name, spec in properties.items():
        rq = spec.pop("required", False) if isinstance(spec, dict) else False
        props[name] = spec
        if rq:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


__all__ = ["READ_ONLY", "ok", "err", "handle", "schema", "DocHandle"]
