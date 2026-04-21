# SPDX-License-Identifier: LGPL-2.1-or-later
"""Claude Code-style chat panel for FreeCAD.

Dark canvas, flush rows (no bubbles), status-dot + IN/OUT badged tool blocks,
and a rounded composer with a circular accent send button.
"""

from __future__ import annotations

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets

from .composer import _Composer
from .styles import PANEL_QSS
from .widgets import (
    _AssistantRow,
    _CodeBlock,
    _ErrorRow,
    _SystemRow,
    _ThinkingRow,
    _ToolCallCard,
    _ToolEntry,
    _TurnFooter,
    _UserRow,
    badge,
    preview_result,
)


translate = App.Qt.translate


DOCK_OBJECT_NAME = "CADAgentChatDock"


def _mw():
    """Return the FreeCAD main window."""
    return Gui.getMainWindow()


class ChatPanel(QtWidgets.QWidget):
    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CADAgentRoot")
        self.setStyleSheet(PANEL_QSS)
        self._runtime = None
        self._assistant_row = None
        self._last_thinking_row: _ThinkingRow | None = None
        self._tool_entries: dict[str, _ToolEntry] = {}
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stream = QtWidgets.QScrollArea()
        self._stream.setObjectName("CADAgentStream")
        self._stream.setWidgetResizable(True)
        self._stream.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget()
        body.setObjectName("CADAgentStreamBody")
        self._stream_body = body
        self._stream_layout = QtWidgets.QVBoxLayout(body)
        self._stream_layout.setAlignment(QtCore.Qt.AlignTop)
        self._stream_layout.setContentsMargins(4, 6, 4, 6)
        self._stream_layout.setSpacing(2)
        self._stream.setWidget(body)
        root.addWidget(self._stream, 1)

        composer_wrap = QtWidgets.QWidget()
        cw = QtWidgets.QVBoxLayout(composer_wrap)
        cw.setContentsMargins(8, 4, 8, 8)
        cw.setSpacing(0)
        self._composer = _Composer()
        cw.addWidget(self._composer)
        root.addWidget(composer_wrap)

        self._composer.sendRequested.connect(self._on_send_clicked)
        self._composer.stopRequested.connect(self._on_stop_clicked)

        self._append(
            _SystemRow(
                translate("CADAgent", "CAD Agent ready. Ask me to model something.")
            )
        )

    # --- External API -------------------------------------------------

    def attach_runtime(self, runtime) -> None:
        """Bind an agent runtime and sync permission-mode UI state."""
        self._runtime = runtime
        try:
            mode = App.ParamGet(
                "User parameter:BaseApp/Preferences/Mod/CADAgent"
            ).GetString("PermissionMode", "default")
            self._composer.set_bypass(mode == "bypassPermissions")
        except Exception:
            pass

    def append_assistant_text(self, text: str) -> None:
        if self._assistant_row is None:
            self._collapse_thinking()
            self._assistant_row = _AssistantRow()
            self._append(self._assistant_row)
        self._assistant_row.append(text)

    def append_thinking(self, text: str) -> None:
        self._close_assistant()
        if self._last_thinking_row is not None:
            self._last_thinking_row.append(text)
            return
        row = _ThinkingRow(text)
        self._last_thinking_row = row
        self._append(row)

    def announce_tool_use(self, tool_use_id: str, name: str, tool_input: dict) -> None:
        self._close_assistant()
        self._collapse_thinking()
        entry = _ToolEntry(name, tool_input)
        if tool_use_id:
            self._tool_entries[tool_use_id] = entry
        self._append(entry)

    def announce_tool_result(self, tool_use_id: str, content, is_error: bool) -> None:
        entry = self._tool_entries.pop(tool_use_id, None)
        if entry is not None:
            entry.set_result(content, is_error)
        else:
            # Fallback: render a standalone OUT block so nothing is lost.
            row = QtWidgets.QWidget()
            rl = QtWidgets.QHBoxLayout(row)
            rl.setContentsMargins(28, 2, 10, 2)
            rl.setSpacing(8)
            rl.setAlignment(QtCore.Qt.AlignTop)
            badge_text = (
                translate("CADAgent", "ERR") if is_error else translate("CADAgent", "OUT")
            )
            rl.addWidget(badge(badge_text), 0, QtCore.Qt.AlignTop)
            rl.addWidget(_CodeBlock(preview_result(content)), 1)
            self._append(row)

    def record_result(self, msg) -> None:
        self._close_assistant()
        self._collapse_thinking()
        cost = getattr(msg, "total_cost_usd", None) or getattr(msg, "cost_usd", None)
        usage = getattr(msg, "usage", None)
        tokens = None
        if usage is not None:
            in_tok = getattr(usage, "input_tokens", None)
            out_tok = getattr(usage, "output_tokens", None)
            if in_tok is None and isinstance(usage, dict):
                in_tok = usage.get("input_tokens")
                out_tok = usage.get("output_tokens")
            if in_tok is not None or out_tok is not None:
                tokens = (in_tok or 0) + (out_tok or 0)
        parts = []
        if tokens is not None:
            parts.append(translate("CADAgent", "{0} tok").format(f"{tokens:,}"))
        if cost is not None:
            parts.append(f"${cost:.4f}")
        text = " · ".join(parts) if parts else translate("CADAgent", "turn complete")
        self._append(_TurnFooter(text))

    def mark_turn_complete(self) -> None:
        self._close_assistant()
        self._composer.set_busy(False)
        self._composer.input.setFocus()

    def show_error(self, message: str) -> None:
        self._close_assistant()
        self._append(_ErrorRow(message))

    def request_permission_threadsafe(
        self, tool_name: str, tool_input: dict, cf_future
    ) -> None:
        """Create a pending card whose Apply/Reject resolves ``cf_future``.

        Called from the Qt GUI thread (via the PanelProxy signal). ``cf_future``
        is a concurrent.futures.Future awaited by the async worker thread.
        """
        self._close_assistant()
        card = _ToolCallCard(tool_name, tool_input, cf_future)
        self._append(card)

    # --- Internals ----------------------------------------------------

    def _append(self, widget: QtWidgets.QWidget) -> None:
        self._stream_layout.addWidget(widget)
        QtCore.QTimer.singleShot(
            0,
            lambda: self._stream.verticalScrollBar().setValue(
                self._stream.verticalScrollBar().maximum()
            ),
        )

    def _close_assistant(self) -> None:
        if self._assistant_row is not None:
            self._assistant_row.mark_done()
            self._assistant_row = None

    def _collapse_thinking(self) -> None:
        if self._last_thinking_row is not None:
            self._last_thinking_row.collapse()
            self._last_thinking_row = None

    def _on_send_clicked(self) -> None:
        text = self._composer.input.toPlainText().strip()
        if not text:
            return
        if self._runtime is None:
            self.show_error(translate("CADAgent", "Agent runtime is not ready yet."))
            return
        self._composer.input.clear()
        self._append(_UserRow(text))
        self._composer.set_busy(True)
        self._runtime.submit(text)

    def _on_stop_clicked(self) -> None:
        if self._runtime is None:
            return
        self._runtime.interrupt()
        self._composer.set_busy(False)


def get_or_create_dock() -> QtWidgets.QDockWidget:
    """Return the CAD Agent dock widget, creating it on first use."""
    mw = _mw()
    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if existing is not None:
        return existing

    dock = QtWidgets.QDockWidget(translate("CADAgent", "CAD Agent"), mw)
    dock.setObjectName(DOCK_OBJECT_NAME)
    panel = ChatPanel(dock)
    ChatPanel._instance = panel
    dock.setWidget(panel)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.resize(440, dock.height())
    return dock


def get_panel():
    """Return the singleton ChatPanel instance, if any."""
    return ChatPanel._instance
