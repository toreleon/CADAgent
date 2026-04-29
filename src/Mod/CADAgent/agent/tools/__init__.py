# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unified MCP tool surface.

Tools are declared with ``@cad_tool(category=...)`` in topical
submodules — ``inspect``, ``memory``, ``plan`` for the standalone CLI
tools, plus ``doc_lifecycle`` for the FreeCAD GUI tools. Importing the
submodule registers them; ``build_server`` then constructs a single
in-process MCP server holding all of them.

Public surface:

* ``cad_tool`` / ``build_server`` — the decorator + server factory.
* ``MCP_PREFIX`` / ``short_name(full)`` — the ``mcp__cad__`` prefix and
  its inverse.
* ``cli_tool_funcs`` / ``gui_tool_funcs`` / ``all_tool_funcs`` — callable
  lists used by the runtime when constructing options.
* ``allowed_tool_names(server)`` — full MCP names for the permissions
  allowlist.

The ``doc_lifecycle`` import is gated: it imports ``FreeCAD`` at module
load and would break the standalone CLI / pure-Python tests. Importers
that don't need GUI tools can stick with ``cli_tool_funcs``.
"""

from __future__ import annotations

from ._registry import (
    MCP_PREFIX,
    ToolSpec,
    build_server,
    cad_tool,
    registered_callables,
    registered_short_names,
    registered_tools,
    short_name,
)

# Importing the topical modules triggers @cad_tool registration as a
# side effect. Do this BEFORE any code calls registered_tools().
from . import inspect as _inspect_mod  # noqa: F401, E402
from . import memory as _memory_mod  # noqa: F401, E402
from . import plan as _plan_mod  # noqa: F401, E402

# Re-export the individual tool callables for back-compat / direct import.
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


def _name_of(fn) -> str:
    return fn.name if hasattr(fn, "name") else fn.__name__


def cli_tool_funcs() -> list:
    """Tool callables safe to register in any host (no FreeCAD import)."""
    return list(registered_callables())


def gui_tool_funcs() -> list:
    """Tool callables that require FreeCAD at import (the GUI doc lifecycle).

    Imported lazily so a pure-Python caller (tests, standalone CLI) doesn't
    pull in ``import FreeCAD`` just by importing ``agent.tools``.
    """
    from . import doc_lifecycle  # registers gui_* tools as a side effect

    return list(doc_lifecycle.TOOL_FUNCS)


def all_tool_funcs() -> list:
    return cli_tool_funcs() + gui_tool_funcs()


def cli_allowed_tool_names(server_name: str = "cad") -> list[str]:
    return [f"mcp__{server_name}__{_name_of(fn)}" for fn in cli_tool_funcs()]


def gui_allowed_tool_names(server_name: str = "cad") -> list[str]:
    return [f"mcp__{server_name}__{_name_of(fn)}" for fn in gui_tool_funcs()]


def allowed_tool_names(server_name: str = "cad") -> list[str]:
    """Names of every tool currently registered (CLI + GUI if imported)."""
    prefix = MCP_PREFIX if server_name == "cad" else f"mcp__{server_name}__"
    return [prefix + n for n in registered_short_names()]


# Back-compat: TOOL_FUNCS used to be a flat list. Keep the attribute as
# a property-like accessor that lazily includes GUI tools.
def __getattr__(name: str):
    if name == "TOOL_FUNCS":
        return all_tool_funcs()
    raise AttributeError(name)


__all__ = [
    "MCP_PREFIX",
    "ToolSpec",
    "build_server",
    "cad_tool",
    "registered_callables",
    "registered_tools",
    "short_name",
    "cli_tool_funcs",
    "gui_tool_funcs",
    "all_tool_funcs",
    "cli_allowed_tool_names",
    "gui_allowed_tool_names",
    "allowed_tool_names",
]
