"""Pytest configuration for CADAgent headless tests.

Installs a fake `FreeCAD` module before any `agent.*` import so backend modules
load without the real FreeCAD runtime.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `agent` importable as a top-level package: src/Mod/CADAgent is the
# package root that contains `agent/`.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# Install fake FreeCAD into sys.modules at import time so `from agent import …`
# works in test collection. Per-test isolation is provided by the `fc` fixture
# below, which resets the in-memory state.
from tests.fakes import freecad as _fake_freecad  # noqa: E402

_fake_freecad.install()


@pytest.fixture
def fc(tmp_path, monkeypatch):
    """Fresh fake `FreeCAD` namespace, with `getUserAppDataDir` pointing at tmp.

    Re-installs the fake module to clear documents / params between tests.
    """
    # Reset by removing and re-installing; install() returns the fresh app.
    sys.modules.pop("FreeCAD", None)
    sys.modules.pop("FreeCADGui", None)
    app = _fake_freecad.install()
    monkeypatch.setattr(app, "_user_data_dir", str(tmp_path))
    return app


@pytest.fixture
def fake_doc(fc, tmp_path):
    """A saved fake document at <tmp>/test.FCStd."""
    path = str(tmp_path / "test.FCStd")
    doc = fc.openDocument(path)
    return doc


@pytest.fixture
def fake_sdk_client():
    """Factory for `FakeSDKClient` instances (importable for runtime tests)."""
    from tests.fakes.sdk_client import FakeSDKClient

    return FakeSDKClient
