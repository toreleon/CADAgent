# SPDX-License-Identifier: LGPL-2.1-or-later
"""Document-level handlers for the CAD worker.

Reference implementation for Phase-B verb-tools. Exposes ``doc_inspect`` —
the first handler that actually touches FreeCAD. The worker caches opened
``App.Document`` instances by absolute path so subsequent calls reuse state
instead of re-parsing the ``.FCStd``.

FreeCAD is imported lazily at call time: the worker process is long-lived,
and we don't want ``import agent.worker.server`` on its own to drag in all
of FreeCAD for tests that never touch geometry.
"""

from __future__ import annotations

import os
from typing import Any

from ..registry import handler


# Module-level cache keyed by absolute .FCStd path. Future handlers (B1..B5)
# will share this — if the surface grows, promote to `handlers/_doc_cache.py`.
_DOC_CACHE: dict[str, Any] = {}


def _resolve_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("'doc' is required: absolute path to the .FCStd file")
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"no such file: {abs_path}")
    return abs_path


def _open_or_reuse(abs_path: str):
    import FreeCAD as App  # lazy — only when actually inspecting

    cached = _DOC_CACHE.get(abs_path)
    if cached is not None:
        # Guard against the doc having been closed out from under us.
        try:
            # Accessing .Name on a closed doc raises; this is a cheap probe.
            _ = cached.Name
            return cached
        except Exception:
            _DOC_CACHE.pop(abs_path, None)

    doc = App.openDocument(abs_path)
    _DOC_CACHE[abs_path] = doc
    return doc


def _visibility(obj) -> bool:
    """Best-effort visibility without requiring the GUI.

    Headless FreeCAD exposes ``.Visibility`` on most App-level objects; when
    it's missing we assume visible (matches the GUI default).
    """
    return bool(getattr(obj, "Visibility", True))


@handler("doc_inspect")
def doc_inspect(doc: str, include_hidden: bool = True) -> dict[str, Any]:
    """Inspect a .FCStd: document metadata + object list.

    Parameters
    ----------
    doc:
        Absolute path to the ``.FCStd`` file. Opened once and cached.
    include_hidden:
        When False, skip objects whose ``Visibility`` is False.

    Returns the payload documented in the A3 spec: ``path``, ``name``,
    ``label``, ``dirty``, ``object_count``, and an ``objects`` list of
    ``{name, label, type, visible}`` entries.
    """
    abs_path = _resolve_path(doc)
    document = _open_or_reuse(abs_path)

    objects_out: list[dict[str, Any]] = []
    for obj in document.Objects:
        visible = _visibility(obj)
        if not include_hidden and not visible:
            continue
        objects_out.append(
            {
                "name": obj.Name,
                "label": obj.Label,
                "type": obj.TypeId,
                "visible": visible,
            }
        )

    return {
        "path": abs_path,
        "name": document.Name,
        "label": document.Label,
        "dirty": bool(getattr(document, "Modified", False)),
        "object_count": len(document.Objects),
        "objects": objects_out,
    }
