# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stop hook: thin adapter over :class:`AgentLoop`.

Behavior matches pre-Step-13: run the verify gate, persist the table to
the sidecar, block the stop with a structured reason if any row fails,
let the stop through after ``max_iter`` attempts.

The cap state lives in ``AgentLoop`` now; ``GATE_ATTEMPTS_CAP`` is kept
as a module-level constant for tests and external callers.
"""

from __future__ import annotations

import os
import sys

from .. import memory as project_memory
from .. import verify_gate
from ..cli.doc_handle import DocHandle
from ..worker.client import get_shared
from .agent_loop import default_loop
from .auto_probe import active_doc_path


GATE_ATTEMPTS_CAP = 3


async def stop_gate(input_data, tool_use_id, context):  # noqa: ANN001 — SDK callback signature
    path = active_doc_path()
    if not path or not os.path.exists(path):
        return {}
    sys.stderr.write(f"[stop-gate] firing on {path}\n")
    loop = default_loop()
    try:
        client = await get_shared()
        await client.call("doc.open", path=path)
        await client.call("doc.reload")
        decision = await loop.should_continue(client, path)
    except Exception as exc:
        return {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": f"[stop-gate] error: {type(exc).__name__}: {exc}",
            }
        }

    rows = decision.rows or []
    failed = verify_gate.fails(rows)

    try:
        project_memory.write_note(
            DocHandle(path), "open_questions", "completeness_gate",
            verify_gate.format_table(rows)
            + f"\n\n(attempt {decision.iteration}/{decision.max_iter})",
        )
    except Exception as exc:
        sys.stderr.write(f"[stop-gate] persist error: {type(exc).__name__}: {exc}\n")

    if not failed:
        return {}

    if decision.give_up:
        return {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": (
                    f"[stop-gate] cap reached ({decision.iteration}/{decision.max_iter}); "
                    f"{len(failed)} row(s) still FAIL — list them prominently in your final summary, "
                    "do NOT call them 'simplified'.\n"
                    + verify_gate.format_table(rows)
                ),
            }
        }

    table = verify_gate.format_table(rows)
    fails_brief = ", ".join(f"{r['name']} ({r['detail']})" for r in failed)
    reason = (
        f"Stop blocked by completeness gate (attempt {decision.iteration}/{decision.max_iter}). "
        f"{len(failed)} verify row(s) FAIL: {fails_brief}. "
        "Emit a Bash that rebuilds the missing/wrong feature(s) — clean up the prior attempt's "
        "named features first (doc.removeObject) so the geometry doesn't double up. "
        "Then verify_spec / inspect again before declaring done.\n\n"
        + table
    )
    return {"decision": "block", "reason": reason}


__all__ = ["GATE_ATTEMPTS_CAP", "stop_gate"]
