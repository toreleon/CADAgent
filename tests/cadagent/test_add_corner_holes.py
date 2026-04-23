"""Multi-step tool sequencing: agent must add four corner holes to an existing plate.

Fixture is a 50x30x5 padded rectangle. Success criteria:
- Agent calls a hole-creating tool at least once (add_corner_holes macro, or a
  pocket-from-sketch sequence).
- Final topology still contains the original 50x30 footprint but with reduced
  volume (holes removed material).
"""

from __future__ import annotations

import shutil

import pytest

from .replay import run_agent


pytestmark = pytest.mark.live_llm


_HOLE_TOOLS = {
    "mcp__cad__add_corner_holes",
    "mcp__cad__pocket",
    "mcp__cad__add_sketch_geometry",
}


def test_add_corner_holes_reduces_volume(tmp_path, transport_env, pad_on_rect):
    # Copy fixture so the agent can modify it without dirtying the shared copy.
    work_doc = tmp_path / "plate.FCStd"
    shutil.copy(pad_on_rect, work_doc)

    trace = run_agent(
        "The active document has a 50 mm x 30 mm x 5 mm plate. "
        "Add four M6 through-holes, one at each corner, 6 mm in from each edge. "
        "Save the document when done.",
        tmpdir=tmp_path,
        doc=work_doc,
        save_as=work_doc,
        timeout_s=240.0,
    )

    assert not trace.timed_out, f"agent timed out at {trace.elapsed_s:.1f}s"
    assert trace.errors == [], f"panel errors: {trace.errors}"

    called = set(trace.successful_tool_names())
    assert called & _HOLE_TOOLS, (
        f"agent did not invoke any hole-creating tool; called={called}"
    )

    shapes = trace.shape_objects
    assert shapes, "no finite-volume solids after corner-hole operation"

    # The outer plate footprint must survive; find the largest-by-bbox solid
    # and confirm it's still ~50x30 with reduced volume.
    def _fp(o):
        return sorted([o["bbox"]["xlen"], o["bbox"]["ylen"]], reverse=True)

    plates = [s for s in shapes if _fp(s) == pytest.approx([50.0, 30.0], abs=0.5)]
    assert plates, f"no 50x30 plate footprint remaining; footprints={[(s['name'], _fp(s)) for s in shapes]}"
    # PartDesign preserves each feature's pre-op shape in the tree, so look
    # for the *tip* shape — use the minimum-volume plate as the final result.
    final = min(plates, key=lambda s: s["volume"])
    assert final["volume"] < 7500.0 * 0.995, (
        f"plate volume did not decrease (still {final['volume']:.1f}); holes were not cut"
    )
    assert final["is_valid_solid"]
