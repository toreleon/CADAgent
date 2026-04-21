# SPDX-License-Identifier: LGPL-2.1-or-later
"""PartDesign MCP tools: body, sketch, pad/pocket, dress-ups."""

from __future__ import annotations

from . import body, sketch, pad_pocket, dress_ups


TOOL_FUNCS = (
    body.TOOL_FUNCS
    + sketch.TOOL_FUNCS
    + pad_pocket.TOOL_FUNCS
    + dress_ups.TOOL_FUNCS
)

TOOL_NAMES = (
    body.TOOL_NAMES
    + sketch.TOOL_NAMES
    + pad_pocket.TOOL_NAMES
    + dress_ups.TOOL_NAMES
)


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in TOOL_NAMES]
