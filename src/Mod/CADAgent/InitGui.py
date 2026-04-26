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


def _attach_panel_to_host():
    """Wire the QML chat panel into the C++ ``Gui::CADAgentView`` host.

    Visibility is owned by ``DockWindowManager`` (see StdWorkbench's
    ``DockWindowItems`` registration). For users whose saved dock layout
    pre-dates ``Std_CADAgentView``, ``QMainWindow::restoreState`` leaves the
    new dock unplaced; we detect that case and dock it on the right once.
    """
    import traceback
    try:
        try:
            from PySide6 import QtCore as _QC, QtWidgets as _QtW
        except ImportError:
            from PySide2 import QtCore as _QC, QtWidgets as _QtW

        import CADAgent
        CADAgent.register_commands()
        CADAgent.open_panel()

        # Guard against pre-existing saved layouts that don't know about the
        # new Std_CADAgentView dock. Run after a delay so DockWindowManager's
        # setup() and MainWindow::loadLayoutSettings() have finished.
        def _ensure_placed():
            mw = FreeCADGui.getMainWindow()
            if mw is None:
                return
            for d in mw.findChildren(_QtW.QDockWidget):
                if d.objectName() != "CAD Agent":
                    continue
                area = mw.dockWidgetArea(d)
                # If the dock is floating (top-level window) or stranded with
                # no area — both happen when restoreState has no entry for the
                # newly-added Std_CADAgentView — re-dock it on the right.
                needs_dock = d.isFloating() or area == _QC.Qt.NoDockWidgetArea
                if needs_dock:
                    if d.isFloating():
                        d.setFloating(False)
                    mw.addDockWidget(_QC.Qt.RightDockWidgetArea, d)
                    d.setVisible(True)
                break

        _QC.QTimer.singleShot(0, _ensure_placed)
        _QC.QTimer.singleShot(1500, _ensure_placed)
    except Exception as exc:
        FreeCAD.Console.PrintError(
            f"CAD Agent: panel attach failed: {exc}\n"
            f"{traceback.format_exc()}\n"
        )


def _install_agent_toolbar():
    """Add a persistent 'Agent' button to the main window's status bar.

    The button sits next to FreeCAD's built-in console/report-view toggles so
    the chat is always one click away, like Copilot's status-bar icon in VS Code.
    """
    import traceback
    try:
        from PySide6 import QtCore as _QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore as _QtCore, QtGui, QtWidgets
    mw = FreeCADGui.getMainWindow()
    if mw is None:
        return
    if mw.findChild(QtWidgets.QToolButton, "CADAgentStatusBarButton") is not None:
        return
    sb = mw.statusBar()
    if sb is None:
        return

    # Inline the toggle callback so it survives FreeCAD's InitGui exec context
    # (where sibling module-level functions aren't reliably visible to closures).
    def _toggle():
        try:
            import CADAgent
            CADAgent.register_commands()
            # Ensure the QML panel is wired to the C++ host before we toggle.
            CADAgent.open_panel()
            # Find the QDockWidget container that DockWindowManager built around
            # the CADAgentView host. Both the inner view and the container share
            # the objectName "CAD Agent"; iterate dock widgets to disambiguate.
            container = None
            for dw in mw.findChildren(QtWidgets.QDockWidget):
                if dw.objectName() == "CAD Agent":
                    container = dw
                    break
            if container is None:
                return
            if container.isVisible():
                container.hide()
            else:
                container.show()
                container.raise_()
        except Exception as exc:
            FreeCAD.Console.PrintError(
                f"CAD Agent: toggle failed: {exc}\n{traceback.format_exc()}\n"
            )

    act = QtGui.QAction(translate("CADAgent", "Agent"), mw)
    act.setObjectName("CADAgent_OpenChatAction")
    act.setToolTip(translate("CADAgent", "Open CAD Agent chat (Ctrl+Alt+A)"))
    act.setShortcut(QtGui.QKeySequence("Ctrl+Alt+A"))
    try:
        act.setIcon(QtGui.QIcon(":/CADAgent/icons/CADAgent.svg"))
    except Exception:
        pass
    act.triggered.connect(_toggle)

    btn = QtWidgets.QToolButton(sb)
    btn.setObjectName("CADAgentStatusBarButton")
    btn.setDefaultAction(act)
    btn.setToolButtonStyle(_QtCore.Qt.ToolButtonTextBesideIcon)
    btn.setAutoRaise(True)

    # Place next to the console/report-view toggles on the right side of the
    # status bar. addPermanentWidget right-aligns; insert so the button sits
    # just before the existing toggles rather than after them.
    sb.addPermanentWidget(btn, 0)


# Attach the QML chat panel into the C++ host shell (Std_CADAgentView).
# Visibility itself is managed by FreeCAD's DockWindowManager + saved layout,
# so this only constructs the panel and binds the runtime — Copilot-style
# default visibility is set in StdWorkbench::setupDockWindows().
QtCore.QTimer.singleShot(0, _attach_panel_to_host)
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
