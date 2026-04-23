# SPDX-License-Identifier: LGPL-2.1-or-later
"""Specialist subagents for the CAD Agent orchestrator.

Subagents are declared as ``AgentDefinition`` values and attached to the
runtime's ``ClaudeAgentOptions.agents``. The main agent delegates to them
via the SDK's built-in ``Agent`` tool — pass the subagent name + a prompt
and the SDK spins up a fresh conversation with only that subagent's tool
list in scope.

SDK constraints (claude_agent_sdk 0.1.63):

- Subagent invocations run serially inside one ``query()``.
- Subagents do NOT inherit parent conversation memory. The orchestrator
  must pass any relevant decision / milestone context in the Agent-tool
  prompt.
- ``tools=[...]`` is a literal list of full tool names; no wildcards.
- Nested subagents are not supported; stay flat.
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from .prompts import REVIEWER_PROMPT, SKETCHER_PROMPT


# Verb allow-lists per subagent. Each subagent sees the same 10-verb
# surface as the orchestrator; its system prompt scopes it to the
# appropriate kinds. Kind-prefix filtering at the dispatcher level is a
# future enhancement; today, scoping is prompt-enforced.
_REVIEWER_VERB_NAMES: tuple[str, ...] = (
    "cad_inspect", "cad_verify", "cad_render", "cad_memory",
)
_SKETCHER_VERB_NAMES: tuple[str, ...] = (
    "cad_create", "cad_modify", "cad_verify", "cad_inspect", "cad_memory",
)
_ASSEMBLER_VERB_NAMES: tuple[str, ...] = (
    "cad_create", "cad_modify", "cad_delete", "cad_inspect", "cad_verify",
)


def _verb_names(bare: tuple[str, ...]) -> list[str]:
    return [f"mcp__cad__{n}" for n in bare]


_ASSEMBLER_PROMPT = (
    "You are CAD Assembler, embedded in FreeCAD 1.2. Your job is to compose "
    "existing Bodies / Parts into a fully-constrained Assembly using the "
    "cad_create / cad_modify verbs with assembly.* kinds. Follow the "
    "assembly-bottom-up skill: create the assembly, reference each part, "
    "ground one, add joints (fixed / revolute / slider / ball / distance) "
    "until the solver reports DoF=0 for rigid assemblies or the intended "
    "DoF for mechanisms. Return control with one result message summarising "
    "joints added and any unresolved constraints.\n\n"
    "You MUST NOT create new Bodies or new geometry — parts must already "
    "exist. If the brief lists parts that aren't in the document, fail the "
    "turn and ask."
)


def reviewer_agent() -> AgentDefinition:
    return AgentDefinition(
        description=(
            "Read-only CAD design reviewer. Runs cad_verify / cad_inspect / "
            "cad_render / cad_memory to produce a pass-fail report on the "
            "current document. Cannot modify geometry."
        ),
        prompt=REVIEWER_PROMPT,
        tools=_verb_names(_REVIEWER_VERB_NAMES),
        permissionMode="default",
        model="inherit",
    )


def sketcher_agent() -> AgentDefinition:
    return AgentDefinition(
        description=(
            "2D sketch specialist. Creates and constrains sketches inside "
            "the active PartDesign Body until DoF=0. Use when a milestone "
            "needs sketch_from_profile or an add-constraint loop, or when "
            "a pad/pocket just failed due to an underconstrained profile."
        ),
        prompt=SKETCHER_PROMPT,
        tools=_verb_names(_SKETCHER_VERB_NAMES),
        permissionMode="default",
        model="inherit",
    )


def assembler_agent() -> AgentDefinition:
    return AgentDefinition(
        description=(
            "Assembly specialist. Composes existing Bodies into a FreeCAD "
            "Assembly with fixed/revolute/slider/ball/distance joints. Use "
            "when a milestone mentions assembly, joint, or mechanism."
        ),
        prompt=_ASSEMBLER_PROMPT,
        tools=_verb_names(_ASSEMBLER_VERB_NAMES),
        permissionMode="default",
        model="inherit",
    )


def build_subagents() -> dict[str, AgentDefinition]:
    return {
        "reviewer": reviewer_agent(),
        "sketcher": sketcher_agent(),
        "assembler": assembler_agent(),
    }
