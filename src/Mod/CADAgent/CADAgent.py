# SPDX-License-Identifier: LGPL-2.1-or-later
"""Module entry points for the CAD Agent workbench.

Responsibilities:
  * Install a qasync event loop once so the Claude Agent SDK can run alongside Qt.
  * Create the chat dock widget on demand.
  * Register commands and preferences page.
"""

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
    ui_path = os.path.join(os.path.dirname(__file__), "dlgPreferencesCADAgent.ui")
    if os.path.exists(ui_path):
        Gui.addPreferencePage(ui_path, "CAD Agent")


def _make_open_panel_command():
    try:
        import CADAgent_rc  # noqa: F401 - registers Qt resources
    except ImportError:
        pass

    class CADAgent_OpenPanel:
        def GetResources(self):
            return {
                "MenuText": "Open CAD Agent",
                "ToolTip": "Open the CAD Agent chat panel",
                "Pixmap": ":/CADAgent/icons/CADAgent.svg",
            }

        def IsActive(self):
            return True

        def Activated(self):
            open_panel()

    return CADAgent_OpenPanel


def register_commands() -> None:
    try:
        Gui.addCommand("CADAgent_OpenPanel", _make_open_panel_command()())
    except Exception:
        # addCommand raises if the command is already registered; ignore.
        App.Console.PrintLog(
            f"CADAgent: addCommand skipped\n{traceback.format_exc()}"
        )


def open_panel() -> None:
    """Create (if needed) and show the dock widget, wiring the runtime."""
    global _RUNTIME
    try:
        _install_asyncio_loop()
        import gui_thread
        gui_thread.init_dispatcher()
    except Exception as exc:
        App.Console.PrintError(f"CAD Agent: {exc}\n")
        return

    use_web = App.ParamGet(
        "User parameter:BaseApp/Preferences/Mod/CADAgent"
    ).GetBool("UseWebUI", False)

    if use_web:
        try:
            import WebChatPanel as ChatPanelMod
        except ImportError as exc:
            App.Console.PrintError(
                f"CAD Agent: web UI unavailable ({exc}); falling back to native panel.\n"
            )
            import ChatPanel as ChatPanelMod
    else:
        import ChatPanel as ChatPanelMod
    import AgentRuntime as AgentRuntimeMod

    dock = ChatPanelMod.get_or_create_dock()
    panel = ChatPanelMod.get_panel()
    if panel is None:
        App.Console.PrintError("CAD Agent: panel failed to construct.\n")
        return

    if _RUNTIME is None:
        _RUNTIME = AgentRuntimeMod.AgentRuntime(panel)
        panel.attach_runtime(_RUNTIME)

    dock.show()
    dock.raise_()
