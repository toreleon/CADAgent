# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI / FreeCAD document lifecycle tools.

Step 1: re-export shim over ``agent.cli.dock_tools``. Step 2 moves the
implementations here.
"""

from __future__ import annotations

from ..cli.dock_tools import (
    TOOL_FUNCS,
    TOOL_NAMES,
    allowed_tool_names,
    gui_active_document,
    gui_documents_list,
    gui_inspect_live,
    gui_new_document,
    gui_open_document,
    gui_reload_active_document,
    gui_set_active_document,
)

__all__ = [
    "TOOL_FUNCS",
    "TOOL_NAMES",
    "allowed_tool_names",
    "gui_active_document",
    "gui_documents_list",
    "gui_inspect_live",
    "gui_new_document",
    "gui_open_document",
    "gui_reload_active_document",
    "gui_set_active_document",
]
