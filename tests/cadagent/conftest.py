"""Pytest fixtures for CADAgent live-LLM tests.

Tests in this package make real calls to the configured proxy, so we gate
them behind the ``live_llm`` marker. To run:

    pytest tests/cadagent -m live_llm

Required env vars (or a parent has them exported):
    ANTHROPIC_BASE_URL   e.g. http://localhost:4141
    ANTHROPIC_API_KEY    any non-empty string for self-hosted proxies
    ANTHROPIC_MODEL      e.g. gpt-5-mini
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FREECADCMD = REPO_ROOT / "build" / "debug" / "bin" / "FreeCADCmd"
FIXTURES_SCRIPT = Path(__file__).resolve().parent / "fixtures" / "make_fixtures.py"
FIXTURES = ("empty", "one_body_one_sketch", "pad_on_rect")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_llm: hits the configured LLM proxy; skip by default, enable with -m live_llm",
    )


def pytest_collection_modifyitems(config, items):
    if "live_llm" in (config.getoption("-m") or ""):
        return
    skip_marker = pytest.mark.skip(reason="live_llm test; run with `-m live_llm` to enable")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def transport_env() -> dict[str, str]:
    required = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        pytest.skip(f"missing env vars for live_llm test: {missing}")
    return {k: os.environ[k] for k in required}


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory) -> Path:
    """Ensure every fixture .FCStd exists; regenerate missing ones via FreeCADCmd."""
    d = Path(__file__).resolve().parent / "fixtures"
    d.mkdir(exist_ok=True)
    missing = [n for n in FIXTURES if not (d / f"{n}.FCStd").exists()]
    if not missing:
        return d
    if not FREECADCMD.exists():
        pytest.skip(f"FreeCADCmd not found at {FREECADCMD} — cannot generate fixtures")
    scratch = tmp_path_factory.mktemp("fx-home")
    (scratch / ".local" / "share").mkdir(parents=True, exist_ok=True)
    (scratch / ".config").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "HOME": str(scratch),
        "XDG_DATA_HOME": str(scratch / ".local" / "share"),
        "XDG_CONFIG_HOME": str(scratch / ".config"),
        "CADAGENT_FIXTURES_DIR": str(d),
    })
    subprocess.run(
        [str(FREECADCMD), "-c", f"exec(open({str(FIXTURES_SCRIPT)!r}).read())"],
        env=env, check=True, timeout=120, capture_output=True,
    )
    return d


@pytest.fixture
def pad_on_rect(fixtures_dir) -> Path:
    return fixtures_dir / "pad_on_rect.FCStd"


@pytest.fixture
def empty_doc(fixtures_dir) -> Path:
    return fixtures_dir / "empty.FCStd"
