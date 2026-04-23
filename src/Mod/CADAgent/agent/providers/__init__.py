# SPDX-License-Identifier: LGPL-2.1-or-later
"""v2 workbench providers — auto-loaded at runtime startup.

Each ``providers/<workbench>.py`` module imports the agent ``registry`` and
calls ``register(...)`` for each operation it exposes. Importing this package
triggers all providers via ``load_all()`` so the registry is fully populated
before the verb tools are constructed.

The order of imports does not matter: the registry detects duplicate
``(verb, kind)`` pairs and raises immediately.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def load_all() -> list[ModuleType]:
    """Import every provider module under this package.

    Returns the list of imported modules, primarily for debugging and tests.
    Provider modules with import-time errors propagate to the caller — a
    broken provider should fail the runtime, not silently disappear.
    """
    loaded: list[ModuleType] = []
    pkg_path = list(__path__)  # type: ignore[name-defined]
    for info in pkgutil.iter_modules(pkg_path):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        loaded.append(mod)
    return loaded


__all__ = ["load_all"]
