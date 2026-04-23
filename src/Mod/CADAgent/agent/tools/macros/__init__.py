# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tier A macros — intent-level CAD operations.

Each macro composes the primitive Body/Sketch/Pad tools into one-shot,
atomic, guaranteed-valid transactions. They're the agent's preferred path
for common CAD intents like "create a box" or "add corner holes".
"""

from __future__ import annotations

from . import plate, holes


TOOL_FUNCS = plate.TOOL_FUNCS + holes.TOOL_FUNCS
TOOL_NAMES = plate.TOOL_NAMES + holes.TOOL_NAMES


