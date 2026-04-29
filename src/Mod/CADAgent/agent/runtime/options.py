# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build ``ClaudeAgentOptions`` for the in-FreeCAD agent.

Centralises the options scaffolding so the dock and any future host can
share it. Hooks (PostToolUse auto-probe, Stop verify-gate), MCP server,
agents, system prompt, allowed-tools list, and thinking config all
land here.
"""

from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from .. import tools as agent_tools
from ..prompts_cli import CAD_SYSTEM_PROMPT
from ..subagents import build_agents
from .auto_probe import post_bash_probe
from .stop_gate import stop_gate


def _thinking_kwargs() -> dict[str, Any]:
    """Translate ``CADAGENT_THINKING`` into SDK thinking / effort fields.

    Extended reasoning is verbose and expensive when routed through LiteLLM
    to small models like ``gpt-5-mini`` — default it off. Users who want it
    back can set:

    * ``CADAGENT_THINKING=off``          — disabled (default)
    * ``CADAGENT_THINKING=adaptive``     — model decides per turn
    * ``CADAGENT_THINKING=<int>``        — enabled with that token budget
    * ``CADAGENT_EFFORT=low|medium|high|max`` — optional effort hint
    """
    out: dict[str, Any] = {}
    raw = (os.environ.get("CADAGENT_THINKING") or "").strip().lower()
    if raw in ("", "off", "disabled", "none", "0"):
        out["thinking"] = {"type": "disabled"}
    elif raw == "adaptive":
        out["thinking"] = {"type": "adaptive"}
    else:
        try:
            budget = int(raw)
            if budget > 0:
                out["thinking"] = {"type": "enabled", "budget_tokens": budget}
            else:
                out["thinking"] = {"type": "disabled"}
        except ValueError:
            out["thinking"] = {"type": "disabled"}
    effort = (os.environ.get("CADAGENT_EFFORT") or "").strip().lower()
    if effort in ("low", "medium", "high", "max"):
        out["effort"] = effort
    return out


def build_options(
    *,
    extra_tools: list | None = None,
    extra_allowed_tool_names: list[str] | None = None,
    **overrides: Any,
) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions for the in-FreeCAD agent.

    ``overrides`` lets the dock replace fields like ``permission_mode`` or
    inject ``can_use_tool`` without duplicating the option scaffolding here.
    ``extra_tools`` and ``extra_allowed_tool_names`` let the dock add MCP
    tools that only make sense when running inside FreeCAD (doc inspection /
    creation).
    """
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    os.environ.setdefault("ANTHROPIC_SMALL_FAST_MODEL", model)

    # Build a single MCP server holding every @cad_tool-registered function.
    # In the dock the runtime imports agent.cli.dock_tools at module load,
    # which triggers GUI tool registration before this function runs; in the
    # standalone CLI only the inspect/memory/plan tools are registered.
    # build_server deduplicates so the legacy extra_tools list is harmless.
    server = agent_tools.build_server(name="cad", extra=list(extra_tools or []))

    # SDK built-ins the agent is allowed to use. Deliberately excluding Edit:
    # the agent is supposed to write new .py scripts via Bash heredocs,
    # not edit source files.
    sdk_builtins = [
        "Bash",
        "Read",
        "Grep",
        "Glob",
        "Write",
        "AskUserQuestion",
        "Agent",
        "TodoWrite",
    ]
    # Names of every registered tool (CLI + GUI when imported), plus any
    # legacy extras and the SDK built-ins. dedup keeps the list clean if a
    # caller still passes the GUI names by hand.
    allowed_seen: set[str] = set()
    allowed: list[str] = []
    for n in (
        agent_tools.allowed_tool_names("cad")
        + list(extra_allowed_tool_names or [])
        + sdk_builtins
    ):
        if n in allowed_seen:
            continue
        allowed_seen.add(n)
        allowed.append(n)

    kwargs: dict[str, Any] = dict(
        model=model,
        system_prompt=CAD_SYSTEM_PROMPT,
        mcp_servers={"cad": server},
        allowed_tools=allowed,
        agents=build_agents(model),
        permission_mode=os.environ.get("CADAGENT_PERMS", "bypassPermissions"),
        include_partial_messages=True,
        hooks={
            "PostToolUse": [HookMatcher(matcher="Bash", hooks=[post_bash_probe])],
            "Stop": [HookMatcher(hooks=[stop_gate])],
        },
        **_thinking_kwargs(),
    )
    kwargs.update(overrides)
    return ClaudeAgentOptions(**kwargs)


__all__ = ["build_options"]
