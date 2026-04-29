# SPDX-License-Identifier: LGPL-2.1-or-later
"""First-class agent modes — Ask, Edit, Agent.

Today's UX is built on the SDK's four ``permission_mode`` strings
(``default``, ``acceptEdits``, ``bypassPermissions``, ``plan``). This
module introduces a product-shaped enum on top of that:

* ``Mode.ASK``   — chat / inspect only; no Bash, no doc mutation.
                   Subsumes today's ``plan``.
* ``Mode.EDIT``  — single mutating tool call per turn, with preview.
                   Brand-new mode (lands UX-side at Step 15).
* ``Mode.AGENT`` — autonomous loop with the verify-gate as terminator.
                   Subsumes ``default`` / ``acceptEdits`` /
                   ``bypassPermissions``, with an ``auto_approve`` flag.

A ``ModePolicy`` bundles the mode with the tool-allowlist derivation,
auto-approve flags, and iteration cap. Step 8 only adds the types and a
mapping table to/from the SDK strings so behavior stays identical;
Steps 14–16 promote ``Mode`` to a first-class UX concept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Mode(str, Enum):
    ASK = "ask"
    EDIT = "edit"
    AGENT = "agent"


AutoApprove = Literal["none", "edits", "all"]


@dataclass(frozen=True)
class ModePolicy:
    """How a mode should constrain tool execution.

    * ``tool_allowlist`` — full MCP names of tools allowed in this mode.
      Empty set means "no extra restriction beyond the SDK allowlist."
      Consumed by ``permissions.make_can_use_tool``.
    * ``auto_allow_edits`` — auto-allow file-edit tools without a prompt.
      Today's ``acceptEdits`` semantics.
    * ``auto_allow_all`` — auto-allow every tool without a prompt.
      Today's ``bypassPermissions`` semantics.
    * ``require_preview`` — show the EditApprovalRow with a dry-run diff
      before the single mutating call. Edit-mode only (Step 15).
    * ``max_iterations`` — agent-loop cap. Ask=0 (no execution),
      Edit=1 (single mutation), Agent=N (Step 13's AgentLoop).
    """

    mode: Mode
    tool_allowlist: frozenset[str] = field(default_factory=frozenset)
    auto_allow_edits: bool = False
    auto_allow_all: bool = False
    require_preview: bool = False
    max_iterations: int = 3


# ---------------------------------------------------------------------------
# Mapping today's SDK permission_mode strings <-> Mode + flags.
#
# This is the back-compat layer. The runtime still threads
# ``permission_mode`` strings into ``ClaudeAgentOptions``; ``make_can_use_tool``
# can accept either a string (legacy) or a ``ModePolicy`` (new). When Step
# 14 promotes Mode to a UX concept, the mapping inverts and the SDK string
# becomes a derived value.
# ---------------------------------------------------------------------------


def policy_from_permission_mode(s: str | None) -> ModePolicy:
    """Translate today's SDK permission_mode string to a ModePolicy.

    Mapping table (preserves today's semantics 1:1):

    * ``"plan"``               → Ask
    * ``"default"``            → Agent + auto_approve=none
    * ``"acceptEdits"``        → Agent + auto_approve=edits
    * ``"bypassPermissions"``  → Agent + auto_approve=all
    * anything else / None     → Agent + auto_approve=none
    """
    s = (s or "").strip()
    if s == "plan":
        return ModePolicy(mode=Mode.ASK, max_iterations=0)
    if s == "acceptEdits":
        return ModePolicy(mode=Mode.AGENT, auto_allow_edits=True, max_iterations=3)
    if s == "bypassPermissions":
        return ModePolicy(
            mode=Mode.AGENT,
            auto_allow_edits=True,
            auto_allow_all=True,
            max_iterations=3,
        )
    return ModePolicy(mode=Mode.AGENT, max_iterations=3)


def permission_mode_from_policy(policy: ModePolicy) -> str:
    """Inverse mapping. Used by the runtime when constructing
    ``ClaudeAgentOptions(permission_mode=...)``."""
    if policy.mode is Mode.ASK:
        return "plan"
    if policy.mode is Mode.EDIT:
        # Edit mode wraps the SDK's default behavior with our own one-mutation
        # cap (Step 15). The SDK only sees "default" — our can_use_tool
        # callback enforces the rest.
        return "default"
    # AGENT
    if policy.auto_allow_all:
        return "bypassPermissions"
    if policy.auto_allow_edits:
        return "acceptEdits"
    return "default"


def derive_auto_approve(policy: ModePolicy) -> AutoApprove:
    if policy.auto_allow_all:
        return "all"
    if policy.auto_allow_edits:
        return "edits"
    return "none"


# ---------------------------------------------------------------------------
# Mode → tool-allowlist derivation (used by Step 14 onward).
#
# The allowlist is built from ``agent.tools.categories``; ASK gets only
# READ + INSPECT, EDIT gets read + selected mutators, AGENT gets the full
# surface. permissions.MUTATING_TOOLS / FILE_EDIT_TOOLS / READ_ONLY_TOOLS
# are still the substrate for the ``can_use_tool`` decision; the policy's
# ``tool_allowlist`` is the SDK-level pre-filter.
# ---------------------------------------------------------------------------


def tool_allowlist_for(mode: Mode) -> frozenset[str]:
    """Tools the SDK should expose to the model in this mode.

    Step 8 returns an empty set so behavior stays identical to today
    (the SDK allowlist remains as built by ``cli/runtime.build_options``).
    Step 14 / 15 fill this in to enforce ASK / EDIT semantics at the
    SDK level.
    """
    return frozenset()


__all__ = [
    "AutoApprove",
    "Mode",
    "ModePolicy",
    "derive_auto_approve",
    "permission_mode_from_policy",
    "policy_from_permission_mode",
    "tool_allowlist_for",
]
