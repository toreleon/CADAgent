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

from .. import sessions as cad_sessions
from .composer import _Composer
from .history_popup import HistoryPopup
from .styles import build_panel_qss
from .widgets import (
    GUTTER,
    IO_COL,
    _AssistantRow,
    _CodeBlock,
    _ErrorRow,
    _SystemRow,
    _ThinkingRow,
    _ToolCallCard,
    _ToolEntry,
    _TurnFooter,
    _UserRow,
    preview_result,
)


translate = App.Qt.translate


DOCK_OBJECT_NAME = "CADAgentChatDock"


def _extract_text(message) -> str:
    """Pull plain text out of a raw session-transcript message dict."""
    if message is None:
        return ""
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            parts.append(block["text"])
    return "\n".join(parts).strip()


def _mw():
    """Return the FreeCAD main window."""
    return Gui.getMainWindow()


class ChatPanel(QtWidgets.QWidget):
    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CADAgentRoot")
        self.setStyleSheet(build_panel_qss())
        self._runtime = None
        self._assistant_row = None
        self._last_thinking_row: _ThinkingRow | None = None
        self._tool_entries: dict[str, _ToolEntry] = {}
        self._bound_doc = None
        self._current_session_id: str | None = None
        self._build_ui()
        self._sync_doc_binding()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        self._stream = QtWidgets.QScrollArea()
        self._stream.setObjectName("CADAgentStream")
        self._stream.setWidgetResizable(True)
        self._stream.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget()
        body.setObjectName("CADAgentStreamBody")
        self._stream_body = body
        self._stream_layout = QtWidgets.QVBoxLayout(body)
        self._stream_layout.setContentsMargins(4, 6, 4, 6)
        self._stream_layout.setSpacing(2)
        self._stream_layout.addStretch(1)
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

        self._greet()

    def _build_topbar(self) -> QtWidgets.QWidget:
        """Minimal borderless top row with new-chat + history icon buttons.

        The dock title already names the panel, so no header label/tabs — just
        two unobtrusive icons, right-aligned, floating over the canvas.
        """
        bar = QtWidgets.QWidget()
        bar.setAttribute(QtCore.Qt.WA_StyledBackground, False)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(6, 4, 6, 0)
        lay.setSpacing(2)
        lay.addStretch(1)

        self._new_btn = QtWidgets.QToolButton()
        self._new_btn.setText("+")
        self._new_btn.setProperty("role", "icon")
        self._new_btn.setToolTip(translate("CADAgent", "New chat"))
        self._new_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._new_btn.setFixedSize(22, 22)
        self._new_btn.clicked.connect(self._on_new_clicked)
        lay.addWidget(self._new_btn)

        self._history_btn = QtWidgets.QToolButton()
        self._history_btn.setText("\u25F7")
        self._history_btn.setProperty("role", "icon")
        self._history_btn.setToolTip(
            translate("CADAgent", "Chat history for this document")
        )
        self._history_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._history_btn.setFixedSize(22, 22)
        self._history_btn.clicked.connect(self._on_history_clicked)
        lay.addWidget(self._history_btn)

        self._config_btn = QtWidgets.QToolButton()
        self._config_btn.setText("⚙")
        self._config_btn.setProperty("role", "icon")
        self._config_btn.setToolTip(
            translate("CADAgent", "Configure LLM (URL, key, model)")
        )
        self._config_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._config_btn.setFixedSize(22, 22)
        self._config_btn.clicked.connect(self._on_configure_clicked)
        lay.addWidget(self._config_btn)

        # Kept so session-title updates from existing code still have a sink.
        self._title_lbl = QtWidgets.QLabel("")
        self._title_lbl.setVisible(False)

        self._history_popup: HistoryPopup | None = None
        return bar

    def _greet(self) -> None:
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
        self._sync_doc_binding()

    def on_session_changed(self, session_id: str) -> None:
        """Called from the runtime when the SDK reports a session id."""
        self._current_session_id = session_id
        doc = self._bound_doc or App.ActiveDocument
        entry = cad_sessions.find(doc, session_id) if doc else None
        if entry and entry.get("title"):
            self._title_lbl.setText(entry["title"])
        else:
            self._title_lbl.setText(
                translate("CADAgent", "New chat")
                if not self._current_session_id
                else session_id[:8]
            )

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
            rl.setContentsMargins(10 + GUTTER, 2, 12, 2)
            rl.setSpacing(8)
            rl.setAlignment(QtCore.Qt.AlignTop)
            label_text = (
                translate("CADAgent", "ERR") if is_error else translate("CADAgent", "OUT")
            )
            io_lbl = QtWidgets.QLabel(label_text)
            io_lbl.setProperty("role", "io_label")
            io_lbl.setFixedWidth(IO_COL)
            rl.addWidget(io_lbl, 0, QtCore.Qt.AlignTop)
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
        widget.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum
        )
        # Insert above the trailing stretch so rows stack top-down.
        self._stream_layout.insertWidget(self._stream_layout.count() - 1, widget)
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

    # --- session management UI ---------------------------------------

    def _sync_doc_binding(self) -> None:
        """Bind the panel + runtime to the currently active FreeCAD document."""
        doc = App.ActiveDocument
        if doc is self._bound_doc:
            return
        self._bound_doc = doc
        if self._runtime is not None and doc is not None:
            self._runtime.bind_document(doc)
        self._reset_stream(initial=True)

    def _reset_stream(self, initial: bool = False) -> None:
        self._close_assistant()
        self._last_thinking_row = None
        self._tool_entries.clear()
        while self._stream_layout.count():
            item = self._stream_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._stream_layout.addStretch(1)
        self._greet()
        if initial:
            self._title_lbl.setText(translate("CADAgent", "New chat"))

    def _on_new_clicked(self) -> None:
        if self._runtime is not None and not self._runtime.start_new_session():
            self.show_error(
                translate("CADAgent", "Finish or stop the current turn first.")
            )
            return
        self._current_session_id = None
        self._title_lbl.setText(translate("CADAgent", "New chat"))
        self._reset_stream()

    def _on_configure_clicked(self) -> None:
        try:
            import FreeCADGui as Gui
            Gui.runCommand("CADAgent_ConfigureLLM")
        except Exception as exc:
            self.show_error(str(exc))

    def _on_history_clicked(self) -> None:
        doc = self._bound_doc or App.ActiveDocument
        entries = cad_sessions.list_sessions(doc) if doc else []
        if self._history_popup is None:
            self._history_popup = HistoryPopup(self)
            self._history_popup.sessionActivated.connect(self._on_resume_clicked)
            self._history_popup.sessionDeleted.connect(self._on_delete_session)
        self._history_popup.set_entries(entries, self._current_session_id)
        self._history_popup.popup_below(self._history_btn)

    def _on_delete_session(self, session_id: str) -> None:
        doc = self._bound_doc or App.ActiveDocument
        if doc is None or not session_id:
            return
        cad_sessions.delete(doc, session_id)
        if session_id == self._current_session_id:
            if self._runtime is not None and self._runtime.start_new_session():
                self._current_session_id = None
                self._title_lbl.setText(translate("CADAgent", "New chat"))
                self._reset_stream()

    def _on_resume_clicked(self, session_id: str) -> None:
        if not session_id or self._runtime is None:
            return
        if not self._runtime.resume_session(session_id):
            self.show_error(
                translate("CADAgent", "Finish or stop the current turn first.")
            )
            return
        self._current_session_id = session_id
        doc = self._bound_doc or App.ActiveDocument
        entry = cad_sessions.find(doc, session_id) if doc else None
        title = (entry or {}).get("title") or session_id[:8]
        self._reset_stream()
        self._title_lbl.setText(title)
        self._replay_transcript(session_id)

    def _replay_transcript(self, session_id: str) -> None:
        """Render past user/assistant text from the SDK transcript."""
        try:
            from claude_agent_sdk import get_session_messages
        except ImportError:
            return
        try:
            msgs = get_session_messages(session_id)
        except Exception as exc:
            self._append(
                _SystemRow(
                    translate("CADAgent", "Could not load transcript: {0}").format(exc)
                )
            )
            return
        rendered = 0
        for sm in msgs:
            text = _extract_text(getattr(sm, "message", None))
            if not text:
                continue
            if sm.type == "user":
                self._append(_UserRow(text))
            else:
                row = _AssistantRow()
                row.append(text)
                row.mark_done()
                self._append(row)
            rendered += 1
        if rendered == 0:
            self._append(
                _SystemRow(translate("CADAgent", "(Empty transcript)"))
            )
        else:
            self._append(
                _SystemRow(
                    translate("CADAgent", "\u2014 resumed session \u2014")
                )
            )


class _DocObserver:
    """FreeCAD document observer that re-binds the panel on doc switches."""

    def slotActivateDocument(self, _doc):
        panel = get_panel()
        if panel is not None:
            try:
                panel._sync_doc_binding()
            except Exception:
                pass

    # Keep hook names matching FreeCAD's observer protocol; unused slots
    # are fine to omit — App.DocumentObserver dispatches by attribute.
    slotFinishOpenDocument = slotActivateDocument
    slotCreatedDocument = slotActivateDocument


_doc_observer_instance = None


def _install_doc_observer() -> None:
    global _doc_observer_instance
    if _doc_observer_instance is not None:
        return
    try:
        obs = _DocObserver()
        App.addDocumentObserver(obs)
        _doc_observer_instance = obs
    except Exception:
        pass


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
    _install_doc_observer()
    return dock


def get_panel():
    """Return the singleton ChatPanel instance, if any."""
    return ChatPanel._instance
