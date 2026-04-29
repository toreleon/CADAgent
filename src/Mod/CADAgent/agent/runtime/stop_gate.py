# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stop hook: harness-level enforcement of the spec contract.

The model used to omit features ("simplified for robustness"), claim
PASS, and exit. Prose can describe the gate; only code can refuse the
stop. This hook fires when the SDK reports the agent is about to stop.
We run every parameter's verify query through the worker, and if any
fail, we return ``decision="block"`` with the failed rows in the
reason — the SDK routes that back as a tool result and the model gets
another turn.

Cap at 3 stop-blocks per session so we don't loop indefinitely on a
verify query the geometry can never satisfy. Step 13 promotes this from
a Stop-hook special case to ``runtime.agent_loop.AgentLoop`` and per-
session state replaces the module-global ``_gate_attempts``.
"""

from __future__ import annotations

import os
import sys

from .. import memory as project_memory
from .. import verify_gate
from ..cli.doc_handle import DocHandle
from ..worker.client import get_shared
from .auto_probe import active_doc_path


GATE_ATTEMPTS_CAP = 3
_gate_attempts: dict[str, int] = {}


async def stop_gate(input_data, tool_use_id, context):  # noqa: ANN001 — SDK callback signature
    path = active_doc_path()
    if not path or not os.path.exists(path):
        return {}
    sys.stderr.write(f"[stop-gate] firing on {path}\n")
    try:
        client = await get_shared()
        await client.call("doc.open", path=path)
        await client.call("doc.reload")
        rows = await verify_gate.run_gate(client, path)
        rows.extend(verify_gate.coverage_rows(path))
    except Exception as exc:
        return {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": f"[stop-gate] error: {type(exc).__name__}: {exc}",
            }
        }

    failed = verify_gate.fails(rows)
    attempts = _gate_attempts.get(path, 0)

    try:
        project_memory.write_note(
            DocHandle(path), "open_questions", "completeness_gate",
            verify_gate.format_table(rows) + f"\n\n(attempt {attempts + 1}/{GATE_ATTEMPTS_CAP})",
        )
    except Exception as exc:
        sys.stderr.write(f"[stop-gate] persist error: {type(exc).__name__}: {exc}\n")

    if not failed:
        return {}

    if attempts >= GATE_ATTEMPTS_CAP:
        return {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": (
                    f"[stop-gate] cap reached ({attempts}/{GATE_ATTEMPTS_CAP}); "
                    f"{len(failed)} row(s) still FAIL — list them prominently in your final summary, "
                    "do NOT call them 'simplified'.\n"
                    + verify_gate.format_table(rows)
                ),
            }
        }

    _gate_attempts[path] = attempts + 1
    table = verify_gate.format_table(rows)
    fails_brief = ", ".join(f"{r['name']} ({r['detail']})" for r in failed)
    reason = (
        f"Stop blocked by completeness gate (attempt {attempts + 1}/{GATE_ATTEMPTS_CAP}). "
        f"{len(failed)} verify row(s) FAIL: {fails_brief}. "
        "Emit a Bash that rebuilds the missing/wrong feature(s) — clean up the prior attempt's "
        "named features first (doc.removeObject) so the geometry doesn't double up. "
        "Then verify_spec / inspect again before declaring done.\n\n"
        + table
    )
    return {"decision": "block", "reason": reason}


__all__ = ["GATE_ATTEMPTS_CAP", "stop_gate"]
