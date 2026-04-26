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
  * Register the open-panel command.

LLM configuration (model, base URL, API key) is read from environment
variables by the underlying CLI agent runtime — see
``agent/cli/runtime.py``.
"""

from __future__ import annotations

import traceback

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtWidgets
except ImportError:
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets


translate = App.Qt.translate


_RUNTIME = None
_LOOP_INSTALLED = False


def _install_asyncio_loop() -> None:
    """Install qasync's Qt-backed asyncio event loop. Idempotent."""
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
        existing = asyncio.get_event_loop()
        if isinstance(existing, qasync.QEventLoop):
            _LOOP_INSTALLED = True
            return
    except RuntimeError:
        pass
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    _LOOP_INSTALLED = True


PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/CADAgent"


def _make_configure_llm_command():
    """Build and return the CADAgent_ConfigureLLM command class.

    Persists the LiteLLM proxy URL, API key, and model into FreeCAD's
    parameter store. The dock runtime reads these (falling back to
    ANTHROPIC_* env vars) when starting the SDK client.
    """

    def _open_dialog():
        params = App.ParamGet(PARAM_PATH)
        dlg = QtWidgets.QDialog(Gui.getMainWindow())
        dlg.setWindowTitle(translate("CADAgent", "Configure LLM"))
        form = QtWidgets.QFormLayout(dlg)

        url_edit = QtWidgets.QLineEdit(params.GetString("BaseURL", ""), dlg)
        url_edit.setPlaceholderText("http://localhost:4000  (leave blank for direct Anthropic)")
        form.addRow(translate("CADAgent", "Base URL"), url_edit)

        key_edit = QtWidgets.QLineEdit(params.GetString("ApiKey", ""), dlg)
        key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow(translate("CADAgent", "API key"), key_edit)

        model_edit = QtWidgets.QLineEdit(params.GetString("Model", ""), dlg)
        model_edit.setPlaceholderText("claude-opus-4-7")
        form.addRow(translate("CADAgent", "Model"), model_edit)

        # Thinking toggle — off by default (matches the new runtime default).
        # For Anthropic-native endpoints this controls extended-thinking blocks.
        # For LiteLLM-fronted providers (GLM, OpenAI, …) the SDK still sends
        # the field; whether it propagates depends on the proxy's mapping.
        thinking_box = QtWidgets.QCheckBox(
            translate("CADAgent", "Enable reasoning / extended thinking"), dlg
        )
        thinking_box.setChecked(
            bool(params.GetBool("ThinkingEnabled", False))
        )
        form.addRow("", thinking_box)

        effort_combo = QtWidgets.QComboBox(dlg)
        effort_combo.addItem(translate("CADAgent", "(default)"), "")
        for level in ("low", "medium", "high", "max"):
            effort_combo.addItem(level, level)
        stored_effort = params.GetString("ThinkingEffort", "")
        idx = effort_combo.findData(stored_effort)
        effort_combo.setCurrentIndex(max(0, idx))
        effort_combo.setEnabled(thinking_box.isChecked())
        thinking_box.toggled.connect(effort_combo.setEnabled)
        form.addRow(translate("CADAgent", "Thinking effort"), effort_combo)

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
        params.SetBool("ThinkingEnabled", thinking_box.isChecked())
        params.SetString(
            "ThinkingEffort", effort_combo.currentData() or ""
        )

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
                    "CADAgent", "Set the API base URL, key, and model"
                ),
                "Pixmap": ":/CADAgent/icons/CADAgent.svg",
            }

        def IsActive(self):
            return True

        def Activated(self):
            _open_dialog()

    return CADAgent_ConfigureLLM


def _make_open_panel_command():
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


def register_commands() -> None:
    """Register the CAD Agent Gui commands (idempotent)."""
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
    """Attach the chat panel to its C++ host (if needed) and surface the dock.

    The host is a ``Gui::CADAgentView`` registered by MainWindow with
    ``DockWindowManager``; visibility is owned by FreeCAD's standard
    parameter/saved-layout system. This function only ensures the QML panel
    is attached, the runtime is wired, and the dock is activated/raised.
    """
    global _RUNTIME
    try:
        _install_asyncio_loop()
        from agent import gui_thread
        gui_thread.init_dispatcher()
    except Exception as exc:
        App.Console.PrintError(f"CAD Agent: {exc}\n")
        return

    from agent.ui import qml_panel as ChatPanelMod
    from agent.cli.dock_runtime import DockRuntime

    panel = ChatPanelMod.attach_panel_to_host()
    if panel is None:
        App.Console.PrintError("CAD Agent: panel failed to construct.\n")
        return

    if _RUNTIME is None:
        _RUNTIME = DockRuntime(panel)
        panel.attach_runtime(_RUNTIME)

    # Surface the dock: walk up from the panel to find the QDockWidget
    # container that DockWindowManager wrapped around the C++ host, and show
    # / raise it. (DockWindowManager isn't exposed to Python, so we cannot
    # call its activate() directly.)
    widget = panel
    while widget is not None and not isinstance(widget, QtWidgets.QDockWidget):
        widget = widget.parentWidget()
    if widget is not None:
        if widget.isHidden():
            widget.show()
        widget.raise_()
