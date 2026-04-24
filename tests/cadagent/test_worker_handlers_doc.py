"""Integration tests for the worker ``doc_inspect`` handler (A3).

These spin up a real ``python -m agent.worker.server`` subprocess via
:class:`WorkerClient` and exercise ``doc_inspect`` against a tempdir
``.FCStd`` created by FreeCAD. Requires a FreeCAD build — skip otherwise.

The debug build at ``build/debug/lib`` is added to the worker's
``PYTHONPATH`` so ``import FreeCAD`` resolves inside the subprocess.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CADAGENT_DIR = REPO_ROOT / "src" / "Mod" / "CADAgent"
FREECAD_LIB = REPO_ROOT / "build" / "debug" / "lib"


def _freecad_available() -> bool:
    return (FREECAD_LIB / "FreeCAD.so").exists()


pytestmark = pytest.mark.skipif(
    not _freecad_available(),
    reason="FreeCAD debug build not present at build/debug/lib — run `pixi run build-debug` first",
)


@pytest.fixture
def worker_env(tmp_path) -> dict[str, str]:
    """Env that makes FreeCAD importable + writable from the worker subprocess."""
    home = tmp_path / ".fc-home"
    (home / ".local" / "share").mkdir(parents=True, exist_ok=True)
    (home / ".config").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    existing = env.get("PYTHONPATH", "")
    # FreeCAD first so ``import FreeCAD`` works; WorkerClient will append
    # the CADAgent dir on top of this.
    env["PYTHONPATH"] = (
        str(FREECAD_LIB) + (os.pathsep + existing if existing else "")
    )
    return env


@pytest.fixture
def sample_fcstd(tmp_path, worker_env) -> Path:
    """Create a .FCStd with a single Part::Box via an out-of-process helper."""
    out = tmp_path / "sample.FCStd"
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(FREECAD_LIB)!r})
        import FreeCAD
        doc = FreeCAD.newDocument("Sample")
        doc.Label = "Sample"
        doc.addObject("Part::Box", "Box1")
        doc.saveAs({str(out)!r})
        """
    )
    subprocess.run(
        [sys.executable, "-c", script],
        env=worker_env,
        check=True,
    )
    assert out.exists()
    return out


@pytest.fixture
def worker_client_module(monkeypatch):
    monkeypatch.syspath_prepend(str(CADAGENT_DIR))
    for name in list(sys.modules):
        if name == "agent.cli.worker_client":
            del sys.modules[name]
    import agent.cli.worker_client as wc  # type: ignore
    return wc


def _run(coro):
    return asyncio.run(coro)


def test_doc_inspect_returns_object_metadata(worker_client_module, sample_fcstd, worker_env):
    wc = worker_client_module

    async def _go():
        client = wc.WorkerClient(env=worker_env)
        await client.start()
        try:
            result = await client.call(
                "doc_inspect", {"doc": str(sample_fcstd)}, timeout=30.0
            )
        finally:
            await client.close()
        return result

    result = _run(_go())
    assert result["path"] == str(sample_fcstd)
    assert result["object_count"] == 1
    assert isinstance(result["dirty"], bool)
    names = [o["name"] for o in result["objects"]]
    assert "Box1" in names
    box = next(o for o in result["objects"] if o["name"] == "Box1")
    assert box["type"] == "Part::Box"
    assert isinstance(box["visible"], bool)


def test_doc_inspect_missing_path_is_error_envelope(worker_client_module, worker_env, tmp_path):
    wc = worker_client_module
    missing = tmp_path / "nope.FCStd"

    async def _go():
        client = wc.WorkerClient(env=worker_env)
        await client.start()
        try:
            with pytest.raises(wc.WorkerError) as ei:
                await client.call("doc_inspect", {"doc": str(missing)}, timeout=10.0)
            # Worker stays healthy after a handler-level failure.
            assert await client.ping() is True
            return str(ei.value)
        finally:
            await client.close()

    msg = _run(_go())
    assert "no such file" in msg or "FileNotFoundError" in msg


def test_doc_inspect_cache_reuses_document(worker_client_module, sample_fcstd, worker_env):
    """Second call on the same path must succeed (cache hit, not a re-open error)."""
    wc = worker_client_module

    async def _go():
        client = wc.WorkerClient(env=worker_env)
        await client.start()
        try:
            r1 = await client.call("doc_inspect", {"doc": str(sample_fcstd)}, timeout=30.0)
            r2 = await client.call("doc_inspect", {"doc": str(sample_fcstd)}, timeout=10.0)
        finally:
            await client.close()
        return r1, r2

    r1, r2 = _run(_go())
    assert r1["object_count"] == r2["object_count"] == 1
    assert r1["name"] == r2["name"]
