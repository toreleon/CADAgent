# SPDX-License-Identifier: LGPL-2.1-or-later
"""QWebChannel bridge between the Python AgentRuntime and the web UI.

Implements the same method surface the native ChatPanel exposes to AgentRuntime
(append_assistant_text, announce_tool_use, ...), translating each call into a
Qt signal that the JavaScript side listens to over QWebChannel.

Slots annotated with @QtCore.Slot are callable from JS; signals are connected
in JS to DOM-update handlers.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import FreeCAD as App

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore

from .permissions import Decision


translate = App.Qt.translate


class ChatBridge(QtCore.QObject):
    # Python -> JS
    assistantText     = QtCore.Signal(str)
    thinkingText      = QtCore.Signal(str)
    toolUse           = QtCore.Signal(str, str, str)   # id, name, input_json
    toolResult        = QtCore.Signal(str, str, bool)  # id, content_json, is_error
    permissionRequest = QtCore.Signal(str, str, str)   # req_id, name, input_json
    turnComplete      = QtCore.Signal(float)           # cost_usd, -1 if unknown
    errorText         = QtCore.Signal(str)
    systemText        = QtCore.Signal(str)
    bypassChanged     = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._runtime = None
        self._pending: dict[str, asyncio.Future] = {}

    def attach_runtime(self, runtime) -> None:
        self._runtime = runtime

    # --- JS -> Python ------------------------------------------------

    @QtCore.Slot(str)
    def submit(self, text: str) -> None:
        if self._runtime is None:
            self.errorText.emit(translate("CADAgent", "Agent runtime not ready."))
            return
        self._runtime.submit(text)

    @QtCore.Slot()
    def stop(self) -> None:
        if self._runtime is None:
            return
        loop = asyncio.get_event_loop()
        loop.create_task(self._runtime.interrupt())

    @QtCore.Slot(str, bool, str)
    def decidePermission(self, req_id: str, allowed: bool, reason: str) -> None:
        fut = self._pending.pop(req_id, None)
        if fut is not None and not fut.done():
            fut.set_result(Decision(allowed=allowed, reason=reason or ""))

    # --- Async permission prompt (called by permissions.can_use_tool) ---

    async def request_permission(self, tool_name: str, tool_input: dict) -> Decision:
        req_id = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        self.permissionRequest.emit(
            req_id, tool_name, json.dumps(tool_input, default=str)
        )
        return await fut

    # --- Panel-API shims the runtime calls ---------------------------

    def append_assistant_text(self, text: str) -> None:
        self.assistantText.emit(text)

    def append_thinking(self, text: str) -> None:
        self.thinkingText.emit(text)

    def announce_tool_use(self, tool_use_id: str, name: str, tool_input) -> None:
        self.toolUse.emit(
            tool_use_id or "", name, json.dumps(tool_input, default=str)
        )

    def announce_tool_result(self, tool_use_id: str, content, is_error: bool) -> None:
        self.toolResult.emit(
            tool_use_id or "", json.dumps(content, default=str), bool(is_error)
        )

    def record_result(self, msg) -> None:
        cost = (
            getattr(msg, "total_cost_usd", None)
            or getattr(msg, "cost_usd", None)
            or -1.0
        )
        self.turnComplete.emit(float(cost))

    def mark_turn_complete(self) -> None:
        # The web side re-enables the send button on turnComplete; if record_result
        # didn't fire (e.g. aborted turn), emit a sentinel so the UI recovers.
        self.turnComplete.emit(-1.0)

    def show_error(self, message: str) -> None:
        self.errorText.emit(message)

    def set_bypass(self, on: bool) -> None:
        self.bypassChanged.emit(bool(on))
