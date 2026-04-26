"""Pytest configuration for CADAgent headless tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Make `agent` importable as a top-level package: src/Mod/CADAgent is the
# package root that contains `agent/`.
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))
