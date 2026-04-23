# SPDX-License-Identifier: LGPL-2.1-or-later
"""Specialist subagents for the CAD Agent orchestrator.

Subagents are declared as ``AgentDefinition`` values and attached to the
runtime's ``ClaudeAgentOptions.agents``. The main agent delegates to them via
the SDK's built-in ``Agent`` tool — pass the subagent name + a prompt and
the SDK spins up a fresh conversation with only that subagent's tool list
in scope.

Important SDK constraints (as of claude_agent_sdk 0.1.63):

- Subagent invocations run serially inside one ``query()``.
- Subagents do NOT inherit parent conversation memory. The orchestrator
  must pass any relevant decision / milestone context in the Agent-tool
  prompt.
- ``tools=[...]`` is a literal list of full tool names. No wildcards are
  honoured, so we enumerate from the canonical registry in ``tools/``.
- Nested subagents are not supported; stay flat.

This module defines the factories; ``runtime.py`` calls them when it builds
options so the tool list is always in sync with the live registry.
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from . import tools as cad_tools
from .prompts import REVIEWER_PROMPT


# Read-only tools the Reviewer may use. Enumerated by name so the SDK's
# static tool check accepts the subagent definition — wildcards would be
# nicer but the runtime rejects them.
_REVIEWER_READONLY_NAMES: tuple[str, ...] = (
    # doc / structure
    "list_documents",
    "get_active_document",
    "list_objects",
    "get_object",
    "get_selection",
    # parameters + memory (read only)
    "get_parameters",
    "read_project_memory",
    "list_decisions",
    "get_active_milestone",
    # verification / inspection
    "verify_sketch",
    "verify_feature",
    "preview_topology",
    "render_view",
)


def _as_mcp_names(bare_names: tuple[str, ...]) -> list[str]:
    """Promote bare tool names to the ``mcp__cad__`` form the SDK expects."""
    registered = set(cad_tools.tool_names())
    out: list[str] = []
    for n in bare_names:
        if n in registered:
            out.append(f"mcp__cad__{n}")
    return out


def reviewer_tool_names() -> list[str]:
    """Full tool names granted to the Reviewer subagent."""
    return _as_mcp_names(_REVIEWER_READONLY_NAMES)


def reviewer_agent() -> AgentDefinition:
    """Build the Reviewer AgentDefinition from the live tool registry.

    The orchestrator invokes this subagent after completing a milestone (or
    at any point the user asks for a design review). It cannot mutate the
    document — its tool set is filtered to read-only operations.
    """
    return AgentDefinition(
        description=(
            "Read-only CAD design reviewer. Invokes verify_feature, "
            "render_view, and topology queries to produce a pass/fail "
            "report on the current document state. Cannot modify geometry."
        ),
        prompt=REVIEWER_PROMPT,
        tools=reviewer_tool_names(),
        permissionMode="default",
    )


def build_subagents() -> dict[str, AgentDefinition]:
    """Return the full subagent map to wire into ClaudeAgentOptions.agents.

    New specialists (Sketcher in Phase 6, Assembler later) plug in here.
    """
    return {
        "reviewer": reviewer_agent(),
    }
