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
"""Dockable web-based chat panel using QWebEngineView + QWebChannel.

The HTML/TS app lives under Resources/web/. This module loads it inside a
QDockWidget and wires a ChatBridge that the JS side consumes via QWebChannel.

Panel interface matches the native ChatPanel so AgentRuntime can call either
one interchangeably.
"""

from __future__ import annotations

import os

import FreeCAD as App
import FreeCADGui as Gui

# FreeCAD's `PySide` compatibility shim wraps core Qt modules but NOT the
# QtWebEngine submodules, so import those directly from PySide6 / PySide2.
try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebChannel import QWebChannel
except ImportError:
    from PySide2.QtWebEngineWidgets import QWebEngineView
    from PySide2.QtWebChannel import QWebChannel

from Bridge import ChatBridge


translate = App.Qt.translate

DOCK_OBJECT_NAME = "CADAgentChatDock"

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEB_INDEX = os.path.join(_HERE, "Resources", "web", "index.html")


class WebChatPanel(QtWidgets.QWidget):
    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CADAgentWebRoot")

        self.bridge = ChatBridge(self)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.view = QWebEngineView(self)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        if os.path.exists(_WEB_INDEX):
            self.view.load(QtCore.QUrl.fromLocalFile(_WEB_INDEX))
        else:
            message = translate(
                "CADAgent",
                "CAD Agent web UI not found at:\n{0}\n"
                "Rebuild the module (cmake --build build/debug --target CADAgent).",
            ).format(_WEB_INDEX)
            self.view.setHtml(
                f"<pre style='color:#e05757;padding:12px;font:12px monospace'>"
                f"{message}"
                f"</pre>"
            )
        lay.addWidget(self.view)

    # --- Panel API (matches ChatPanel) -------------------------------

    def attach_runtime(self, runtime) -> None:
        self.bridge.attach_runtime(runtime)
        try:
            mode = App.ParamGet(
                "User parameter:BaseApp/Preferences/Mod/CADAgent"
            ).GetString("PermissionMode", "default")
            self.bridge.set_bypass(mode == "bypassPermissions")
        except Exception:
            pass

    def append_assistant_text(self, text: str) -> None:
        self.bridge.append_assistant_text(text)

    def append_thinking(self, text: str) -> None:
        self.bridge.append_thinking(text)

    def announce_tool_use(self, tool_use_id, name, tool_input) -> None:
        self.bridge.announce_tool_use(tool_use_id, name, tool_input)

    def announce_tool_result(self, tool_use_id, content, is_error) -> None:
        self.bridge.announce_tool_result(tool_use_id, content, is_error)

    def record_result(self, msg) -> None:
        self.bridge.record_result(msg)

    def mark_turn_complete(self) -> None:
        self.bridge.mark_turn_complete()

    def show_error(self, message: str) -> None:
        self.bridge.show_error(message)

    async def request_permission(self, tool_name, tool_input):
        return await self.bridge.request_permission(tool_name, tool_input)


def get_or_create_dock() -> QtWidgets.QDockWidget:
    mw = Gui.getMainWindow()
    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if existing is not None:
        return existing

    dock = QtWidgets.QDockWidget(translate("CADAgent", "CAD Agent"), mw)
    dock.setObjectName(DOCK_OBJECT_NAME)
    panel = WebChatPanel(dock)
    WebChatPanel._instance = panel
    dock.setWidget(panel)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.resize(460, dock.height())
    return dock


def get_panel():
    return WebChatPanel._instance
