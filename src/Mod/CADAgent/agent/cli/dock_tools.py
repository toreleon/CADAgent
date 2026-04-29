# SPDX-License-Identifier: LGPL-2.1-or-later
"""Back-compat shim. The implementation lives in
:mod:`agent.tools.doc_lifecycle` since Step 2 of the harness refactor.
This module is deleted at Step 18.
"""

from __future__ import annotations

from ..tools.doc_lifecycle import (  # noqa: F401
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
