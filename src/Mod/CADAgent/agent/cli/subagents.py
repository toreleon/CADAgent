# SPDX-License-Identifier: LGPL-2.1-or-later
"""Back-compat shim. Subagents moved to :mod:`agent.subagents` at Step
10 of the harness refactor; this module is deleted at Step 18.
"""

from __future__ import annotations

from ..subagents import build_agents  # noqa: F401
