# SPDX-License-Identifier: LGPL-2.1-or-later
"""Composable system prompt for CAD Agent.

Step 6 lands the assembler around a single ``core.md`` section
containing today's full prompt verbatim. Step 7 carves the prompt into
topical sections; Step 12 makes selection hint-driven and per-mode.
"""

from __future__ import annotations

from .assembler import PromptHints, build_system_prompt

__all__ = ["PromptHints", "build_system_prompt"]
