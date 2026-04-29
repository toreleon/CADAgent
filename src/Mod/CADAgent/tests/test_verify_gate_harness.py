# SPDX-License-Identifier: LGPL-2.1-or-later
"""Regression tests for the harness fixes layered on the verify gate.

Three independent failure modes used to slip past the gate:

* The ``inch → mm`` rewriter applied a ``val < 10 ⇒ inches`` magnitude
  fallback that double-converted already-mm values
  (``3.556 mm → 90.32 mm``) when the model wrote raw mm but tagged the
  parameter ``unit="in"``.
* The worker's JSON-RPC server caught every ``KeyError`` from
  ``registry.dispatch`` as "unknown method", so a handler raising
  ``KeyError("no object 'flange'")`` looked like the method itself was
  missing — masking real verify failures.
* The model could descope features by editing
  ``design_intent.spec_from_drawing`` after the coverage check had
  already scanned it, dropping ``32×R0.09`` patterns to silence the
  gate. ``write_note`` now snapshots the first write to
  ``spec_from_drawing_initial`` and the gate reads from that.
"""
from __future__ import annotations

import asyncio

import pytest


# ---------------------------------------------------------------------------
# rewriter: no magnitude-based double-conversion
# ---------------------------------------------------------------------------


def test_rewriter_converts_when_query_matches_param_value():
    """Model wrote raw inches in the query — convert to mm."""
    from agent.verify_gate import rewrite_verify_for_unit

    out = rewrite_verify_for_unit("holes diameter=0.14 axis=z", "in", 0.14)
    assert out == "holes diameter=3.556 axis=z"


def test_rewriter_leaves_pre_converted_mm_alone():
    """Regression: model pre-converted to mm but tagged unit='in'.

    The query numeric (3.556) does not match param_value (0.14), so the
    rewriter must leave it alone — the old ``val < 10`` fallback would
    have produced ``90.3224``, which then matches no real geometry."""
    from agent.verify_gate import rewrite_verify_for_unit

    out = rewrite_verify_for_unit("holes diameter=3.556 axis=z", "in", 0.14)
    assert out == "holes diameter=3.556 axis=z"


def test_rewriter_noop_when_param_value_absent():
    """Without a param_value anchor the rewriter cannot tell pre-converted
    mm from raw inches, so it must leave the query alone."""
    from agent.verify_gate import rewrite_verify_for_unit

    out = rewrite_verify_for_unit("holes diameter=3.556 axis=z", "in", None)
    assert out == "holes diameter=3.556 axis=z"


def test_rewriter_noop_for_mm_unit():
    from agent.verify_gate import rewrite_verify_for_unit

    out = rewrite_verify_for_unit("holes diameter=3.556 axis=z", "mm", 3.556)
    assert out == "holes diameter=3.556 axis=z"


def test_rewriter_skips_axis_and_tol():
    """``axis=…`` / ``tol=…`` are not lengths and must never be rewritten."""
    from agent.verify_gate import rewrite_verify_for_unit

    out = rewrite_verify_for_unit(
        "holes diameter=0.14 axis=z tol=0.5", "in", 0.14
    )
    assert out == "holes diameter=3.556 axis=z tol=0.5"


# ---------------------------------------------------------------------------
# registry: UnknownMethod is distinct from handler KeyError
# ---------------------------------------------------------------------------


def test_registry_unknown_method_raises_distinct_exception():
    """A missing method must raise ``UnknownMethod``, not a bare KeyError."""
    from agent.worker import registry

    async def go():
        with pytest.raises(registry.UnknownMethod):
            await registry.dispatch("does.not.exist", {})

    asyncio.run(go())


def test_registry_handler_keyerror_propagates_as_keyerror():
    """A handler that raises KeyError (e.g. "no such object") must
    propagate unchanged so the server reports it as a handler error,
    not as "unknown method"."""
    from agent.worker import registry

    @registry.handler("test.raise_keyerror")
    def _raise(name: str = ""):
        raise KeyError(f"no such object: {name!r}")

    async def go():
        try:
            with pytest.raises(KeyError) as exc_info:
                await registry.dispatch("test.raise_keyerror", {"name": "boss"})
            assert not isinstance(exc_info.value, registry.UnknownMethod)
            assert "boss" in str(exc_info.value)
        finally:
            registry._HANDLERS.pop("test.raise_keyerror", None)

    asyncio.run(go())


# ---------------------------------------------------------------------------
# memory: spec_from_drawing snapshot is locked on first write
# ---------------------------------------------------------------------------


def test_spec_from_drawing_locked_on_first_write(fake_doc):
    """The first write to design_intent.spec_from_drawing also populates
    spec_from_drawing_initial. A second write replaces the editable copy
    but leaves the locked snapshot untouched — so the coverage check
    sees the original ``N×`` patterns even if the model edits them out."""
    from agent import memory

    initial = "Plate 3.94×3.94. 12×Ø0.14 mounting holes. 32×R0.09 small rounds."
    memory.write_note(fake_doc, "design_intent", "spec_from_drawing", initial)

    data = memory.load(fake_doc)
    assert data["design_intent"]["spec_from_drawing"] == initial
    assert data["design_intent"]["spec_from_drawing_initial"] == initial

    # Second write — the model "fixes" the spec by removing the 32× count.
    edited = "Plate 3.94×3.94. 12×Ø0.14 mounting holes."
    memory.write_note(fake_doc, "design_intent", "spec_from_drawing", edited)

    data = memory.load(fake_doc)
    assert data["design_intent"]["spec_from_drawing"] == edited
    # Snapshot is preserved — it locks on first write only.
    assert data["design_intent"]["spec_from_drawing_initial"] == initial


def test_coverage_rows_uses_locked_spec(fake_doc):
    """coverage_rows must read from spec_from_drawing_initial when present
    so the model can't silence the gate by editing the live spec text."""
    from agent import memory
    from agent import verify_gate

    initial = "Plate. 12×Ø0.14 mounting holes. 32×R0.09 rounds."
    memory.write_note(fake_doc, "design_intent", "spec_from_drawing", initial)
    # Model "descopes" the 32× count by overwriting the live spec.
    memory.write_note(
        fake_doc, "design_intent", "spec_from_drawing",
        "Plate. 12×Ø0.14 mounting holes.",
    )

    rows = verify_gate.coverage_rows(fake_doc.FileName)
    names = {r["name"] for r in rows if r["status"] == "fail"}
    # Both 12× and 32× should be flagged because no count_* parameters
    # exist; the locked spec keeps 32 visible even though the live spec
    # no longer mentions it.
    assert "<spec count 12>" in names
    assert "<spec count 32>" in names
