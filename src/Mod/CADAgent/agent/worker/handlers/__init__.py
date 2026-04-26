# SPDX-License-Identifier: LGPL-2.1-or-later
"""Worker-side FreeCAD handlers.

Importing this package triggers ``@handler`` registration side effects on
the server's dispatch table. The bootstrap in :mod:`agent.worker.client`
imports this package before calling :func:`agent.worker.server.main`.
"""

from __future__ import annotations

from . import document  # noqa: F401  -- import for side effects
from . import inspect  # noqa: F401  -- import for side effects

__all__ = ["document", "inspect"]
