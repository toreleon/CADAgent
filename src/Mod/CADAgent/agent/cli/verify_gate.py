# SPDX-License-Identifier: LGPL-2.1-or-later
"""Back-compat shim. The verify gate moved to :mod:`agent.verify_gate`
at Step 10 of the harness refactor; this module is deleted at Step 18.
"""

from __future__ import annotations

from ..verify_gate import (  # noqa: F401
    coverage_rows,
    fails,
    format_table,
    rewrite_verify_for_unit,
    run_gate,
)
