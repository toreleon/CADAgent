# SPDX-License-Identifier: LGPL-2.1-or-later
"""Compose the system prompt from versioned ``.md`` sections.

Step 12 layers ``include_when`` rules on top of the Step-7 always-
include concatenation. Each section can declare a predicate keyed on
:class:`PromptHints`; sections whose predicate returns False are
dropped. With ``hints=None`` (or default-constructed hints), every
section is included so the output is byte-identical to pre-Step-12.

Section order is preserved as a module-level tuple so it can be diffed
in a snapshot test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_PROMPTS_DIR = Path(__file__).resolve().parent


# Document order. Every section is included by default; per-section
# include_when rules below override that for the geometry cookbook
# (only loaded when the user's request mentions the relevant verbs)
# and for the worked_example (Agent mode only).
_DEFAULT_SECTIONS: tuple[str, ...] = (
    "core",
    "bash_contract",
    "conventions/slots",
    "conventions/validity",
    "gates/hard_limits",
    "bash_contract_subsections",
    "invariants",
    "geometry/cookbook_index",
    "geometry/obround_slot",
    "geometry/spherical_dome",
    "geometry/cruciform",
    "geometry/two_view_stackup",
    "conventions/landmines",
    "worked_example",
    "inspect_contract",
    "workflow",
    "error_recipes",
    "when_to_stop",
    "etiquette",
    "modes_legacy",
)


@dataclass(frozen=True)
class PromptHints:
    """Inputs to ``build_system_prompt`` selection / budgeting.

    ``mode`` is currently a string placeholder (``"agent"``, ``"edit"``,
    ``"ask"``). Step 14 swaps it for ``agent.modes.Mode``; the assembler
    treats it as opaque so that swap is invisible here.
    """

    mode: str = "agent"
    has_active_doc: bool = False
    build_verbs: frozenset[str] = field(default_factory=frozenset)
    has_drawing_attachment: bool = False
    spec_mentions_counts: bool = False
    user_text_preview: str = ""

    @classmethod
    def all_in(cls) -> "PromptHints":
        """Hints that pass every include_when rule — used as the back-compat
        default so callers that don't construct hints still see everything."""
        return cls(
            mode="agent",
            has_active_doc=True,
            build_verbs=frozenset({
                "slot", "obround", "dome", "sphere", "cruciform",
                "two_view", "stackup", "flange", "boss",
            }),
            has_drawing_attachment=True,
            spec_mentions_counts=True,
            user_text_preview="",
        )


# include_when rules. Section id → predicate(hints) -> bool.
# Sections without an entry are always included.
_INCLUDE_WHEN: dict[str, Callable[[PromptHints], bool]] = {
    # Geometry cookbook entries: include when the user's prompt mentions
    # the relevant verb. The cookbook index stays so the agent knows the
    # entries exist even if not loaded this turn.
    "geometry/obround_slot": lambda h: bool({"slot", "obround", "keyway"} & h.build_verbs),
    "geometry/spherical_dome": lambda h: bool({"dome", "sphere"} & h.build_verbs),
    "geometry/cruciform": lambda h: bool({"cruciform", "cross"} & h.build_verbs),
    "geometry/two_view_stackup": lambda h: bool(
        {"two_view", "stackup", "flange", "boss"} & h.build_verbs
    ) or h.has_drawing_attachment,
    # Worked example is only useful in Agent mode (Ask doesn't run Bash;
    # Edit is single-shot).
    "worked_example": lambda h: h.mode == "agent",
    # Mode docs section: legacy block kept for everything until Step 14
    # introduces modes/{ask,edit,agent}.md.
}


def _load_section(section_id: str) -> str:
    """Read ``<section_id>.md`` from the prompts dir, raise if missing."""
    return (_PROMPTS_DIR / f"{section_id}.md").read_text(encoding="utf-8")


def _select(hints: PromptHints, sections: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for sid in sections:
        rule = _INCLUDE_WHEN.get(sid)
        if rule is None or rule(hints):
            out.append(sid)
    return out


def build_system_prompt(
    hints: PromptHints | None = None,
    budget: int = 12_000,  # noqa: ARG001 — Step 13/14 wire up budget eviction
    sections: tuple[str, ...] | None = None,
) -> tuple[str, list[str]]:
    """Return ``(assembled_prompt, included_section_ids)``.

    Step 12: filter ``sections`` by ``_INCLUDE_WHEN`` against ``hints``.
    With ``hints=None`` falls back to ``PromptHints.all_in()`` so every
    rule passes — preserves the pre-Step-12 byte-for-byte output.

    ``budget`` is accepted but not enforced yet; Step 13 adds eviction
    when assembled text exceeds the budget (drop lowest-priority cookbook
    pages first, never drop core/mode/gates).
    """
    h = hints if hints is not None else PromptHints.all_in()
    use = sections if sections is not None else _DEFAULT_SECTIONS
    selected = _select(h, use)
    text = "".join(_load_section(s) for s in selected)
    return text, selected


__all__ = ["PromptHints", "build_system_prompt"]
