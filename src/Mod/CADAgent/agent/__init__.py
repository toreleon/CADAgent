# SPDX-License-Identifier: LGPL-2.1-or-later
"""CAD Agent package — runtime, UI, and MCP tool implementations."""

from __future__ import annotations

import sys as _sys

# FreeCAD's GUI replaces sys.stderr with a C++-backed stream whose __class__
# attribute isn't introspectable the way @dataclass(f.default.__class__) needs.
# claude_agent_sdk's ClaudeAgentOptions defaults `debug_stderr = sys.stderr`
# at import time, so importing it under FreeCAD blows up with AttributeError:
# __class__. Warm-import the SDK once here with the original stream restored
# so every subsequent `from claude_agent_sdk import ...` hits sys.modules.
_saved_stderr = _sys.stderr
try:
    _sys.stderr = _sys.__stderr__ or _sys.stdout
    import claude_agent_sdk as _claude_agent_sdk  # noqa: F401
finally:
    _sys.stderr = _saved_stderr
