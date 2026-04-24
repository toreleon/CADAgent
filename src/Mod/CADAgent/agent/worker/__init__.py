# SPDX-License-Identifier: LGPL-2.1-or-later
"""Long-lived CAD worker subprocess.

Hosts a JSON-RPC-ish stdio loop so the CAD agent can drive FreeCAD without
forking a fresh ``FreeCADCmd`` per tool call. This package is intentionally
dependency-free at import time — it must load in a plain Python interpreter
with no FreeCAD available. Handlers that need FreeCAD will register in a
later PR (A3).
"""
