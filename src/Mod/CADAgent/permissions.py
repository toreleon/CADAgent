# SPDX-License-Identifier: LGPL-2.1-or-later
"""Permission hook bridging the Claude Agent SDK `can_use_tool` callback to the
inline Apply / Reject cards rendered by ChatPanel.

The SDK callback runs on the asyncio worker thread; the panel lives on the Qt
GUI thread. A `concurrent.futures.Future` carries the user's decision back
across that boundary.
"""

import asyncio
import concurrent.futures
from dataclasses import dataclass


# Tools that never mutate the document — auto-allow to keep the UX snappy.
READ_ONLY_TOOLS = {
    "mcp__cad__list_documents",
    "mcp__cad__get_active_document",
    "mcp__cad__list_objects",
    "mcp__cad__get_object",
    "mcp__cad__get_selection",
    "mcp__cad__recompute_and_fit",
    "mcp__cad__read_project_memory",
    "mcp__cad__get_parameters",
    # Diagnostics (Slice 4 will add render_view etc).
    "mcp__cad__verify_sketch",
    "mcp__cad__verify_feature",
    "mcp__cad__preview_topology",
    "mcp__cad__render_view",
}


def is_dry_run(tool_input: dict) -> bool:
    """Dry-run invocations never touch the document — auto-allow them."""
    return bool((tool_input or {}).get("dry_run"))


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


def make_can_use_tool(proxy):
    """Return a `can_use_tool` coroutine that asks the GUI thread via `proxy`.

    `proxy` is a `_PanelProxy` QObject whose `permissionRequest` signal is
    connected to a slot that creates a card on the panel and resolves the
    provided concurrent.futures.Future on Apply / Reject.
    """

    async def can_use_tool(tool_name, tool_input, context=None):
        if tool_name in READ_ONLY_TOOLS or is_dry_run(tool_input):
            return {"behavior": "allow", "updatedInput": tool_input}

        cf: concurrent.futures.Future = concurrent.futures.Future()
        proxy.permissionRequest.emit(tool_name, tool_input, cf)
        decision = await asyncio.wrap_future(cf)
        if decision.allowed:
            return {"behavior": "allow", "updatedInput": tool_input}
        return {
            "behavior": "deny",
            "message": decision.reason or "User rejected this action.",
        }

    return can_use_tool
