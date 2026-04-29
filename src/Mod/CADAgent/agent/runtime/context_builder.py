# SPDX-License-Identifier: LGPL-2.1-or-later
"""Per-turn context: doc snapshot, preamble, additionalContext join.

Today's call sites (dock_runtime ``_snapshot_active_doc`` + ``_build_preamble``,
auto_probe / stop_gate hand-assembled ``additionalContext`` strings) move
behind this module so future steps can:

* add selection / view-state injection (Step 16) without touching
  every call site,
* enforce a token budget on the assembled tail without growing the
  hooks (Steps 12 / 13),
* hold the verify-gate feedback table on the next turn's preamble
  (Step 13).

For Step 5 the goal is **byte-identical output** vs the prior inline
implementations. Future steps consolidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActiveDocSnapshot:
    path: str | None
    name: str | None
    label: str | None
    object_count: int

    @classmethod
    def empty(cls) -> "ActiveDocSnapshot":
        return cls(path=None, name=None, label=None, object_count=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "label": self.label,
            "object_count": self.object_count,
        }


@dataclass
class TurnContext:
    """Everything the next turn's preamble + system-prompt tail might pull from.

    Only ``active_doc`` is populated today; later steps fill the rest:

    * ``selection`` / ``view_state`` — Step 16 (GUI-thread snapshot).
    * ``recent_probe`` — Step 5 (PostToolUse caches it here once
      that hook is migrated to the store).
    * ``parameters_sidecar`` — Step 12.
    * ``gate_feedback`` — Step 13 (becomes the agent-loop primitive).
    """

    active_doc: ActiveDocSnapshot = field(default_factory=ActiveDocSnapshot.empty)
    selection: list[Any] = field(default_factory=list)
    view_state: dict | None = None
    recent_probe: dict | None = None
    parameters_sidecar: dict | None = None
    gate_feedback: dict | None = None
    user_text: str = ""
    attachments: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Doc snapshot — moved verbatim from ``cli/dock_runtime.py``.
# Imports FreeCAD lazily so this module stays importable in tests.
# ---------------------------------------------------------------------------


def snapshot_active_doc() -> ActiveDocSnapshot:
    """Save the active doc if dirty and return a small summary.

    Returns the dataclass; callers that want the legacy ``dict`` shape
    use ``.to_dict()`` for byte-compat.
    """
    try:
        import FreeCAD as App  # type: ignore
    except ImportError:
        return ActiveDocSnapshot.empty()

    doc = App.ActiveDocument
    if doc is None:
        return ActiveDocSnapshot.empty()
    path = getattr(doc, "FileName", "") or ""
    if path:
        try:
            doc.save()
        except Exception:
            pass
    return ActiveDocSnapshot(
        path=path or None,
        name=getattr(doc, "Name", "") or None,
        label=getattr(doc, "Label", "") or None,
        object_count=len(getattr(doc, "Objects", []) or []),
    )


def build_preamble(snap: ActiveDocSnapshot | dict) -> str:
    """Wrap user text with one of two GUI-context paragraphs.

    Output is intentionally byte-identical to the original in
    ``dock_runtime._build_preamble``. Accepts either the dataclass or
    the legacy dict shape so the migration is incremental.
    """
    if isinstance(snap, ActiveDocSnapshot):
        path = snap.path
        label = snap.label
        name = snap.name
        object_count = snap.object_count
    else:
        path = (snap or {}).get("path")
        label = (snap or {}).get("label")
        name = (snap or {}).get("name")
        object_count = (snap or {}).get("object_count", 0)

    if path:
        return (
            f"[GUI context] Active FreeCAD document: "
            f"{label or name!r} at {path!r} "
            f"({object_count} objects). Pass this path as "
            f"the ``doc`` argument to ``memory_*`` / ``plan_*`` tools. "
            f"You may also use ``gui_documents_list``, ``gui_open_document``, "
            f"``gui_new_document``, or ``gui_set_active_document`` to work "
            f"on a different file when the request calls for it. The dock "
            f"auto-reloads the active doc in the GUI at end of turn."
        )
    return (
        "[GUI context] No FreeCAD document is open. Use "
        "``gui_new_document`` to create one (returns its on-disk path for "
        "``memory_*`` / ``plan_*`` tools), or ``gui_open_document`` to "
        "open an existing .FCStd. For pure questions or memory work no "
        "document is required."
    )


# ---------------------------------------------------------------------------
# additionalContext join. The PostToolUse + Stop hooks build a list of
# bracket-tagged "pieces" and join with " | "; centralise the join so
# Step 13 can budget / dedupe / re-order without touching every hook.
# ---------------------------------------------------------------------------


def format_additional_context(pieces: list[str]) -> str:
    """Compact join used by PostToolUse / Stop hooks. Empty in -> empty out."""
    return " | ".join(p for p in pieces if p)


__all__ = [
    "ActiveDocSnapshot",
    "TurnContext",
    "snapshot_active_doc",
    "build_preamble",
    "format_additional_context",
]
