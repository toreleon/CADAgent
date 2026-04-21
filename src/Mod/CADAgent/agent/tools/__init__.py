# SPDX-License-Identifier: LGPL-2.1-or-later
"""In-process MCP tools exposing FreeCAD's Python API to the CAD Agent.

Each mutating tool wraps its work in `doc.openTransaction / commitTransaction`
so a single agent action becomes one Ctrl+Z step. Read-only tools return
JSON-encoded summaries of the requested state.

Importing this package triggers every submodule so their ``@tool`` decorators
run and the tool registry is populated before `build_mcp_server` is called.
"""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from . import doc, selection, geometry, memory, diagnostics, partdesign, macros
from ._shared import mark_tool, get_last_result_summary


_MODULES = (doc, selection, geometry, memory, diagnostics, partdesign, macros)


def _all_tool_funcs() -> list:
    out: list = []
    for m in _MODULES:
        out.extend(m.TOOL_FUNCS)
    return out


def _all_tool_names() -> list[str]:
    out: list[str] = []
    for m in _MODULES:
        out.extend(m.TOOL_NAMES)
    return out


def build_mcp_server():
    """Create the in-process MCP server exposing CAD tools."""
    return create_sdk_mcp_server(name="cad", version="0.1.0", tools=_all_tool_funcs())


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in _all_tool_names()]


__all__ = [
    "build_mcp_server",
    "allowed_tool_names",
    "mark_tool",
    "get_last_result_summary",
]
