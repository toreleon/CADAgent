# SPDX-License-Identifier: LGPL-2.1-or-later
"""In-FreeCAD agent runtime.

The chat dock (``agent.ui.qml_panel``) hosts :class:`agent.cli.dock_runtime.DockRuntime`,
which spins up a ``ClaudeSDKClient`` on a worker asyncio thread. The agent
drives FreeCAD via the SDK's built-in ``Bash`` tool invoking ``FreeCADCmd``
subprocesses, plus an MCP surface for live document inspection and the
memory / plan sidecar.
"""
