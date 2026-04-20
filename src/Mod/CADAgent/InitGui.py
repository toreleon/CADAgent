# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI initialisation for the CAD Agent workbench."""

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


def _auto_open_panel():
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
    away — like Copilot's activity-bar icon in VS Code.
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

    tb = QtWidgets.QToolBar("CAD Agent", mw)
    tb.setObjectName("CADAgentPersistentToolbar")
    act = QtGui.QAction("Agent", mw)
    act.setObjectName("CADAgent_OpenChatAction")
    act.setToolTip("Open CAD Agent chat (Ctrl+Alt+A)")
    act.setShortcut(QtGui.QKeySequence("Ctrl+Alt+A"))
    try:
        act.setIcon(QtGui.QIcon(":/CADAgent/icons/CADAgent.svg"))
    except Exception:
        pass
    act.triggered.connect(_toggle)
    tb.addAction(act)
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
        import CADAgent

        CADAgent.register_commands()
        CADAgent.add_preferences_page()
        self.appendToolbar("CAD Agent", ["CADAgent_OpenPanel"])
        self.appendMenu("CAD Agent", ["CADAgent_OpenPanel"])

    def Activated(self):
        import CADAgent

        CADAgent.open_panel()

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(CADAgentWorkbench())
