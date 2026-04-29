# SPDX-License-Identifier: LGPL-2.1-or-later
"""Back-compat shim. ``DockRuntime`` (and its module-level helpers /
imports) moved to :mod:`agent.runtime.dock_runtime` at Step 11 of the
harness refactor; this module is deleted at Step 18.

Tests and callers can still ``from agent.cli.dock_runtime import …``
or ``monkeypatch.setattr(_dr.X, …)``: ``__getattr__`` proxies every
attribute read to the new module.
"""

from __future__ import annotations

from ..runtime import dock_runtime as _dr

DockRuntime = _dr.DockRuntime


def __getattr__(name: str):
    return getattr(_dr, name)
