# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2026 FreeCAD Project Association <www.freecad.org>      *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful,            *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with FreeCAD; if not, write to the Free Software        *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************
"""GUI initialisation for the CAD Agent workbench."""

from __future__ import annotations

import os

import FreeCAD
import FreeCADGui

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore


translate = FreeCAD.Qt.translate


def _auto_open_panel():
    """Auto-open the CAD Agent chat panel at FreeCAD startup."""
    import traceback
    try:
        FreeCAD.Console.PrintMessage("CADAgent: auto-open start\n")
        import CADAgent
        FreeCAD.Console.PrintMessage("CADAgent: module imported\n")
        CADAgent.register_commands()
        FreeCAD.Console.PrintMessage("CADAgent: commands registered\n")
        CADAgent.add_preferences_page()
        FreeCAD.Console.PrintMessage("CADAgent: prefs added\n")
        CADAgent.open_panel()
        FreeCAD.Console.PrintMessage("CADAgent: panel opened\n")
    except Exception as exc:
        FreeCAD.Console.PrintError(
            f"CAD Agent: auto-open failed: {exc}\n"
            f"{traceback.format_exc()}\n"
        )


def _install_agent_toolbar():
    """Add a persistent 'Agent' button to the main window toolbar.

    The button is visible in every workbench, so the chat is always one click
    away, like Copilot's activity-bar icon in VS Code.
    """
    import traceback
    try:
        from PySide6 import QtCore as _QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore as _QtCore, QtGui, QtWidgets
    mw = FreeCADGui.getMainWindow()
    if mw is None:
        return
    existing = mw.findChild(QtWidgets.QToolBar, "CADAgentPersistentToolbar")
    if existing is not None:
        return

    # Inline the toggle callback so it survives FreeCAD's InitGui exec context
    # (where sibling module-level functions aren't reliably visible to closures).
    def _toggle():
        try:
            import CADAgent
            CADAgent.register_commands()
            CADAgent.open_panel()
            dock = mw.findChild(QtWidgets.QDockWidget, "CADAgentChatDock")
            if dock is not None:
                if dock.isHidden():
                    dock.show()
                dock.raise_()
        except Exception as exc:
            FreeCAD.Console.PrintError(
                f"CAD Agent: toggle failed: {exc}\n{traceback.format_exc()}\n"
            )

    tb = QtWidgets.QToolBar(translate("CADAgent", "CAD Agent"), mw)
    tb.setObjectName("CADAgentPersistentToolbar")
    act = QtGui.QAction(translate("CADAgent", "Agent"), mw)
    act.setObjectName("CADAgent_OpenChatAction")
    act.setToolTip(translate("CADAgent", "Open CAD Agent chat (Ctrl+Alt+A)"))
    act.setShortcut(QtGui.QKeySequence("Ctrl+Alt+A"))
    try:
        act.setIcon(QtGui.QIcon(":/CADAgent/icons/CADAgent.svg"))
    except Exception:
        pass
    act.triggered.connect(_toggle)
    tb.addAction(act)

    def _configure():
        try:
            import CADAgent
            CADAgent.register_commands()
            FreeCADGui.runCommand("CADAgent_ConfigureLLM")
        except Exception as exc:
            FreeCAD.Console.PrintError(
                f"CAD Agent: configure failed: {exc}\n{traceback.format_exc()}\n"
            )

    cfg_act = QtGui.QAction(translate("CADAgent", "Configure LLM…"), mw)
    cfg_act.setObjectName("CADAgent_ConfigureLLMAction")
    cfg_act.setToolTip(
        translate("CADAgent", "Set the LiteLLM proxy URL, key, and model")
    )
    cfg_act.triggered.connect(_configure)
    tb.addAction(cfg_act)

    tb.setToolButtonStyle(_QtCore.Qt.ToolButtonTextBesideIcon)
    mw.addToolBar(_QtCore.Qt.TopToolBarArea, tb)


# Open the chat dock automatically at FreeCAD startup (Copilot-style),
# regardless of which workbench the user lands on. Deferred via a 0-ms
# timer so the main window is fully constructed first.
QtCore.QTimer.singleShot(0, _auto_open_panel)
QtCore.QTimer.singleShot(0, _install_agent_toolbar)


# Register the Qt resource compiled from Resources/CADAgent.qrc so the icon
# below is addressable via the ":/CADAgent/..." URL regardless of on-disk path.
try:
    import CADAgent_rc  # noqa: F401
except ImportError:
    pass


class CADAgentWorkbench(FreeCADGui.Workbench):
    """Copilot-style AI chat workbench for FreeCAD."""

    # NOTE: FreeCAD evaluates InitGui.py in an exec context where class
    # bodies cannot see module-level globals. Therefore initial attributes
    # must be inline literals or set inside __init__, following the BIM
    # workbench pattern.
    MenuText = "CAD Agent"
    ToolTip = "AI chat assistant for FreeCAD powered by the Claude Agent SDK"
    Icon = ":/CADAgent/icons/CADAgent.svg"

    def Initialize(self):
        """Register commands and build menus/toolbars."""
        import CADAgent

        CADAgent.register_commands()
        CADAgent.add_preferences_page()
        self.appendToolbar("CAD Agent", ["CADAgent_OpenPanel"])
        self.appendMenu(
            "CAD Agent",
            ["CADAgent_OpenPanel", "CADAgent_ConfigureLLM"],
        )

    def Activated(self):
        """Open the chat panel when the workbench is activated."""
        import CADAgent

        CADAgent.open_panel()

    def Deactivated(self):
        """No-op on workbench deactivation."""
        pass

    def GetClassName(self):
        """Return the C++ workbench class name."""
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(CADAgentWorkbench())
