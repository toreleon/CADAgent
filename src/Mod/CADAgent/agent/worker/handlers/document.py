# SPDX-License-Identifier: LGPL-2.1-or-later
"""Document-level handlers: open, inspect, recompute, close.

State model: the worker holds at most one *current* document at a time,
identified by ``doc.open(path)``. That's enough to kill the "20 cold
FreeCADCmd forks for a 20-part assembly" case — every subsequent
inspect is an in-process attribute read returned over a JSON pipe.

The worker's copy of the doc is a separate ``App.Document`` from the
GUI's. The on-disk ``.FCStd`` remains the source of truth; whoever
writes saves, the other reloads. Keep this purely read-first; writes
land in a later PR.
"""

from __future__ import annotations

from typing import Any, Iterable

import FreeCAD as App  # type: ignore[import-not-found]

from .. import registry


_state: dict[str, Any] = {"doc": None}


def _summary(doc: Any) -> dict[str, Any]:
    return {
        "name": getattr(doc, "Name", "") or "",
        "label": getattr(doc, "Label", "") or "",
        "path": getattr(doc, "FileName", "") or "",
        "object_count": len(getattr(doc, "Objects", []) or []),
    }


def _describe(obj: Any, props: Iterable[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": getattr(obj, "Name", "") or "",
        "label": getattr(obj, "Label", "") or "",
        "type": getattr(obj, "TypeId", "") or "",
    }
    if props:
        data: dict[str, Any] = {}
        for p in props:
            try:
                data[p] = getattr(obj, p)
            except Exception as exc:  # property access can raise inside FreeCAD
                data[p] = f"<error: {type(exc).__name__}: {exc}>"
        out["properties"] = data
    return out


def _require_doc() -> Any:
    doc = _state["doc"]
    if doc is None:
        raise RuntimeError("no document open; call doc.open first")
    return doc


@registry.handler("doc.open")
def doc_open(path: str) -> dict[str, Any]:
    """Open ``path`` (or activate the existing load) and make it current."""
    for d in App.listDocuments().values():
        if (getattr(d, "FileName", "") or "") == path:
            _state["doc"] = d
            return _summary(d)
    doc = App.openDocument(path)
    _state["doc"] = doc
    return _summary(doc)


@registry.handler("doc.current")
def doc_current() -> dict[str, Any] | None:
    doc = _state["doc"]
    return _summary(doc) if doc is not None else None


@registry.handler("doc.close")
def doc_close() -> dict[str, Any]:
    doc = _state["doc"]
    if doc is None:
        return {"closed": False}
    try:
        App.closeDocument(doc.Name)
    finally:
        _state["doc"] = None
    return {"closed": True}


@registry.handler("doc.inspect")
def doc_inspect(
    obj_name: str | None = None,
    props: list[str] | None = None,
) -> dict[str, Any]:
    """Inspect the full tree, or one object by name.

    ``props`` is an optional list of property names to read on each
    object; omit it to get just name/label/type (cheap for large docs).
    """
    doc = _require_doc()
    prop_list = list(props) if props else None
    if obj_name:
        obj = doc.getObject(obj_name)
        if obj is None:
            raise KeyError(f"no such object: {obj_name!r}")
        return {"object": _describe(obj, prop_list)}
    return {
        "document": _summary(doc),
        "objects": [_describe(o, prop_list) for o in doc.Objects],
    }


@registry.handler("doc.recompute")
def doc_recompute() -> dict[str, Any]:
    doc = _require_doc()
    doc.recompute()
    return {"object_count": len(doc.Objects)}
