# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tiny stand-in for a FreeCAD document handle.

The CLI never has a live ``App.Document``; instead, the ``.FCStd`` file path
is the durable identity. ``agent.memory`` only touches two attributes on its
``doc`` argument (``FileName`` and ``Name``), so a plain object with those
fields is indistinguishable from a real doc for sidecar I/O.
"""

from __future__ import annotations

import os


class DocHandle:
    """A ``.FCStd`` path dressed up as a FreeCAD doc, enough for ``agent.memory``.

    The sidecar lives next to the file (``<name>.cadagent.json``). We deliberately
    do not require the .FCStd to exist on disk yet — the agent may register a
    path for a file it's about to create.
    """

    __slots__ = ("FileName", "Name")

    def __init__(self, fcstd_path: str):
        if not fcstd_path:
            raise ValueError("fcstd_path is required")
        # Normalise to an absolute path so the sidecar winds up next to the
        # file regardless of the agent's cwd.
        self.FileName = os.path.abspath(fcstd_path)
        # ``Name`` is used only as a filesystem-safe id for the unsaved-doc
        # fallback, which CLI callers never hit. Provide something sensible
        # anyway in case a future caller relies on it.
        stem = os.path.splitext(os.path.basename(self.FileName))[0]
        self.Name = stem or "Doc"

    def __repr__(self) -> str:
        return f"DocHandle(FileName={self.FileName!r})"
