# SPDX-License-Identifier: LGPL-2.1-or-later
"""Custom tools exposing FreeCAD's Python API to the CAD Agent.

Each mutating tool wraps its work in ``doc.openTransaction / commitTransaction``
so a single agent action becomes one Ctrl+Z step. Read-only tools return
JSON-encoded summaries of the requested state.

Importing this package triggers every submodule so their ``@tool`` decorators
run and the tool registry is populated before the server is built.
"""

from __future__ import annotations

from . import doc, selection, geometry, memory, diagnostics, partdesign, macros
from ._shared import mark_tool, get_last_result_summary


_MODULES = (doc, selection, geometry, memory, diagnostics, partdesign, macros)


def tool_funcs() -> list:
    """Return all registered tool handler objects for use with create_sdk_mcp_server()."""
    out: list = []
    for m in _MODULES:
        out.extend(m.TOOL_FUNCS)
    return out


def tool_names() -> list[str]:
    out: list[str] = []
    for m in _MODULES:
        out.extend(m.TOOL_NAMES)
    return out


def allowed_tool_names() -> list[str]:
    """Return the full tool names as the Claude CLI expects them (mcp__cad__ prefix)."""
    return [f"mcp__cad__{n}" for n in tool_names()]


__all__ = [
    "tool_funcs",
    "tool_names",
    "allowed_tool_names",
    "mark_tool",
    "get_last_result_summary",
]
