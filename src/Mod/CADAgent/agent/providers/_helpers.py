# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared provider helpers — primarily a compact way to register a kind that
wraps an existing v1 SDK tool handler unchanged.

During the v1→v2 migration we don't rewrite tool bodies; we just expose them
under the new verb surface. Each provider entry calls ``passthrough(...)`` with
the v1 tool, the verb/kind it should appear under, and a translator that
massages v2 args ({kind, params, …}) into v1 args ({field: value, …}).

For most tools the translator is the identity — v1 args are exactly the
v2 ``params`` dict — so the default works.
"""

from __future__ import annotations

from typing import Any, Callable

from .. import registry


def _identity_translate(args: dict[str, Any]) -> dict[str, Any]:
    """Default v2→v1 args translator: lift `params` to top-level."""
    out = dict(args.get("params") or {})
    # Many v1 tools accept a top-level `doc`; fold it through.
    if "doc" in args and "doc" not in out:
        out["doc"] = args["doc"]
    return out


def passthrough(
    *,
    verb: str,
    kind: str,
    v1_tool: Any,
    description: str,
    params_schema: dict[str, str] | None = None,
    translate: Callable[[dict], dict] | None = None,
    read_only: bool | None = None,
) -> None:
    """Register a kind whose implementation is an existing v1 SDK tool.

    ``v1_tool`` is the ``SdkMcpTool`` instance produced by ``@tool(...)`` —
    its ``.handler`` is the async function we call. The dispatcher's
    passthrough mode bypasses our preflight/transaction/summarize and just
    returns the v1 result verbatim (it is already MCP-shaped).
    """
    registry.register(
        verb=verb,
        kind=kind,
        description=description,
        params_schema=params_schema or {},
        execute=translate or _identity_translate,
        summarize=getattr(v1_tool, "handler", None),
        passthrough=True,
        read_only=read_only,
    )
