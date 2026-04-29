# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unified MCP tool surface.

The implementation lives in topical submodules: ``doc_lifecycle`` (FreeCAD
GUI doc lifecycle, imports ``FreeCAD`` at module load), ``inspect`` (worker-
backed geometry queries), ``memory`` (project sidecar reads/writes), and
``plan`` (milestone tracking + ``exit_plan_mode``). Categories live in
``categories.py``; shared helpers in ``_common.py``.

Public surface:

* ``MCP_PREFIX`` — single source of truth for the ``mcp__cad__`` prefix.
* ``short_name(full)`` — strip ``MCP_PREFIX`` if present.
* ``TOOL_FUNCS`` — combined list of every ``@tool``-decorated function.
* ``allowed_tool_names(server)`` — full MCP names for the permissions
  allowlist.

The ``doc_lifecycle`` import is gated: it imports ``FreeCAD`` at module
load and would break the standalone CLI / pure-Python tests. Importers
that don't need GUI tools can import the topical submodules directly.
"""

from __future__ import annotations

MCP_PREFIX = "mcp__cad__"


def short_name(full: str) -> str:
    """Return ``full`` with ``MCP_PREFIX`` stripped if present."""
    if isinstance(full, str) and full.startswith(MCP_PREFIX):
        return full[len(MCP_PREFIX):]
    return full


# Worker-backed + sidecar tools — pure Python, safe in any host.
from .inspect import doc_reload, inspect, verify_spec  # noqa: E402
from .memory import (  # noqa: E402
    memory_decision_record,
    memory_decisions_list,
    memory_note_write,
    memory_parameter_set,
    memory_parameters_get,
    memory_read,
)
from .plan import (  # noqa: E402
    exit_plan_mode,
    plan_active_get,
    plan_emit,
    plan_milestone_activate,
    plan_milestone_done,
    plan_milestone_failed,
)

# Standalone-CLI tool list (no GUI tools — they require FreeCAD at import).
_CLI_TOOL_FUNCS = [
    inspect,
    verify_spec,
    doc_reload,
    memory_read,
    memory_note_write,
    memory_parameter_set,
    memory_parameters_get,
    memory_decision_record,
    memory_decisions_list,
    plan_emit,
    plan_active_get,
    plan_milestone_activate,
    plan_milestone_done,
    plan_milestone_failed,
    exit_plan_mode,
]


def _name_of(fn) -> str:
    return fn.name if hasattr(fn, "name") else fn.__name__


def cli_tool_funcs() -> list:
    """Tool functions safe to register in any host (no FreeCAD import)."""
    return list(_CLI_TOOL_FUNCS)


def gui_tool_funcs() -> list:
    """Tool functions that require FreeCAD at import (the GUI doc lifecycle).

    Imported lazily so a pure-Python caller (tests, standalone CLI) doesn't
    pull in ``import FreeCAD`` just by importing ``agent.tools``.
    """
    from . import doc_lifecycle
    return list(doc_lifecycle.TOOL_FUNCS)


# Combined surface for the in-FreeCAD dock runtime.
def all_tool_funcs() -> list:
    return cli_tool_funcs() + gui_tool_funcs()


def cli_allowed_tool_names(server_name: str = "cad") -> list[str]:
    return [f"mcp__{server_name}__{_name_of(fn)}" for fn in _CLI_TOOL_FUNCS]


def gui_allowed_tool_names(server_name: str = "cad") -> list[str]:
    from . import doc_lifecycle
    return doc_lifecycle.allowed_tool_names(server_name)


def allowed_tool_names(server_name: str = "cad") -> list[str]:
    return cli_allowed_tool_names(server_name) + gui_allowed_tool_names(server_name)


# Back-compat: TOOL_FUNCS used to be a flat list. Keep the attribute as a
# property-like accessor that lazily includes GUI tools — the only callers
# today are the dock runtime (always in-FreeCAD) and subagents (CLI only).
def __getattr__(name: str):
    if name == "TOOL_FUNCS":
        return all_tool_funcs()
    raise AttributeError(name)


__all__ = [
    "MCP_PREFIX",
    "short_name",
    "cli_tool_funcs",
    "gui_tool_funcs",
    "all_tool_funcs",
    "cli_allowed_tool_names",
    "gui_allowed_tool_names",
    "allowed_tool_names",
]
