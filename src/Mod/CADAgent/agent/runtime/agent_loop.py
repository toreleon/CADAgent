# SPDX-License-Identifier: LGPL-2.1-or-later
"""Agent loop primitive: gate-driven iteration with a hard max_iter cap.

Today's verify gate is implemented as a Stop hook with a module-global
``_gate_attempts`` dict (see ``stop_gate``). This module promotes that
into a class so the cap can become per-DockRuntime (per-session) state
when Step 14+ wires it up, and so the UI can surface "Iteration N/M".

For Step 13 we introduce the class and rewire ``stop_gate`` to call it,
but the cap state still lives in a module-level instance keyed by
doc_path — same observable behavior as before. The class shape is the
contract Step 14+ builds against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import verify_gate


@dataclass
class LoopDecision:
    stop: bool
    reason: str
    give_up: bool = False
    rows: list[dict] = None  # type: ignore[assignment]
    iteration: int = 0
    max_iter: int = 0


class AgentLoop:
    """Encapsulates the stop-blocking verify-gate loop.

    Per-instance state replaces the prior module-global ``_gate_attempts``
    dict. ``max_iter`` is the cap; ``should_continue`` runs the gate, returns
    a decision, and bumps the iteration counter when blocking.
    """

    def __init__(self, max_iter: int = 3):
        self.max_iter = max_iter
        # Per-doc iteration counter (shared across sessions in the legacy
        # model). Step 14 hangs an instance off DockRuntime and keys per
        # session instead.
        self._iter: dict[str, int] = {}

    def reset(self, doc_path: str | None = None) -> None:
        """Reset the iteration counter for one doc, or all docs."""
        if doc_path is None:
            self._iter.clear()
        else:
            self._iter.pop(doc_path, None)

    def attempts(self, doc_path: str) -> int:
        return self._iter.get(doc_path, 0)

    async def should_continue(self, client, doc_path: str) -> LoopDecision:
        """Run the gate against ``doc_path`` and return a LoopDecision.

        Side effect: increments the per-doc iteration counter when blocking
        (so ``attempts(doc_path)`` reflects the count).

        Caller (the Stop hook adapter) handles SDK-level "block" vs "allow"
        translation; this method only knows about the loop primitive.
        """
        rows = await verify_gate.run_gate(client, doc_path)
        rows.extend(verify_gate.coverage_rows(doc_path))
        failed = verify_gate.fails(rows)
        attempts = self._iter.get(doc_path, 0)

        if not failed:
            return LoopDecision(
                stop=True,
                reason="all checks pass",
                rows=rows,
                iteration=attempts,
                max_iter=self.max_iter,
            )

        if attempts >= self.max_iter:
            return LoopDecision(
                stop=True,
                give_up=True,
                reason=verify_gate.format_table(rows),
                rows=rows,
                iteration=attempts,
                max_iter=self.max_iter,
            )

        self._iter[doc_path] = attempts + 1
        return LoopDecision(
            stop=False,
            reason=verify_gate.format_table(rows),
            rows=rows,
            iteration=attempts + 1,
            max_iter=self.max_iter,
        )


# Module-default loop, used by the legacy stop_gate adapter. Step 14+ moves
# the instance onto DockRuntime so per-session state lands in the right
# place (and rewinds clear it).
_DEFAULT_LOOP = AgentLoop(max_iter=3)


def default_loop() -> AgentLoop:
    return _DEFAULT_LOOP


__all__ = ["AgentLoop", "LoopDecision", "default_loop"]
