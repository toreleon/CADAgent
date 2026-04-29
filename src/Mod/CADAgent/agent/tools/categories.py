# SPDX-License-Identifier: LGPL-2.1-or-later
"""Permission categories.

The category for each tool is declared at the ``@cad_tool`` decoration
site (Step 4 of the harness refactor); this module just defines the
``Category`` enum and the live-registry-driven lookup helpers used by
``agent.permissions``.

Categories:

* ``READ`` — pure reads of project memory or sidecar state.
* ``INSPECT`` — read-only worker queries (``inspect``, ``inspect_live``,
  ``verify_spec``).
* ``DOC_LIFECYCLE`` — open / new / activate a FreeCAD document.
* ``MUTATING`` — anything that writes to disk or alters worker state
  (memory_*, plan_*, ``doc_reload``).
"""

from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    READ = "read"
    INSPECT = "inspect"
    DOC_LIFECYCLE = "doc_lifecycle"
    MUTATING = "mutating"


def category_of(short_name: str) -> Category | None:
    """Return the category of the registered tool ``short_name``."""
    from ._registry import _REGISTRY  # local import to dodge the cycle

    spec = _REGISTRY.get(short_name)
    return spec.category if spec else None


def names_for(*cats: Category, server: str = "cad") -> list[str]:
    """Full MCP names (``mcp__<server>__<short>``) for every registered tool
    whose category is in ``cats``."""
    from ._registry import MCP_PREFIX, _REGISTRY  # local import

    prefix = MCP_PREFIX if server == "cad" else f"mcp__{server}__"
    wanted = set(cats)
    return [prefix + spec.name for spec in _REGISTRY.values() if spec.category in wanted]


def all_short_names() -> list[str]:
    from ._registry import _REGISTRY

    return [spec.name for spec in _REGISTRY.values()]


def names_with_prefix(prefix: str, server: str = "cad") -> list[str]:
    """Full MCP names whose short name starts with ``prefix`` (e.g. ``plan_``).

    Used by ``permissions`` to derive UX-classification sets (plan-meta)
    without re-listing every tool by hand.
    """
    from ._registry import MCP_PREFIX, _REGISTRY

    full_prefix = MCP_PREFIX if server == "cad" else f"mcp__{server}__"
    return [full_prefix + spec.name for spec in _REGISTRY.values() if spec.name.startswith(prefix)]


__all__ = [
    "Category",
    "category_of",
    "names_for",
    "names_with_prefix",
    "all_short_names",
]
