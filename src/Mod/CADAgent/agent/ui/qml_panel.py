# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dockable QML-based chat panel — the sole CAD Agent UI.

The UI itself is declared in ``qml/ChatPanel.qml`` and talks to two Python
context objects:

* ``messages`` — a :class:`MessagesModel` (``QAbstractListModel``) holding one
  row per chat entry. Roles: ``kind``, ``text``, ``meta``.
* ``bridge`` — a :class:`QmlChatBridge` (``QObject``) exposing slots the QML
  calls (``submit``, ``stop``, ``newChat``, …) and properties QML binds to
  (``busy``, ``bypass``).

Unsupported-in-v1 features (inline ``AskUserQuestion`` cards, the chat-history
popup, session resume) fall back to system rows rather than crashing, so the
runtime stays compatible.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets

# QQuickWidget lives in QtQuickWidgets; on FreeCAD's PySide shim it isn't
# re-exported, so import explicitly from the underlying binding.
try:
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtQml import QQmlContext  # noqa: F401
except ImportError:  # pragma: no cover - PySide2 fallback
    from PySide2.QtQuickWidgets import QQuickWidget
    from PySide2.QtQml import QQmlContext  # noqa: F401

from .. import sessions as cad_sessions
from ..permissions import Decision


translate = App.Qt.translate


DOCK_OBJECT_NAME = "CADAgentChatDock"

_HERE = os.path.dirname(os.path.abspath(__file__))
_QML_MAIN = os.path.join(_HERE, "qml", "ChatPanel.qml")


# --- Roles --------------------------------------------------------------

_ROLE_KIND = QtCore.Qt.UserRole + 1
_ROLE_TEXT = QtCore.Qt.UserRole + 2
_ROLE_META = QtCore.Qt.UserRole + 3


def _preview(value: Any, limit: int = 400) -> str:
    """Stringify arbitrary tool input/output for compact inline display."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, indent=2, default=str)
        except Exception:
            text = str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


class MessagesModel(QtCore.QAbstractListModel):
    """Flat list of chat rows exposed to QML as the ``messages`` model.

    Rows are opaque dicts with at minimum ``kind`` and ``text``. Tool and
    permission rows also carry a ``meta`` dict (tool id, previews, status,
    decision state).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        # Index lookups used when streaming updates target a specific row
        # (assistant append, tool result, permission decision).
        self._open_assistant: int | None = None
        self._open_thinking: int | None = None
        self._tool_index: dict[str, int] = {}
        self._perm_index: dict[str, int] = {}

    # --- QAbstractListModel overrides --------------------------------

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == _ROLE_KIND:
            return row.get("kind", "system")
        if role == _ROLE_TEXT:
            return row.get("text", "")
        if role == _ROLE_META:
            return row.get("meta", {})
        return None

    def roleNames(self):
        return {
            _ROLE_KIND: b"kind",
            _ROLE_TEXT: b"text",
            _ROLE_META: b"meta",
        }

    # --- Mutations ----------------------------------------------------

    def _append(self, row: dict) -> int:
        idx = len(self._rows)
        self.beginInsertRows(QtCore.QModelIndex(), idx, idx)
        self._rows.append(row)
        self.endInsertRows()
        return idx

    def _emit_changed(self, idx: int) -> None:
        mi = self.index(idx, 0)
        self.dataChanged.emit(mi, mi, [_ROLE_TEXT, _ROLE_META])

    def clear(self) -> None:
        if not self._rows:
            return
        self.beginResetModel()
        self._rows.clear()
        self._open_assistant = None
        self._open_thinking = None
        self._tool_index.clear()
        self._perm_index.clear()
        self.endResetModel()

    def add_user(self, text: str) -> None:
        self._close_assistant()
        self._collapse_thinking()
        self._append({"kind": "user", "text": text})

    def add_system(self, text: str) -> None:
        self._append({"kind": "system", "text": text})

    def add_error(self, text: str) -> None:
        self._close_assistant()
        self._append({"kind": "error", "text": text})

    def add_footer(self, text: str) -> None:
        self._close_assistant()
        self._collapse_thinking()
        self._append({"kind": "footer", "text": text})

    def append_assistant(self, chunk: str) -> None:
        self._collapse_thinking()
        if self._open_assistant is None:
            self._open_assistant = self._append({"kind": "assistant", "text": chunk})
            return
        row = self._rows[self._open_assistant]
        row["text"] = row.get("text", "") + chunk
        self._emit_changed(self._open_assistant)

    def _close_assistant(self) -> None:
        self._open_assistant = None

    def append_thinking(self, chunk: str) -> None:
        self._close_assistant()
        if self._open_thinking is None:
            self._open_thinking = self._append({"kind": "thinking", "text": chunk})
            return
        row = self._rows[self._open_thinking]
        row["text"] = row.get("text", "") + chunk
        self._emit_changed(self._open_thinking)

    def _collapse_thinking(self) -> None:
        self._open_thinking = None

    def add_tool_use(self, tool_id: str, name: str, tool_input: dict) -> None:
        self._close_assistant()
        self._collapse_thinking()
        meta = {
            "toolId": tool_id,
            "inputPreview": _preview(tool_input),
            "status": "…",
            "isError": False,
        }
        idx = self._append({"kind": "tool", "text": name, "meta": meta})
        if tool_id:
            self._tool_index[tool_id] = idx

    def set_tool_result(self, tool_id: str, content: Any, is_error: bool) -> None:
        idx = self._tool_index.pop(tool_id, None)
        if idx is None:
            self._append({
                "kind": "tool",
                "text": translate("CADAgent", "(tool result)"),
                "meta": {
                    "resultPreview": _preview(content),
                    "status": "ERR" if is_error else "OK",
                    "isError": bool(is_error),
                },
            })
            return
        row = self._rows[idx]
        meta = dict(row.get("meta") or {})
        meta.update({
            "resultPreview": _preview(content),
            "status": "ERR" if is_error else "OK",
            "isError": bool(is_error),
        })
        row["meta"] = meta
        self._emit_changed(idx)

    def add_ask(self, ask_id: str, questions: list) -> None:
        """Append an AskUserQuestion card row.

        ``questions`` is a list of ``{question, header, options:[{label,
        description}], multiSelect}`` dicts — the same shape the SDK passes in
        the ``AskUserQuestion`` tool input.
        """
        self._close_assistant()
        self._collapse_thinking()
        meta = {
            "askId": ask_id,
            "questions": list(questions or []),
            "pending": True,
        }
        self._append({"kind": "ask", "text": "", "meta": meta})

    def resolve_ask(self, ask_id: str, answers: list) -> None:
        for i, row in enumerate(self._rows):
            if row.get("kind") != "ask":
                continue
            meta = row.get("meta") or {}
            if meta.get("askId") != ask_id:
                continue
            meta = dict(meta)
            meta["pending"] = False
            meta["answers"] = answers or []
            row["meta"] = meta
            self._emit_changed(i)
            return

    def add_permission_request(
        self, req_id: str, name: str, tool_input: dict
    ) -> None:
        self._close_assistant()
        self._collapse_thinking()
        meta = {
            "reqId": req_id,
            "inputPreview": _preview(tool_input),
            "pending": True,
            "decision": "",
        }
        idx = self._append({"kind": "perm", "text": name, "meta": meta})
        self._perm_index[req_id] = idx

    def resolve_permission(self, req_id: str, allowed: bool) -> None:
        idx = self._perm_index.pop(req_id, None)
        if idx is None:
            return
        row = self._rows[idx]
        meta = dict(row.get("meta") or {})
        meta["pending"] = False
        meta["decision"] = (
            translate("CADAgent", "Approved") if allowed
            else translate("CADAgent", "Rejected")
        )
        row["meta"] = meta
        self._emit_changed(idx)


class QmlChatBridge(QtCore.QObject):
    """Slots + properties consumed by QML. Owns the model on behalf of the view."""

    busyChanged = QtCore.Signal()
    bypassChanged = QtCore.Signal()
    scrollToEnd = QtCore.Signal()

    def __init__(self, model: MessagesModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._runtime = None
        self._panel: "QmlChatPanel | None" = None
        self._busy = False
        self._bypass = False
        self._pending_perm: dict[str, asyncio.Future] = {}
        self._pending_ask: dict[str, Any] = {}  # concurrent.futures.Future

    def bind(self, panel: "QmlChatPanel", runtime) -> None:
        self._panel = panel
        self._runtime = runtime

    # --- Properties --------------------------------------------------

    @QtCore.Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    def set_busy(self, value: bool) -> None:
        if value == self._busy:
            return
        self._busy = value
        self.busyChanged.emit()

    @QtCore.Property(bool, notify=bypassChanged)
    def bypass(self) -> bool:
        return self._bypass

    def set_bypass(self, value: bool) -> None:
        if value == self._bypass:
            return
        self._bypass = value
        self.bypassChanged.emit()

    # --- Slots (QML → Python) ----------------------------------------

    @QtCore.Slot(str)
    def submit(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if self._runtime is None:
            self._model.add_error(translate("CADAgent", "Agent runtime not ready."))
            return
        self._model.add_user(text)
        self.set_busy(True)
        self._runtime.submit(text)
        self.scrollToEnd.emit()

    @QtCore.Slot()
    def stop(self) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.interrupt()
        except Exception as exc:
            self._model.add_error(str(exc))
        self.set_busy(False)

    @QtCore.Slot()
    def newChat(self) -> None:
        if self._runtime is not None and not self._runtime.start_new_session():
            self._model.add_error(
                translate("CADAgent", "Finish or stop the current turn first.")
            )
            return
        self._model.clear()
        self._model.add_system(
            translate("CADAgent", "CAD Agent ready. Ask me to model something.")
        )

    @QtCore.Slot()
    def showHistory(self) -> None:
        # Full popup deferred; enumerate sessions inline so users can see them.
        if self._panel is None:
            return
        doc = getattr(self._panel, "_bound_doc", None) or App.ActiveDocument
        entries = cad_sessions.list_sessions(doc) if doc else []
        if not entries:
            self._model.add_system(translate("CADAgent", "No prior sessions."))
            return
        lines = [
            translate("CADAgent", "Prior sessions for this document:")
        ]
        for e in entries[:10]:
            title = e.get("title") or (e.get("id", "")[:8])
            lines.append(f"  • {title}")
        self._model.add_system("\n".join(lines))

    @QtCore.Slot()
    def configureLlm(self) -> None:
        try:
            Gui.runCommand("CADAgent_ConfigureLLM")
        except Exception as exc:
            self._model.add_error(str(exc))

    @QtCore.Slot(str, bool, str)
    def decidePermission(self, req_id: str, allowed: bool, reason: str) -> None:
        fut = self._pending_perm.pop(req_id, None)
        self._model.resolve_permission(req_id, allowed)
        if fut is not None and not fut.done():
            fut.set_result(Decision(allowed=allowed, reason=reason or ""))

    @QtCore.Slot(str, str)
    def submitAnswers(self, ask_id: str, answers_json: str) -> None:
        """Called from QML when the user clicks Submit (or Skip) on an ask card.

        ``answers_json`` is a JSON-encoded list of ``{header, selected,
        skipped}`` dicts — one per question, in the same order they arrived.
        """
        try:
            answers = json.loads(answers_json) if answers_json else []
        except Exception:
            answers = []
        fut = self._pending_ask.pop(ask_id, None)
        self._model.resolve_ask(ask_id, answers)
        if fut is not None and not fut.done():
            fut.set_result(answers)

    # --- Permission request bookkeeping (called from Python) ---------

    def register_permission(
        self, req_id: str, fut: asyncio.Future, name: str, tool_input: dict
    ) -> None:
        self._pending_perm[req_id] = fut
        self._model.add_permission_request(req_id, name, tool_input)
        self.scrollToEnd.emit()

    def register_ask(self, ask_id: str, fut, questions: list) -> None:
        self._pending_ask[ask_id] = fut
        self._model.add_ask(ask_id, questions)
        self.scrollToEnd.emit()


class QmlChatPanel(QtWidgets.QWidget):
    """QWidget host for the QML ChatPanel, matching :class:`ChatPanel`'s API."""

    _instance: "QmlChatPanel | None" = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CADAgentQmlRoot")

        self._bound_doc = None
        self._current_session_id: str | None = None
        self._runtime = None

        self.model = MessagesModel(self)
        self.bridge = QmlChatBridge(self.model, self)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.view = QQuickWidget(self)
        self.view.setResizeMode(QQuickWidget.SizeRootObjectToView)
        ctx = self.view.rootContext()
        ctx.setContextProperty("bridge", self.bridge)
        ctx.setContextProperty("messages", self.model)

        if not os.path.exists(_QML_MAIN):
            msg = translate(
                "CADAgent",
                "QML UI not found at:\n{0}\n"
                "Rebuild the module (cmake --build build/debug --target CADAgent).",
            ).format(_QML_MAIN)
            App.Console.PrintError(f"CAD Agent: {msg}\n")
            label = QtWidgets.QLabel(msg, self)
            label.setStyleSheet("color:#e05757;padding:12px;font:12px monospace")
            label.setWordWrap(True)
            lay.addWidget(label)
        else:
            self.view.setSource(QtCore.QUrl.fromLocalFile(_QML_MAIN))
            lay.addWidget(self.view)

        self.model.add_system(
            translate("CADAgent", "CAD Agent ready. Ask me to model something.")
        )

    # --- Panel API (matches ChatPanel) -------------------------------

    def attach_runtime(self, runtime) -> None:
        self._runtime = runtime
        self.bridge.bind(self, runtime)
        try:
            mode = App.ParamGet(
                "User parameter:BaseApp/Preferences/Mod/CADAgent"
            ).GetString("PermissionMode", "default")
            self.bridge.set_bypass(mode == "bypassPermissions")
        except Exception:
            pass

    def append_assistant_text(self, text: str) -> None:
        self.model.append_assistant(text)
        self.bridge.scrollToEnd.emit()

    def append_thinking(self, text: str) -> None:
        self.model.append_thinking(text)
        self.bridge.scrollToEnd.emit()

    def announce_tool_use(self, tool_use_id: str, name: str, tool_input) -> None:
        # AskUserQuestion is rendered as a dedicated "ask" card (see
        # ask_user_question_threadsafe) — skip the generic tool row so we
        # don't show a raw JSON dump alongside the interactive card.
        if name == "AskUserQuestion":
            return
        self.model.add_tool_use(tool_use_id or "", name, tool_input or {})
        self.bridge.scrollToEnd.emit()

    def announce_tool_result(self, tool_use_id: str, content, is_error: bool) -> None:
        # Silently drop results for tool rows we never created (e.g. the
        # suppressed AskUserQuestion row).
        if tool_use_id and tool_use_id not in self.model._tool_index:
            return
        self.model.set_tool_result(tool_use_id or "", content, bool(is_error))
        self.bridge.scrollToEnd.emit()

    def record_result(self, msg) -> None:
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
        self.model.add_footer(text)

    def mark_turn_complete(self) -> None:
        self.bridge.set_busy(False)

    def show_error(self, message: str) -> None:
        self.model.add_error(message)

    # --- Permission bridge (called from GUI thread via PanelProxy) ---

    def request_permission_threadsafe(
        self, tool_name: str, tool_input: dict, cf_future
    ) -> None:
        req_id = uuid.uuid4().hex
        self.bridge.register_permission(req_id, cf_future, tool_name, tool_input or {})

    def ask_user_question_threadsafe(self, questions, cf_future) -> None:
        """Surface an inline AskUserQuestion card; resolve cf_future on Submit/Skip.

        Called from the GUI thread (via PanelProxy). The result set on
        ``cf_future`` is a list of ``{header, selected, skipped}`` dicts, one
        per question, which :func:`permissions.can_use_tool` maps to the
        ``answers`` dict the SDK expects.
        """
        ask_id = uuid.uuid4().hex
        self.bridge.register_ask(ask_id, cf_future, list(questions or []))


def get_or_create_dock() -> QtWidgets.QDockWidget:
    mw = Gui.getMainWindow()
    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if existing is not None:
        return existing

    dock = QtWidgets.QDockWidget(translate("CADAgent", "CAD Agent"), mw)
    dock.setObjectName(DOCK_OBJECT_NAME)
    panel = QmlChatPanel(dock)
    QmlChatPanel._instance = panel
    dock.setWidget(panel)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.resize(460, dock.height())
    return dock


def get_panel():
    return QmlChatPanel._instance
