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
"""Module entry points for the CAD Agent workbench.

Responsibilities:
  * Install a qasync event loop once so the Claude Agent SDK can run alongside Qt.
  * Create the chat dock widget on demand.
  * Register commands and preferences page.
"""

from __future__ import annotations

import os
import sys
import traceback

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets


translate = App.Qt.translate


_RUNTIME = None
_LOOP_INSTALLED = False


def _install_asyncio_loop() -> None:
    """Install qasync's Qt-backed asyncio event loop.

    Runs once per FreeCAD session; subsequent calls are no-ops.
    """
    global _LOOP_INSTALLED
    if _LOOP_INSTALLED:
        return
    import asyncio
    try:
        import qasync
    except ImportError as exc:
        raise RuntimeError(
            "The 'qasync' Python package is required for the CAD Agent "
            "workbench. Install it via pixi (it is listed in pixi.toml)."
        ) from exc
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise RuntimeError("Qt application is not running; cannot install asyncio loop.")
    try:
        # If the current event loop is already a QEventLoop, reuse it.
        existing = asyncio.get_event_loop()
        if isinstance(existing, qasync.QEventLoop):
            _LOOP_INSTALLED = True
            return
    except RuntimeError:
        pass
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    _LOOP_INSTALLED = True


def add_preferences_page() -> None:
    """Register the CAD Agent preferences page if the .ui file is available."""
    ui_path = os.path.join(os.path.dirname(__file__), "dlgPreferencesCADAgent.ui")
    if os.path.exists(ui_path):
        Gui.addPreferencePage(ui_path, "CAD Agent")


def _make_open_panel_command():
    """Build and return the CADAgent_OpenPanel command class."""
    try:
        import CADAgent_rc  # noqa: F401 - registers Qt resources
    except ImportError:
        pass

    class CADAgent_OpenPanel:
        def GetResources(self):
            return {
                "MenuText": translate("CADAgent", "Open CAD Agent"),
                "ToolTip": translate("CADAgent", "Open the CAD Agent chat panel"),
                "Pixmap": ":/CADAgent/icons/CADAgent.svg",
            }

        def IsActive(self):
            return True

        def Activated(self):
            open_panel()

    return CADAgent_OpenPanel


def _make_configure_llm_command():
    """Build and return the CADAgent_ConfigureLLM command class."""

    PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/CADAgent"

    def _open_dialog():
        params = App.ParamGet(PARAM_PATH)
        dlg = QtWidgets.QDialog(Gui.getMainWindow())
        dlg.setWindowTitle(translate("CADAgent", "Configure LLM"))
        form = QtWidgets.QFormLayout(dlg)

        url_edit = QtWidgets.QLineEdit(params.GetString("BaseURL", ""), dlg)
        url_edit.setPlaceholderText("http://localhost:4000")
        form.addRow(translate("CADAgent", "LiteLLM proxy URL"), url_edit)

        key_edit = QtWidgets.QLineEdit(params.GetString("ApiKey", ""), dlg)
        key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow(translate("CADAgent", "LiteLLM proxy key"), key_edit)

        model_edit = QtWidgets.QLineEdit(params.GetString("Model", ""), dlg)
        model_edit.setPlaceholderText("gpt-5-mini")
        form.addRow(translate("CADAgent", "Model"), model_edit)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dlg,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        params.SetString("BaseURL", url_edit.text().strip())
        params.SetString("ApiKey", key_edit.text())
        params.SetString("Model", model_edit.text().strip())

        global _RUNTIME
        if _RUNTIME is not None:
            try:
                _RUNTIME.aclose()
            except Exception:
                pass
            _RUNTIME = None
        App.Console.PrintMessage(
            "CAD Agent: LLM settings updated; next turn uses the new config.\n"
        )

    class CADAgent_ConfigureLLM:
        def GetResources(self):
            return {
                "MenuText": translate("CADAgent", "Configure LLM…"),
                "ToolTip": translate(
                    "CADAgent",
                    "Set the LiteLLM proxy URL, key, and model",
                ),
                "Pixmap": ":/CADAgent/icons/CADAgent.svg",
            }

        def IsActive(self):
            return True

        def Activated(self):
            _open_dialog()

    return CADAgent_ConfigureLLM


def register_commands() -> None:
    """Register the CAD Agent Gui commands (idempotent).

    FreeCAD's ``Gui.addCommand`` does not raise on duplicate names — it logs
    ``duplicate command …`` to the console. Check the existing registry so
    re-entry from multiple InitGui paths stays silent.
    """
    existing = set(Gui.listCommands())
    if "CADAgent_OpenPanel" not in existing:
        try:
            Gui.addCommand("CADAgent_OpenPanel", _make_open_panel_command()())
        except Exception:
            App.Console.PrintLog(
                f"CADAgent: addCommand skipped\n{traceback.format_exc()}"
            )
    if "CADAgent_ConfigureLLM" not in existing:
        try:
            Gui.addCommand("CADAgent_ConfigureLLM", _make_configure_llm_command()())
        except Exception:
            App.Console.PrintLog(
                f"CADAgent: addCommand skipped\n{traceback.format_exc()}"
            )


def open_panel() -> None:
    """Create (if needed) and show the dock widget, wiring the runtime."""
    global _RUNTIME
    try:
        _install_asyncio_loop()
        from agent import gui_thread
        gui_thread.init_dispatcher()
    except Exception as exc:
        App.Console.PrintError(f"CAD Agent: {exc}\n")
        return

    from agent.ui import qml_panel as ChatPanelMod
    from agent.runtime import AgentRuntime

    dock = ChatPanelMod.get_or_create_dock()
    panel = ChatPanelMod.get_panel()
    if panel is None:
        App.Console.PrintError("CAD Agent: panel failed to construct.\n")
        return

    if _RUNTIME is None:
        _RUNTIME = AgentRuntime(panel)
        panel.attach_runtime(_RUNTIME)

    dock.show()
    dock.raise_()
