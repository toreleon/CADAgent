# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tool registry: ``@cad_tool`` decorator, ``_REGISTRY`` map, ``build_server``.

Lives in its own module to dodge the import cycle between ``tools/__init__``
and the topical submodules. Submodules import ``cad_tool`` from here; the
package ``__init__`` re-exports it for convenience.

A registered tool carries:

* ``callable`` — the SDK-decorated coroutine (return value of ``@tool``).
* ``category`` — for permission derivation (``READ``, ``INSPECT``,
  ``DOC_LIFECYCLE``, ``MUTATING``).
* ``schema`` / ``summary`` — kept around for introspection / docs.

The decorator is the only registration path; there is no
``register(...)`` helper. Decorating with ``@cad_tool`` always registers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from claude_agent_sdk import create_sdk_mcp_server, tool

from .categories import Category


MCP_PREFIX = "mcp__cad__"


def short_name(full: str) -> str:
    """Return ``full`` with ``MCP_PREFIX`` stripped if present."""
    if isinstance(full, str) and full.startswith(MCP_PREFIX):
        return full[len(MCP_PREFIX):]
    return full


@dataclass(frozen=True)
class ToolSpec:
    name: str
    summary: str
    schema: dict[str, Any]
    category: Category
    callable: Any  # the SDK-decorated coroutine


_REGISTRY: dict[str, ToolSpec] = {}


def cad_tool(
    name: str,
    summary: str,
    schema: dict[str, Any],
    *,
    category: Category,
    annotations=None,
) -> Callable:
    """Drop-in replacement for ``claude_agent_sdk.tool`` that records the
    tool's ``category`` in the registry.

    Usage:

    .. code-block:: python

        @cad_tool("memory_read", "Read sidecar.", schema(),
                  category=Category.READ, annotations=READ_ONLY)
        async def memory_read(args): ...
    """

    def _decorate(fn):
        decorated = tool(name, summary, schema, annotations=annotations)(fn)
        _REGISTRY[name] = ToolSpec(
            name=name,
            summary=summary,
            schema=schema,
            category=category,
            callable=decorated,
        )
        return decorated

    return _decorate


def registered_tools() -> list[ToolSpec]:
    """Snapshot of every registered tool, in registration order."""
    return list(_REGISTRY.values())


def registered_callables() -> list[Any]:
    """Just the SDK-decorated callables, ready for ``create_sdk_mcp_server``."""
    return [spec.callable for spec in _REGISTRY.values()]


def build_server(name: str = "cad", extra: list | None = None):
    """Build the in-process MCP server holding every registered tool.

    Reads the live registry — every module decorated with ``@cad_tool``
    that has been imported by the time of this call is included. Hosts
    that need GUI tools must import ``agent.tools.doc_lifecycle`` (or the
    ``cli/dock_tools`` shim) before calling this.

    ``extra`` exists for callables that are not yet on ``@cad_tool`` and
    must be passed in by hand. The function deduplicates by callable
    identity so passing already-registered tools is a no-op.
    """
    seen = set()
    callables: list = []
    for fn in registered_callables() + list(extra or []):
        if id(fn) in seen:
            continue
        seen.add(id(fn))
        callables.append(fn)
    return create_sdk_mcp_server(name=name, tools=callables)


def registered_short_names() -> list[str]:
    return [spec.name for spec in _REGISTRY.values()]


__all__ = [
    "MCP_PREFIX",
    "short_name",
    "ToolSpec",
    "cad_tool",
    "registered_tools",
    "registered_callables",
    "build_server",
]
