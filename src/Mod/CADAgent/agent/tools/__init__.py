# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unified MCP tool surface.

Step 1 of the harness refactor: this package is a re-export shim over
``agent.cli.dock_tools`` and ``agent.cli.mcp_tools``. The implementation
still lives in those modules; importing through ``agent.tools`` lets new
call sites pin themselves to the post-refactor layout while the code
moves underneath them in later steps.

Public surface:

* ``MCP_PREFIX`` — the ``mcp__<server>__`` prefix used by the SDK for
  in-process MCP tools. Single source of truth.
* ``short_name(full)`` — strip ``MCP_PREFIX`` if present.
* ``TOOL_FUNCS`` — combined list of every ``@tool``-decorated function
  the runtime should register.
* ``allowed_tool_names(server)`` — full MCP names (with prefix) for the
  permissions allowlist.

Per-domain submodules (``doc_lifecycle``, ``inspect``, ``memory``,
``plan``) re-export the relevant pieces so later steps can replace each
in isolation.
"""

from __future__ import annotations

from ..cli import dock_tools as _dock_tools, mcp_tools as _mcp_tools

MCP_PREFIX = "mcp__cad__"


def short_name(full: str) -> str:
    """Return ``full`` with ``MCP_PREFIX`` stripped if present."""
    if isinstance(full, str) and full.startswith(MCP_PREFIX):
        return full[len(MCP_PREFIX):]
    return full


TOOL_FUNCS = list(_mcp_tools.TOOL_FUNCS) + list(_dock_tools.TOOL_FUNCS)


def allowed_tool_names(server_name: str = "cad") -> list[str]:
    """Full MCP tool names for every tool in ``TOOL_FUNCS``."""
    return (
        _mcp_tools.allowed_tool_names(server_name)
        + _dock_tools.allowed_tool_names(server_name)
    )


__all__ = [
    "MCP_PREFIX",
    "short_name",
    "TOOL_FUNCS",
    "allowed_tool_names",
]
