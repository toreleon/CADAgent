# SPDX-License-Identifier: LGPL-2.1-or-later
"""Plan-mode tools (emit, query, milestone transitions, exit_plan_mode).

Step 1: re-export shim over ``agent.cli.mcp_tools``. Step 2 moves the
implementations here.
"""

from __future__ import annotations

from ..cli.mcp_tools import (
    exit_plan_mode,
    plan_active_get,
    plan_emit,
    plan_milestone_activate,
    plan_milestone_done,
    plan_milestone_failed,
)

__all__ = [
    "exit_plan_mode",
    "plan_active_get",
    "plan_emit",
    "plan_milestone_activate",
    "plan_milestone_done",
    "plan_milestone_failed",
]
