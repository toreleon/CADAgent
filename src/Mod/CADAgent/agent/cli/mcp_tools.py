# SPDX-License-Identifier: LGPL-2.1-or-later
"""Back-compat shim. The implementation lives under :mod:`agent.tools`
(``inspect``, ``memory``, ``plan``) since Step 2 of the harness refactor.
This module is deleted at Step 18.
"""

from __future__ import annotations

from ..tools import cli_allowed_tool_names as _cli_allowed_tool_names
from ..tools import cli_tool_funcs as _cli_tool_funcs
from ..tools.inspect import doc_reload, inspect, verify_spec  # noqa: F401
from ..tools.memory import (  # noqa: F401
    memory_decision_record,
    memory_decisions_list,
    memory_note_write,
    memory_parameter_set,
    memory_parameters_get,
    memory_read,
)
from ..tools.plan import (  # noqa: F401
    exit_plan_mode,
    plan_active_get,
    plan_emit,
    plan_milestone_activate,
    plan_milestone_done,
    plan_milestone_failed,
)


TOOL_FUNCS = _cli_tool_funcs()
TOOL_NAMES = [f.name if hasattr(f, "name") else f.__name__ for f in TOOL_FUNCS]


def allowed_tool_names(server_name: str = "cad") -> list[str]:
    """Full MCP tool names with the SDK's ``mcp__<server>__`` prefix."""
    return _cli_allowed_tool_names(server_name)
