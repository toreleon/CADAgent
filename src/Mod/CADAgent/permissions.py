# SPDX-License-Identifier: LGPL-2.1-or-later
"""Permission hook bridging the Claude Agent SDK `can_use_tool` callback to the
inline Apply / Reject cards rendered by ChatPanel."""

from dataclasses import dataclass


# Tools that never mutate the document — auto-allow to keep the UX snappy.
READ_ONLY_TOOLS = {
    "mcp__cad__list_documents",
    "mcp__cad__get_active_document",
    "mcp__cad__list_objects",
    "mcp__cad__get_object",
    "mcp__cad__get_selection",
    "mcp__cad__recompute_and_fit",
}


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


def make_can_use_tool(panel):
    """Return a `can_use_tool` coroutine bound to the given ChatPanel.

    The panel is responsible for:
      * rendering a card for the proposed tool call,
      * exposing Apply / Reject buttons, and
      * returning a Decision via an asyncio.Future.
    """

    async def can_use_tool(tool_name, tool_input, context=None):
        # Fast-path read-only introspection tools.
        if tool_name in READ_ONLY_TOOLS:
            return {"behavior": "allow", "updatedInput": tool_input}

        # Mutating tool: ask the user.
        decision = await panel.request_permission(tool_name, tool_input)
        if decision.allowed:
            return {"behavior": "allow", "updatedInput": tool_input}
        return {
            "behavior": "deny",
            "message": decision.reason or "User rejected this action.",
        }

    return can_use_tool
