# SPDX-License-Identifier: LGPL-2.1-or-later
"""Integration tests for the worker-side ``inspect.query`` DSL.

Boot a real ``WorkerClient`` against ``FreeCADCmd``, build small fixture
documents on the fly, and assert the structured query results match
closed-form geometry. Skipped when ``FreeCADCmd`` isn't available so the
suite still runs in environments without a built FreeCAD.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _freecadcmd_path() -> str | None:
    env = os.environ.get("CADAGENT_FREECADCMD")
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    found = shutil.which("FreeCADCmd")
    if found:
        return found
    # Walk up from this file looking for build/debug/bin/FreeCADCmd
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "build" / "debug" / "bin" / "FreeCADCmd"
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


_FC = _freecadcmd_path()
pytestmark = pytest.mark.skipif(_FC is None, reason="FreeCADCmd not available")


_BUILD_BOX_TPL = r"""
import FreeCAD, Part, os, sys, traceback
try:
    out = os.environ.get("FC_OUT")
    if not out:
        raise SystemExit("missing FC_OUT env")
    doc = FreeCAD.newDocument("Box")
    box = Part.makeBox({W}, {H}, {D})
    {EXTRA}
    feat = doc.addObject("Part::Feature", "Body")
    feat.Shape = box
    doc.recompute()
    doc.saveAs(out)
except BaseException as e:
    sys.stderr.write("ERR: " + repr(e) + "\n" + traceback.format_exc())
    sys.exit(1)
"""


def _build_doc(tmp_path: Path, name: str, *, w: float = 30, h: float = 20, d: float = 5, extra: str = "") -> Path:
    """Run a FreeCADCmd subprocess that writes ``name.FCStd`` and returns the path."""
    out = tmp_path / f"{name}.FCStd"
    script = tmp_path / f"{name}.py"
    script.write_text(_BUILD_BOX_TPL.format(W=w, H=h, D=d, EXTRA=extra))
    home = tmp_path / "fc-home"
    (home / ".local" / "share").mkdir(parents=True, exist_ok=True)
    (home / ".config").mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "FC_OUT": str(out),
    }
    subprocess.run([_FC, str(script)], check=True, capture_output=True, env=env, timeout=60)
    assert out.exists(), f"FreeCADCmd did not produce {out}"
    return out


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def worker(event_loop):
    """Boot one WorkerClient for the whole module so we don't pay cold-start per test."""
    from agent.worker.client import WorkerClient

    client = WorkerClient(executable=_FC)

    async def _start():
        await client.start()
        return client

    event_loop.run_until_complete(_start())
    try:
        yield client
    finally:
        event_loop.run_until_complete(client.close())


def _call(loop, worker, method, **params):
    return loop.run_until_complete(worker.call(method, **params))


def test_bbox_box(tmp_path, event_loop, worker):
    doc = _build_doc(tmp_path, "plain", w=30, h=20, d=5)
    _call(event_loop, worker, "doc.open", path=str(doc))
    r = _call(event_loop, worker, "inspect.query", query="bbox")
    size = r["result"]["size"]
    assert size == pytest.approx([30.0, 20.0, 5.0], abs=1e-6)


def test_face_types_box(tmp_path, event_loop, worker):
    doc = _build_doc(tmp_path, "ftypes", w=10, h=10, d=10)
    _call(event_loop, worker, "doc.open", path=str(doc))
    r = _call(event_loop, worker, "inspect.query", query="face_types")
    counts = r["result"]["counts"]
    assert counts.get("Plane") == 6
    assert r["result"]["total_faces"] == 6


def test_solids_box(tmp_path, event_loop, worker):
    doc = _build_doc(tmp_path, "solid", w=20, h=10, d=4)
    _call(event_loop, worker, "doc.open", path=str(doc))
    r = _call(event_loop, worker, "inspect.query", query="solids")
    items = r["result"]["items"]
    assert len(items) == 1
    s = items[0]
    assert s["isValid"] is True
    assert s["n_solids"] == 1
    assert s["n_faces"] == 6
    assert s["volume"] == pytest.approx(800.0, rel=1e-6)


def test_holes_through_plate(tmp_path, event_loop, worker):
    extra = (
        "hole = Part.makeCylinder(3, 5, FreeCAD.Vector(15, 10, 0))\n"
        "    box = box.cut(hole)\n"
    )
    doc = _build_doc(tmp_path, "drilled", w=30, h=20, d=5, extra=extra)
    _call(event_loop, worker, "doc.open", path=str(doc))
    r = _call(event_loop, worker, "inspect.query", query="holes diameter=6")
    items = r["result"]["items"]
    assert r["result"]["count"] >= 1
    assert any(abs(it["diameter"] - 6.0) < 0.1 for it in items)


def test_probe_one_call(tmp_path, event_loop, worker):
    doc = _build_doc(tmp_path, "probe", w=12, h=8, d=4)
    _call(event_loop, worker, "doc.open", path=str(doc))
    p = _call(event_loop, worker, "inspect.probe")
    assert "bbox" in p and "face_types" in p and "solids" in p
    assert p["solids"]["items"][0]["isValid"] is True


def test_unknown_kind_raises(tmp_path, event_loop, worker):
    doc = _build_doc(tmp_path, "unk", w=5, h=5, d=5)
    _call(event_loop, worker, "doc.open", path=str(doc))
    from agent.worker.client import WorkerError

    with pytest.raises(WorkerError):
        _call(event_loop, worker, "inspect.query", query="not_a_real_kind")
