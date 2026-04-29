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

from ..runtime.context_builder import (  # re-export for callers that import host.doc_state.snapshot_active_doc
    ActiveDocSnapshot,
    snapshot_active_doc,
)


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


__all__ = [
    "ActiveDocSnapshot",
    "snapshot_active_doc",
    "reload_active_doc_if_stale",
]
