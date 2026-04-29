# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI-side document state helpers.

Today this module only owns ``reload_active_doc_if_stale`` (used by
``DockRuntime`` between turns). The doc snapshot itself lives in
:mod:`agent.runtime.context_builder` since Step 5; this module re-exports
it so the host package is the single import surface for GUI-thread
helpers. Step 16 adds selection / view-state collection here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..runtime.context_builder import (  # re-export for callers that import host.doc_state.snapshot_active_doc
    ActiveDocSnapshot,
    snapshot_active_doc,
)


@dataclass(frozen=True)
class SelectedObject:
    name: str
    type_name: str
    bbox: tuple[float, float, float] | None  # XLength, YLength, ZLength


@dataclass(frozen=True)
class ViewState:
    has_view: bool
    visible_object_count: int


_MAX_SELECTION = 20
_MAX_SELECTION_BYTES = 2_000


def snapshot_selection() -> list[SelectedObject]:
    """Return up to ``_MAX_SELECTION`` selected objects from the GUI.

    No-op (returns ``[]``) outside of FreeCAD or when no document is
    active. Bounded to ``_MAX_SELECTION_BYTES`` of name characters to
    keep the preamble compact.
    """
    try:
        import FreeCADGui as Gui  # type: ignore
    except ImportError:
        return []
    sel = []
    try:
        raw = Gui.Selection.getSelectionEx()
    except Exception:
        return []
    used = 0
    for entry in raw[:_MAX_SELECTION]:
        try:
            obj = entry.Object
            name = getattr(obj, "Name", "") or ""
            type_name = getattr(obj, "TypeId", "") or obj.__class__.__name__
            bbox: tuple[float, float, float] | None = None
            shape = getattr(obj, "Shape", None)
            if shape is not None:
                bb = getattr(shape, "BoundBox", None)
                if bb is not None:
                    bbox = (
                        float(bb.XLength),
                        float(bb.YLength),
                        float(bb.ZLength),
                    )
            sel.append(SelectedObject(name=name, type_name=type_name, bbox=bbox))
            used += len(name) + len(type_name)
            if used > _MAX_SELECTION_BYTES:
                break
        except Exception:
            continue
    return sel


def snapshot_view_state() -> ViewState | None:
    """Return a tiny ViewState describing the active 3D view.

    Returns ``None`` outside of FreeCAD or when no view is open. Cheap:
    just counts visible objects so the agent can tell if the user is
    focused on a subset.
    """
    try:
        import FreeCADGui as Gui  # type: ignore
    except ImportError:
        return None
    try:
        active_doc = Gui.ActiveDocument
        if active_doc is None:
            return ViewState(has_view=False, visible_object_count=0)
        n_visible = sum(
            1
            for vp in active_doc.Document.Objects
            if getattr(getattr(active_doc.getObject(vp.Name), "ViewObject", None), "Visibility", False)
        )
        return ViewState(has_view=True, visible_object_count=n_visible)
    except Exception:
        return None


def reload_active_doc_if_stale() -> None:
    """Re-open the active document so the GUI reflects subprocess writes.

    The CLI agent writes geometry via ``Bash → FreeCADCmd``, which mutates
    the ``.FCStd`` on disk while the GUI still holds the pre-Bash copy in
    memory. We close + re-open whenever the file's mtime is newer than the
    one we observed before the turn started.
    """
    try:
        import FreeCAD as App  # type: ignore
    except ImportError:
        return

    doc = App.ActiveDocument
    if doc is None:
        return
    path = getattr(doc, "FileName", "") or ""
    if not path or not os.path.exists(path):
        return
    try:
        name = doc.Name
        App.closeDocument(name)
        new_doc = App.openDocument(path)
        App.setActiveDocument(new_doc.Name)
        try:
            new_doc.recompute()
        except Exception:
            pass
    except Exception:
        try:
            doc.recompute()
        except Exception:
            pass


def render_selection_line(sel: list[SelectedObject], view: ViewState | None) -> str:
    """Compact one-liner for the preamble. Empty input → empty string."""
    if not sel and not view:
        return ""
    parts: list[str] = []
    if sel:
        names = []
        for s in sel[:5]:
            if s.bbox:
                names.append(
                    f"{s.name}({s.bbox[0]:.1f}x{s.bbox[1]:.1f}x{s.bbox[2]:.1f})"
                )
            else:
                names.append(s.name)
        more = f" +{len(sel) - 5} more" if len(sel) > 5 else ""
        parts.append(f"selection=[{', '.join(names)}{more}]")
    if view and view.has_view and view.visible_object_count:
        parts.append(f"visible={view.visible_object_count}")
    if not parts:
        return ""
    return "[GUI selection] " + " ".join(parts)


__all__ = [
    "ActiveDocSnapshot",
    "SelectedObject",
    "ViewState",
    "snapshot_active_doc",
    "snapshot_selection",
    "snapshot_view_state",
    "render_selection_line",
    "reload_active_doc_if_stale",
]
