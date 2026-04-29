# SPDX-License-Identifier: LGPL-2.1-or-later
"""Back-compat shim. The Bash-driven CAD Agent system prompt now lives
under :mod:`agent.prompts` (Step 6 of the harness refactor): a single
``core.md`` section assembled by ``build_system_prompt`` until Step 7
carves it into topical files.

Existing call sites still import ``CAD_SYSTEM_PROMPT`` from here; that
constant now reads through the assembler so the file on disk is the
single source of truth.
"""

from __future__ import annotations

from .prompts import build_system_prompt as _build_system_prompt

CAD_SYSTEM_PROMPT, _ = _build_system_prompt()
