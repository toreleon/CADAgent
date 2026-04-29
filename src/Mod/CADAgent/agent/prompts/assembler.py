# SPDX-License-Identifier: LGPL-2.1-or-later
"""Compose the system prompt from versioned ``.md`` sections.

Step 7 carves the prompt into topical files (``core``, ``bash_contract``,
``conventions/slots``, …). The assembler concatenates them in a fixed
order whose output is byte-identical to the pre-Step-7 single
``CAD_SYSTEM_PROMPT`` string. Step 12 layers ``include_when`` rules on
top so cookbook entries become hint-driven and per-mode budgets kick in.

Section order is preserved as a module-level tuple so it can be diffed
in a snapshot test (``test_prompt_assembler.py``, planned for Step 12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


# Document order. Every section is currently always-included; Step 12
# replaces this with a policy table keyed on PromptHints.
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

    Step 7: ``build_system_prompt`` ignores hints entirely. Step 12 wires
    them up to ``include_when`` rules.
    """

    mode: str = "agent"  # placeholder; Mode enum lands at Step 8
    has_active_doc: bool = False
    build_verbs: frozenset[str] = field(default_factory=frozenset)
    has_drawing_attachment: bool = False
    spec_mentions_counts: bool = False
    user_text_preview: str = ""


def _load_section(section_id: str) -> str:
    """Read ``<section_id>.md`` from the prompts dir, raise if missing."""
    return (_PROMPTS_DIR / f"{section_id}.md").read_text(encoding="utf-8")


def build_system_prompt(
    hints: PromptHints | None = None,
    budget: int = 12_000,
    sections: tuple[str, ...] | None = None,
) -> tuple[str, list[str]]:
    """Return ``(assembled_prompt, included_section_ids)``.

    Step 7: concatenate ``sections`` (default: every section in document
    order) verbatim. Output equals the pre-refactor ``CAD_SYSTEM_PROMPT``
    string byte-for-byte.
    """
    use = sections if sections is not None else _DEFAULT_SECTIONS
    text = "".join(_load_section(s) for s in use)
    return text, list(use)


__all__ = ["PromptHints", "build_system_prompt"]
