# SPDX-License-Identifier: LGPL-2.1-or-later
"""Standalone CLI agent (Option A) — runs outside FreeCAD.

The agent here uses the SDK's built-in ``Bash`` tool to drive FreeCAD via
``FreeCADCmd`` subprocesses, and keeps a thin MCP surface for the memory
sidecar + milestone plan (which don't need a live FreeCAD process).

Entry point: ``scripts/cadagent``. Python module entry: ``agent.cli.main``.
"""
