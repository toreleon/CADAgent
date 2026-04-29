# SPDX-License-Identifier: LGPL-2.1-or-later
"""Compose the system prompt from versioned ``.md`` sections.

Step 6 keeps the surface tiny: one section file (``core.md``), no
include conditions, no per-mode budgeting. The assembler returns the
file's contents verbatim — we just want the seam in place so Step 7
can split the file without changing the call sites.

The intended mature shape (Step 12):

* per-section ``.md`` files with YAML front-matter declaring ``id``,
  ``include_when``, ``budget_tokens``, ``order``;
* ``PromptHints`` derived from ``Mode`` + active doc + user text +
  attachment kinds;
* selection rules that always include core/etiquette/gates/mode and
  conditionally include cookbook entries;
* a stable cache prefix (core + mode + bash_contract + gates) and a
  variable tail (cookbook + ContextBuilder output).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent
_SECTION_DIR = _PROMPTS_DIR


@dataclass(frozen=True)
class PromptHints:
    """Inputs to ``build_system_prompt`` selection / budgeting.

    Step 6 only stores the inputs; ``build_system_prompt`` ignores them
    until Step 12 wires up ``include_when``. The dataclass exists now
    so call sites can be migrated to pass it through.
    """

    mode: str = "agent"  # placeholder; Mode enum lands at Step 8
    has_active_doc: bool = False
    build_verbs: frozenset[str] = field(default_factory=frozenset)
    has_drawing_attachment: bool = False
    spec_mentions_counts: bool = False
    user_text_preview: str = ""


def _load_section(section_id: str) -> str:
    """Read ``<section_id>.md`` from the prompts dir, raise if missing.

    Subdirs (e.g. ``geometry/obround_slot``) are supported via the
    same separator as the section id.
    """
    path = _SECTION_DIR / f"{section_id}.md"
    return path.read_text(encoding="utf-8")


def build_system_prompt(
    hints: PromptHints | None = None,
    budget: int = 12_000,
) -> tuple[str, list[str]]:
    """Return ``(assembled_prompt, included_section_ids)``.

    Step 6: one section, ``core``, returned verbatim. Hints + budget
    accepted but not used.
    """
    text = _load_section("core")
    return text, ["core"]


__all__ = ["PromptHints", "build_system_prompt"]
