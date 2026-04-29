# SPDX-License-Identifier: LGPL-2.1-or-later
"""Permission categories for every MCP tool the agent can call.

Single source of truth used by ``agent.permissions`` (Step 3 flip):

* ``READ`` — pure reads of project memory or sidecar state.
* ``INSPECT`` — read-only worker queries (``inspect``, ``inspect_live``,
  ``verify_spec``).
* ``DOC_LIFECYCLE`` — open / new / activate / reload a FreeCAD document.
  These mutate GUI state but not geometry; they're prompt-worthy by
  default but auto-allowable under acceptEdits / agent autonomous modes.
* ``MUTATING`` — anything that writes to disk (memory_*, plan_*) or
  changes the doc on disk (``doc_reload`` is currently MUTATING because
  it can clobber unsaved worker state).

Tool names here are the *short* names (without the ``mcp__cad__`` prefix).
Use ``names_for(cat, server="cad")`` to get prefixed names for the
permissions allowlist.
"""

from __future__ import annotations

from enum import Enum

from . import MCP_PREFIX


class Category(str, Enum):
    READ = "read"
    INSPECT = "inspect"
    DOC_LIFECYCLE = "doc_lifecycle"
    MUTATING = "mutating"


# Each tool's category. Names are the short, unprefixed names used by the
# ``@tool(...)`` decorator. Keep this in sync with the @tool definitions
# under agent/cli/{dock_tools,mcp_tools}.py until Step 4 moves them all
# under @cad_tool with category metadata.
_CATEGORY: dict[str, Category] = {
    # Worker-backed inspection (read-only)
    "inspect": Category.INSPECT,
    "verify_spec": Category.INSPECT,
    "gui_inspect_live": Category.INSPECT,
    # Read-only document queries
    "gui_documents_list": Category.READ,
    "gui_active_document": Category.READ,
    # Document lifecycle (mutates GUI state)
    "gui_new_document": Category.DOC_LIFECYCLE,
    "gui_open_document": Category.DOC_LIFECYCLE,
    "gui_set_active_document": Category.DOC_LIFECYCLE,
    "gui_reload_active_document": Category.DOC_LIFECYCLE,
    "doc_reload": Category.MUTATING,
    # Sidecar reads
    "memory_read": Category.READ,
    "memory_parameters_get": Category.READ,
    "memory_decisions_list": Category.READ,
    "plan_active_get": Category.READ,
    # Sidecar mutations
    "memory_note_write": Category.MUTATING,
    "memory_parameter_set": Category.MUTATING,
    "memory_decision_record": Category.MUTATING,
    "plan_emit": Category.MUTATING,
    "plan_milestone_activate": Category.MUTATING,
    "plan_milestone_done": Category.MUTATING,
    "plan_milestone_failed": Category.MUTATING,
    "exit_plan_mode": Category.MUTATING,
}


def category_of(short_name: str) -> Category | None:
    return _CATEGORY.get(short_name)


def names_for(*cats: Category, server: str = "cad") -> list[str]:
    """Full MCP names (with ``mcp__<server>__`` prefix) for every tool in
    one of the given categories."""
    prefix = MCP_PREFIX if server == "cad" else f"mcp__{server}__"
    wanted = set(cats)
    return [prefix + n for n, c in _CATEGORY.items() if c in wanted]


def all_short_names() -> list[str]:
    return list(_CATEGORY.keys())


def names_with_prefix(prefix: str, server: str = "cad") -> list[str]:
    """Full MCP names whose short name starts with ``prefix`` (e.g. ``plan_``).

    Used by ``permissions`` to derive UX-classification sets (plan-meta,
    file-edit) without re-listing every tool by hand.
    """
    full_prefix = MCP_PREFIX if server == "cad" else f"mcp__{server}__"
    return [full_prefix + n for n in _CATEGORY if n.startswith(prefix)]


__all__ = [
    "Category",
    "category_of",
    "names_for",
    "names_with_prefix",
    "all_short_names",
]
