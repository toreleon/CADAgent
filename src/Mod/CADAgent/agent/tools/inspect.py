# SPDX-License-Identifier: LGPL-2.1-or-later
"""Worker-backed inspection tools (geometry probe, verify-DSL, reload).

Step 1: re-export shim over ``agent.cli.mcp_tools``. Step 2 moves the
implementations here. The bare names ``inspect`` / ``verify_spec`` are
preserved verbatim; renaming to ``inspect_probe`` / ``inspect_verify``
happens at Step 4 when the ``@cad_tool`` decorator lands.
"""

from __future__ import annotations

from ..cli.mcp_tools import doc_reload, inspect, verify_spec

__all__ = ["doc_reload", "inspect", "verify_spec"]
