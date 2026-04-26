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
import tempfile
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

# QQuickView is a QWindow subclass — wrap it in createWindowContainer() so
# it can live inside a dock widget while managing its own graphics context.
# This avoids the QQuickWidget "graphics API mismatch" error that occurs when
# the top-level FreeCAD window uses a different backend (e.g. Metal on macOS).
try:
    from PySide6.QtQuick import QQuickView
    from PySide6.QtQml import QQmlContext  # noqa: F401
except ImportError:  # pragma: no cover - PySide2 fallback
    from PySide2.QtQuick import QQuickView
    from PySide2.QtQml import QQmlContext  # noqa: F401

from .. import hooks as cad_hooks
from .. import sessions as cad_sessions
from ..permissions import Decision


translate = App.Qt.translate


_HERE = os.path.dirname(os.path.abspath(__file__))
_QML_MAIN = os.path.join(_HERE, "qml", "ChatPanel.qml")


# --- Roles --------------------------------------------------------------

_ROLE_KIND = QtCore.Qt.UserRole + 1
_ROLE_TEXT = QtCore.Qt.UserRole + 2
_ROLE_META = QtCore.Qt.UserRole + 3
_ROLE_ROW_ID = QtCore.Qt.UserRole + 4


_VALID_PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions")


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
        self._milestone_index: dict[str, int] = {}
        self._row_by_id: dict[str, int] = {}
        self._next_row_id: int = 0
        # TodoWrite replaces a single row in place — same open/reuse pattern
        # as the thinking ticker.
        self._todos_row: int | None = None
        # When the planner delegates to a subagent, subsequent rows inherit
        # meta.agent = <name> until end_subagent() clears it. None = main.
        self._current_agent: str | None = None

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
        if role == _ROLE_ROW_ID:
            return row.get("rowId", "")
        return None

    def roleNames(self):
        return {
            _ROLE_KIND: b"kind",
            _ROLE_TEXT: b"text",
            _ROLE_META: b"meta",
            _ROLE_ROW_ID: b"rowId",
        }

    # --- Mutations ----------------------------------------------------

    def _alloc_row_id(self) -> str:
        rid = f"r{self._next_row_id}"
        self._next_row_id += 1
        return rid

    def _append(self, row: dict) -> int:
        # Every row gets a stable rowId; callers that need in-place updates
        # keep it (via the _row_by_id map or a kind-specific index dict).
        row.setdefault("rowId", self._alloc_row_id())
        # Inherit meta.agent from the active subagent span, if any.
        if self._current_agent:
            meta = dict(row.get("meta") or {})
            meta.setdefault("agent", self._current_agent)
            row["meta"] = meta
        idx = len(self._rows)
        self.beginInsertRows(QtCore.QModelIndex(), idx, idx)
        self._rows.append(row)
        self.endInsertRows()
        self._row_by_id[row["rowId"]] = idx
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
        self._milestone_index.clear()
        self._row_by_id.clear()
        self._todos_row = None
        self._current_agent = None
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
            self._open_assistant = self._append({
                "kind": "assistant",
                "text": chunk,
                "meta": {"isPartial": True},
            })
            return
        row = self._rows[self._open_assistant]
        row["text"] = row.get("text", "") + chunk
        self._emit_changed(self._open_assistant)

    def mark_assistant_final(self) -> None:
        """Flip the currently-open assistant row from streaming to final."""
        if self._open_assistant is None:
            return
        row = self._rows[self._open_assistant]
        meta = dict(row.get("meta") or {})
        if not meta.get("isPartial"):
            return
        meta["isPartial"] = False
        row["meta"] = meta
        self._emit_changed(self._open_assistant)

    def _close_assistant(self) -> None:
        if self._open_assistant is not None:
            # A new row is about to push the assistant row out — the prior
            # assistant text is finalised by definition.
            row = self._rows[self._open_assistant]
            meta = dict(row.get("meta") or {})
            if meta.get("isPartial"):
                meta["isPartial"] = False
                row["meta"] = meta
                self._emit_changed(self._open_assistant)
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

    # --- New scaffolding row kinds -----------------------------------
    #
    # Milestone banner rows are emitted by the planner (Move 2). The same
    # milestoneId is upserted as status transitions (pending → active →
    # done|failed) so the row updates in place rather than appending a new
    # line on every progress tick.
    def upsert_milestone(
        self,
        milestone_id: str,
        title: str,
        status: str,
        index: int | None = None,
        total: int | None = None,
    ) -> None:
        self._close_assistant()
        self._collapse_thinking()
        idx = self._milestone_index.get(milestone_id)
        meta = {
            "milestoneId": milestone_id,
            "status": status,
            "index": index,
            "total": total,
        }
        if idx is None:
            new_idx = self._append(
                {"kind": "milestone", "text": title, "meta": meta}
            )
            self._milestone_index[milestone_id] = new_idx
            return
        row = self._rows[idx]
        prev_meta = dict(row.get("meta") or {})
        prev_meta.update({k: v for k, v in meta.items() if v is not None})
        row["meta"] = prev_meta
        if title:
            row["text"] = title
        self._emit_changed(idx)

    # Verification rows are children of a tool row. PostToolUse hook fires
    # these; if the parent tool row is gone (e.g. cleared) we still append
    # the verification so the user sees the hook output.
    def add_verification(
        self,
        parent_tool_id: str,
        checks: list,
        ok: bool,
    ) -> None:
        meta = {
            "parentToolId": parent_tool_id or "",
            "checks": list(checks or []),
            "ok": bool(ok),
        }
        idx = self._append({"kind": "verification", "text": "", "meta": meta})
        # Link to parent tool row (may have already closed → tool_index is
        # popped on set_tool_result, so look through the rows instead).
        if parent_tool_id:
            for i, row in enumerate(self._rows):
                if row.get("kind") != "tool":
                    continue
                rmeta = row.get("meta") or {}
                if rmeta.get("toolId") != parent_tool_id:
                    continue
                rmeta = dict(rmeta)
                children = list(rmeta.get("children") or [])
                children.append(self._rows[idx]["rowId"])
                rmeta["children"] = children
                row["meta"] = rmeta
                self._emit_changed(i)
                break

    def add_decision(
        self,
        decision_id: str,
        title: str,
        rationale: str = "",
        alternatives: list | None = None,
        tags: list | None = None,
    ) -> None:
        self._close_assistant()
        self._collapse_thinking()
        meta = {
            "decisionId": decision_id,
            "rationale": rationale or "",
            "alternatives": list(alternatives or []),
            "tags": list(tags or []),
            "collapsed": True,
        }
        self._append({"kind": "decision", "text": title, "meta": meta})

    def add_plan_file(self, path: str, markdown: str) -> None:
        """Append a PlanFileRow — the plan the agent persisted via
        ``exit_plan_mode``. The row shows the markdown and an Approve hint."""
        self._close_assistant()
        self._collapse_thinking()
        self._append({
            "kind": "plan_file",
            "text": markdown or "",
            "meta": {"path": path or "", "approved": False},
        })

    def add_edit_approval(
        self, req_id: str, summary: str, script: str
    ) -> None:
        self._close_assistant()
        self._collapse_thinking()
        meta = {
            "reqId": req_id,
            "summary": summary or "",
            "script": script or "",
            "pending": True,
            "decision": "",
        }
        idx = self._append({"kind": "edit_approval", "text": summary or "", "meta": meta})
        # Re-use the perm_index so _edit_approval can close in-place.
        self._perm_index[f"edit:{req_id}"] = idx

    def resolve_edit_approval(self, req_id: str, allowed: bool) -> None:
        idx = self._perm_index.pop(f"edit:{req_id}", None)
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

    def add_compaction(
        self,
        tokens_before: int | None,
        tokens_after: int | None,
        archive_path: str = "",
    ) -> None:
        self._close_assistant()
        self._collapse_thinking()
        meta = {
            "tokensBefore": tokens_before,
            "tokensAfter": tokens_after,
            "archivePath": archive_path or "",
        }
        self._append({"kind": "compaction", "text": "", "meta": meta})

    def add_hook_event(
        self,
        event: str,
        message: str | None,
        decision: str | None,
    ) -> None:
        self._close_assistant()
        self._collapse_thinking()
        self._append({
            "kind": "hook_event",
            "text": message or "",
            "meta": {
                "event": event or "",
                "message": message or "",
                "decision": decision or "",
            },
        })

    # Subagent span — begin_subagent adds a header row and sets the
    # inherited agent attribution for every row that follows until
    # end_subagent() clears it.
    def begin_subagent(self, agent: str, task: str) -> None:
        self._close_assistant()
        self._collapse_thinking()
        # Add the header row before flipping _current_agent so the header
        # itself is attributed to the spawning context, not the child.
        self._append({
            "kind": "subagent",
            "text": task or "",
            "meta": {"agent": agent or "", "action": "start"},
        })
        self._current_agent = agent or None

    def end_subagent(self) -> None:
        agent = self._current_agent
        self._current_agent = None
        self._append({
            "kind": "subagent",
            "text": "",
            "meta": {"agent": agent or "", "action": "end"},
        })

    def toggle_collapse(self, row_id: str) -> None:
        idx = self._row_by_id.get(row_id)
        if idx is None:
            return
        row = self._rows[idx]
        meta = dict(row.get("meta") or {})
        meta["collapsed"] = not bool(meta.get("collapsed"))
        row["meta"] = meta
        self._emit_changed(idx)

    # TodoWrite surface — a single reusable "todos" row that is upserted
    # every time the model calls the TodoWrite tool, Claude-Code style. We
    # render the checklist in QML (``todosRow``) instead of as a raw tool row.
    def upsert_todos(self, todos: list) -> None:
        norm: list[dict] = []
        for t in todos or []:
            if not isinstance(t, dict):
                continue
            norm.append({
                "content": str(t.get("content") or ""),
                "status": str(t.get("status") or "pending"),
                "activeForm": str(t.get("activeForm") or ""),
            })
        if getattr(self, "_todos_row", None) is not None:
            idx = self._todos_row
            if 0 <= idx < len(self._rows):
                row = self._rows[idx]
                meta = dict(row.get("meta") or {})
                meta["todos"] = norm
                row["meta"] = meta
                self._emit_changed(idx)
                return
        self._close_assistant()
        self._collapse_thinking()
        self._todos_row = self._append({
            "kind": "todos",
            "text": "",
            "meta": {"todos": norm},
        })

    # --- Persistence -------------------------------------------------

    def snapshot(self) -> list[dict]:
        """Return a deep-copied list of rows suitable for JSON persistence."""
        return [dict(r, meta=dict(r.get("meta") or {})) for r in self._rows]

    def load_snapshot(self, rows: list) -> None:
        """Replace model contents with ``rows`` (previously from snapshot()).

        Rebuilds internal indexes so open tool / milestone / permission rows
        still update in place if a later turn mutates them.
        """
        self.beginResetModel()
        self._rows.clear()
        self._open_assistant = None
        self._open_thinking = None
        self._tool_index.clear()
        self._perm_index.clear()
        self._milestone_index.clear()
        self._row_by_id.clear()
        self._todos_row = None
        self._current_agent = None
        max_n = -1
        for src in rows or []:
            if not isinstance(src, dict):
                continue
            row = {
                "kind": src.get("kind") or "system",
                "text": src.get("text") or "",
                "meta": dict(src.get("meta") or {}),
                "rowId": src.get("rowId") or "",
            }
            if not row["rowId"]:
                row["rowId"] = f"r{max(0, max_n + 1)}"
            rid = row["rowId"]
            if rid.startswith("r"):
                try:
                    max_n = max(max_n, int(rid[1:]))
                except ValueError:
                    pass
            self._rows.append(row)
            idx = len(self._rows) - 1
            self._row_by_id[rid] = idx
            kind = row["kind"]
            meta = row["meta"]
            if kind == "tool":
                tid = meta.get("toolId")
                if tid and meta.get("status") == "…":
                    self._tool_index[tid] = idx
            elif kind == "perm":
                pid = meta.get("reqId")
                if pid and meta.get("pending"):
                    self._perm_index[pid] = idx
            elif kind == "milestone":
                mid = meta.get("milestoneId")
                if mid:
                    self._milestone_index[mid] = idx
            elif kind == "todos":
                self._todos_row = idx
        self._next_row_id = max_n + 1
        self.endResetModel()


class QmlChatBridge(QtCore.QObject):
    """Slots + properties consumed by QML. Owns the model on behalf of the view."""

    busyChanged = QtCore.Signal()
    bypassChanged = QtCore.Signal()
    permissionModeChanged = QtCore.Signal()
    agentChanged = QtCore.Signal()
    milestoneSummaryChanged = QtCore.Signal()
    scrollToEnd = QtCore.Signal()
    attachmentsChanged = QtCore.Signal()

    def __init__(self, model: MessagesModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._runtime = None
        self._panel: "QmlChatPanel | None" = None
        self._busy = False
        self._bypass = False
        self._permission_mode: str = "default"
        self._current_agent: str = "main"
        self._milestone_summary: str = ""
        self._pending_perm: dict[str, asyncio.Future] = {}
        self._pending_ask: dict[str, Any] = {}  # concurrent.futures.Future
        self._pending_edit: dict[str, Any] = {}  # concurrent.futures.Future
        self._attachments: list[dict[str, str]] = []  # [{"path","name"}, ...]

    def bind(self, panel: "QmlChatPanel", runtime) -> None:
        self._panel = panel
        self._runtime = runtime
        proxy = getattr(runtime, "_proxy", None)
        sig = getattr(proxy, "hookEvent", None) if proxy is not None else None
        if sig is not None:
            try:
                sig.connect(self._on_hook_event)
            except Exception:
                pass

    @QtCore.Slot(str, object, object)
    def _on_hook_event(self, event_name, payload, result) -> None:
        if not isinstance(result, dict):
            return
        decision = result.get("decision")
        message = result.get("message")
        if decision != "block" and not (isinstance(message, str) and message.strip()):
            return
        self._model.add_hook_event(
            event_name or "",
            message if isinstance(message, str) else None,
            decision if isinstance(decision, str) else None,
        )
        self.scrollToEnd.emit()

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

    @QtCore.Property(str, notify=permissionModeChanged)
    def permissionMode(self) -> str:
        return self._permission_mode

    def set_permission_mode(self, mode: str, persist: bool = True) -> None:
        mode = mode if mode in _VALID_PERMISSION_MODES else "default"
        if mode == self._permission_mode:
            # Still ensure the derived bypass flag matches on first call.
            desired = (mode == "bypassPermissions")
            if desired != self._bypass:
                self.set_bypass(desired)
            return
        self._permission_mode = mode
        if persist:
            try:
                App.ParamGet(
                    "User parameter:BaseApp/Preferences/Mod/CADAgent"
                ).SetString("PermissionMode", mode)
            except Exception:
                pass
            # Tear down the live SDK client so the next turn re-reads the
            # new mode. No-op if the user switches mid-turn.
            if self._runtime is not None:
                try:
                    self._runtime.rebuild_for_mode()
                except Exception:
                    pass
        self.permissionModeChanged.emit()
        self.set_bypass(mode == "bypassPermissions")

    @QtCore.Property(str, notify=agentChanged)
    def currentAgent(self) -> str:
        return self._current_agent

    def set_current_agent(self, agent: str) -> None:
        agent = agent or "main"
        if agent == self._current_agent:
            return
        self._current_agent = agent
        self.agentChanged.emit()

    @QtCore.Property(str, notify=milestoneSummaryChanged)
    def milestoneSummary(self) -> str:
        return self._milestone_summary

    def set_milestone_summary(self, text: str) -> None:
        text = text or ""
        if text == self._milestone_summary:
            return
        self._milestone_summary = text
        self.milestoneSummaryChanged.emit()

    # --- Slots (QML → Python) ----------------------------------------

    @QtCore.Slot(str)
    def submit(self, text: str) -> None:
        text = (text or "").strip()
        attachments = [a["path"] for a in self._attachments]
        if not text and not attachments:
            return
        if self._runtime is None:
            self._model.add_error(translate("CADAgent", "Agent runtime not ready."))
            return
        # Slash commands are intercepted here so the user prompt never reaches
        # the LLM when it's really a local directive.
        if text.startswith("/"):
            if self._handle_slash(text):
                self._clear_attachments()
                self.scrollToEnd.emit()
                return
        if self._panel is not None and not self._panel._first_prompt:
            self._panel._first_prompt = text
        display = text
        if attachments:
            tag = translate("CADAgent", "[{0} image(s) attached]").format(
                len(attachments)
            )
            display = f"{text}\n{tag}" if text else tag
        self._model.add_user(display)
        self.set_busy(True)
        self._runtime.submit(text, attachments)
        self._clear_attachments()
        self.scrollToEnd.emit()

    # --- Clipboard / attachments ------------------------------------

    @QtCore.Property(str, notify=attachmentsChanged)
    def attachmentsJson(self) -> str:
        return json.dumps(self._attachments)

    @QtCore.Slot(result=bool)
    def tryPasteImage(self) -> bool:
        """Save any image on the clipboard to a temp PNG and attach it.

        Returns True when an image was consumed (the QML caller should then
        swallow the Ctrl+V so the default text-paste path doesn't also run).
        """
        app = QtWidgets.QApplication.instance()
        if app is None:
            return False
        clip = app.clipboard()
        md = clip.mimeData()
        if md is None or not md.hasImage():
            return False
        image = clip.image()
        if image.isNull():
            return False
        fd, path = tempfile.mkstemp(prefix="cadagent_paste_", suffix=".png")
        os.close(fd)
        if not image.save(path, "PNG"):
            try:
                os.unlink(path)
            except OSError:
                pass
            return False
        self._attachments.append(
            {"path": path, "name": os.path.basename(path)}
        )
        self.attachmentsChanged.emit()
        return True

    @QtCore.Slot(str)
    def removeAttachment(self, path: str) -> None:
        before = len(self._attachments)
        self._attachments = [a for a in self._attachments if a["path"] != path]
        if len(self._attachments) != before:
            try:
                os.unlink(path)
            except OSError:
                pass
            self.attachmentsChanged.emit()

    def _clear_attachments(self) -> None:
        if not self._attachments:
            return
        self._attachments = []
        self.attachmentsChanged.emit()

    def _handle_slash(self, raw: str) -> bool:
        """Dispatch slash commands. Returns True if consumed."""
        parts = raw[1:].strip().split(None, 1)
        if not parts:
            return False
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        if cmd in ("plan",):
            # Pin the next turn to plan mode + forward the rest as the prompt.
            if rest:
                if self._runtime is not None:
                    self._runtime._mode_override = "plan"
                    if self._runtime.client is not None and self._runtime._loop is not None:
                        asyncio.run_coroutine_threadsafe(
                            self._runtime._aclose(), self._runtime._loop
                        )
                self._model.add_user(rest)
                self._model.add_system(
                    translate("CADAgent", "Plan mode active for this turn — the agent will research and call exit_plan_mode.")
                )
                self.set_busy(True)
                self._runtime.submit(rest)
            else:
                self.set_permission_mode("plan")
                self._model.add_system(
                    translate("CADAgent", "Permission mode set to plan.")
                )
            return True
        if cmd in ("review", "sketch", "assemble"):
            prompt_map = {
                "review": "Use the reviewer subagent to audit the current document and report issues.",
                "sketch": f"Use the sketcher subagent to: {rest or 'design a sketch per the active plan milestone.'}",
                "assemble": f"Use the assembler subagent to: {rest or 'perform the next assembly step.'}",
            }
            prompt = prompt_map[cmd]
            self._model.add_user(f"/{cmd} {rest}".strip())
            self.set_busy(True)
            self._runtime.submit(prompt)
            return True
        if cmd in ("resume",):
            # The HistoryPopup is driven by bridge.listSessions/openSession. We
            # can't open it from Python, but we can point the user at it.
            self._model.add_system(
                translate("CADAgent", "Open the history popup (clock icon) to resume a prior session.")
            )
            return True
        if cmd in ("compact",):
            self._run_local_compaction()
            return True
        if cmd in ("clear", "new"):
            self.newChat()
            return True
        if cmd in ("help",):
            self._model.add_system(
                translate(
                    "CADAgent",
                    "Commands: /plan <task>  /review  /sketch <desc>  /assemble <desc>  "
                    "/resume  /compact  /clear  /help",
                )
            )
            return True
        return False

    def _run_local_compaction(self) -> None:
        """Collapse rows older than the last ~30 into a single CompactionRow.

        This is a local, no-LLM compaction: the model's own context is handled
        by the SDK's session resume; this surface just keeps the transcript
        scrollable once it grows past a few hundred rows.
        """
        rows = self._model._rows
        cutoff = len(rows) - 30
        if cutoff <= 3:
            self._model.add_system(
                translate("CADAgent", "Nothing to compact yet.")
            )
            return
        # Preserve the tail; replace the head with a single compaction row.
        head = rows[:cutoff]
        tail = rows[cutoff:]
        self._model.beginResetModel()
        self._model._rows = []
        # Rebuild indices from scratch; the tail rows keep their original
        # rowIds and meta, so in-flight tool/perm rows still resolve.
        self._model._open_assistant = None
        self._model._open_thinking = None
        self._model._tool_index.clear()
        self._model._perm_index.clear()
        self._model._milestone_index.clear()
        self._model._row_by_id.clear()
        self._model._todos_row = None
        self._model._current_agent = None
        # Compaction summary row first.
        summary_row = {
            "kind": "compaction",
            "text": "",
            "meta": {
                "tokensBefore": None,
                "tokensAfter": None,
                "archivePath": "",
                "summary": translate(
                    "CADAgent", "{0} earlier rows collapsed."
                ).format(len(head)),
            },
            "rowId": self._model._alloc_row_id(),
        }
        self._model._rows.append(summary_row)
        self._model._row_by_id[summary_row["rowId"]] = 0
        # Re-append tail.
        for row in tail:
            self._model._rows.append(row)
            self._model._row_by_id[row.get("rowId", "")] = len(self._model._rows) - 1
        self._model.endResetModel()
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
        if self._panel is not None:
            self._panel._first_prompt = None
            self._panel._current_session_id = None
        self._model.clear()
        self._model.add_system(
            translate("CADAgent", "CAD Agent ready. Ask me to model something.")
        )

    @QtCore.Slot(result=str)
    def listSessions(self) -> str:
        """Return the session index for the active doc as a JSON string.

        Emitted to QML so the history popup can populate its ListView. Each
        entry carries id/title/first_prompt/updated_at/turn_count.
        """
        if self._panel is None:
            return "[]"
        doc = getattr(self._panel, "_bound_doc", None) or App.ActiveDocument
        if doc is None:
            return "[]"
        try:
            entries = cad_sessions.list_sessions(doc)
        except Exception:
            return "[]"
        return json.dumps(entries)

    @QtCore.Slot(str)
    def openSession(self, session_id: str) -> None:
        if self._panel is None or not session_id:
            return
        self._panel.open_session(session_id)

    @QtCore.Slot(str)
    def deleteSession(self, session_id: str) -> None:
        if self._panel is None or not session_id:
            return
        doc = getattr(self._panel, "_bound_doc", None) or App.ActiveDocument
        if doc is None:
            return
        try:
            cad_sessions.delete(doc, session_id)
        except Exception:
            pass
        if self._panel._current_session_id == session_id:
            # Close the live SDK client too; otherwise the next turn would
            # re-persist this sid and resurrect the entry we just deleted.
            if self._runtime is not None:
                self._runtime.start_new_session()
            self._panel._current_session_id = None
            self._panel._first_prompt = None
            self._model.clear()
            self._model.add_system(
                translate("CADAgent", "CAD Agent ready. Ask me to model something.")
            )

    @QtCore.Slot()
    def configureLlm(self) -> None:
        try:
            Gui.runCommand("CADAgent_ConfigureLLM")
        except Exception as exc:
            self._model.add_error(str(exc))

    @QtCore.Slot(result=str)
    def activeHooksSettings(self) -> str:
        """Return ``{source, settings}`` JSON for the topbar hooks viewer."""
        doc_dir: str | None = None
        if self._panel is not None:
            doc = getattr(self._panel, "_bound_doc", None) or App.ActiveDocument
            path = getattr(doc, "FileName", "") if doc is not None else ""
            if path:
                try:
                    doc_dir = os.path.dirname(path) or None
                except (TypeError, ValueError):
                    doc_dir = None
        try:
            source, settings = cad_hooks.settings_source(doc_dir)
        except Exception:
            source, settings = "none", {}
        return json.dumps({"source": source, "settings": settings})

    @QtCore.Slot(str)
    def setPermissionMode(self, mode: str) -> None:
        """Called from the topbar chip popup. Persists the new mode and
        applies it to the next turn — the runtime re-reads the preference
        inside ``_ensure_client`` so we don't need to mutate the live SDK
        options."""
        prev = self._permission_mode
        self.set_permission_mode(mode)
        if prev != self._permission_mode:
            self._model.add_system(
                translate("CADAgent", "Permission mode: {0}").format(
                    self._permission_mode
                )
            )

    @QtCore.Slot(str)
    def toggleCollapse(self, row_id: str) -> None:
        self._model.toggle_collapse(row_id)

    @QtCore.Slot(str, bool, str)
    def decidePermission(self, req_id: str, allowed: bool, reason: str) -> None:
        """Back-compat two-state entry point (yes / no).

        Scope defaults to ``"once"``. QML that wants "Allow always" should
        call :meth:`decidePermissionScoped` instead.
        """
        self.decidePermissionScoped(req_id, allowed, "once", reason)

    @QtCore.Slot(str, bool, str, str)
    def decidePermissionScoped(
        self, req_id: str, allowed: bool, scope: str, reason: str
    ) -> None:
        if scope not in ("once", "always", "deny"):
            scope = "once" if allowed else "deny"
        fut = self._pending_perm.pop(req_id, None)
        self._model.resolve_permission(req_id, allowed)
        if fut is not None and not fut.done():
            fut.set_result(
                Decision(allowed=allowed, reason=reason or "", scope=scope)
            )

    @QtCore.Slot(str, bool)
    def decideEditApproval(self, req_id: str, allowed: bool) -> None:
        fut = self._pending_edit.pop(req_id, None)
        self._model.resolve_edit_approval(req_id, allowed)
        if fut is not None and not fut.done():
            fut.set_result(
                Decision(allowed=allowed, scope=("once" if allowed else "deny"))
            )

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

    def register_edit_approval(
        self, req_id: str, fut, summary: str, script: str
    ) -> None:
        self._pending_edit[req_id] = fut
        self._model.add_edit_approval(req_id, summary, script)
        self.scrollToEnd.emit()


class QmlChatPanel(QtWidgets.QWidget):
    """QWidget host for the QML ChatPanel, matching :class:`ChatPanel`'s API."""

    _instance: "QmlChatPanel | None" = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CADAgentQmlRoot")

        self._bound_doc = None
        self._current_session_id: str | None = None
        self._first_prompt: str | None = None
        self._runtime = None

        self.model = MessagesModel(self)
        self.bridge = QmlChatBridge(self.model, self)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.view = QQuickView()
        self.view.setResizeMode(QQuickView.SizeRootObjectToView)
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
            container = QtWidgets.QWidget.createWindowContainer(self.view, self)
            container.setMinimumSize(200, 100)
            container.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Expanding,
            )
            lay.addWidget(container)

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
            self.bridge.set_permission_mode(mode, persist=False)
        except Exception:
            pass

    def append_assistant_text(self, text: str) -> None:
        self.model.append_assistant(text)
        self.bridge.scrollToEnd.emit()

    def append_thinking(self, text: str) -> None:
        self.model.append_thinking(text)
        self.bridge.scrollToEnd.emit()

    def announce_tool_use(self, tool_use_id: str, name: str, tool_input) -> None:
        # AskUserQuestion / TodoWrite / plan_* are rendered as dedicated
        # surfaces (ask card, todos checklist, milestone rows). Skip the
        # generic tool row so we don't show a raw JSON dump alongside.
        if name == "AskUserQuestion" or name == "TodoWrite":
            return
        if name.startswith("plan_"):
            return
        self.model.add_tool_use(tool_use_id or "", name, tool_input or {})
        self.bridge.scrollToEnd.emit()

    def update_todos(self, todos) -> None:
        if not isinstance(todos, list):
            return
        self.model.upsert_todos(todos)
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
        self._persist_transcript()

    def on_session_changed(self, session_id: str) -> None:
        """Runtime hands us the SDK's session id at end of each turn."""
        if not session_id:
            return
        self._current_session_id = session_id

    def _active_doc(self):
        return self._bound_doc or App.ActiveDocument

    def _persist_transcript(self) -> None:
        sid = self._current_session_id
        doc = self._active_doc()
        if not sid or doc is None:
            return
        rows = self.model.snapshot()
        try:
            cad_sessions.save_rows(doc, sid, rows)
            cad_sessions.record_turn(doc, sid, self._first_prompt)
        except Exception as exc:
            App.Console.PrintWarning(
                f"CAD Agent: failed to persist session {sid}: {exc}\n"
            )

    def open_session(self, session_id: str) -> None:
        """Replay ``session_id``'s saved rows and ask the runtime to resume it."""
        doc = self._active_doc()
        if doc is None:
            self.show_error(translate("CADAgent", "No active document."))
            return
        if self._runtime is None:
            self.show_error(translate("CADAgent", "Agent runtime not ready."))
            return
        if not self._runtime.resume_session(session_id):
            self.show_error(
                translate("CADAgent", "Finish or stop the current turn first.")
            )
            return
        rows = cad_sessions.load_rows(doc, session_id)
        self.model.load_snapshot(rows)
        entry = cad_sessions.find(doc, session_id) or {}
        self._current_session_id = session_id
        self._first_prompt = entry.get("first_prompt") or None
        title = entry.get("title") or session_id[:8]
        self.model.add_system(
            translate("CADAgent", "Resumed session: {0}").format(title)
        )
        self.bridge.scrollToEnd.emit()

    def show_error(self, message: str) -> None:
        self.model.add_error(message)

    # --- New scaffolding events (GUI-thread entry points) ------------
    #
    # Runtime's _PanelProxy signals fan into these. Each does exactly one
    # thing: mutate the model and nudge the view. Never called off the GUI
    # thread (the proxy's QueuedConnection takes care of marshaling).
    def mark_assistant_final(self) -> None:
        self.model.mark_assistant_final()

    def upsert_milestone(
        self,
        milestone_id: str,
        title: str,
        status: str,
        index,
        total,
    ) -> None:
        self.model.upsert_milestone(
            milestone_id, title, status,
            index if isinstance(index, int) else None,
            total if isinstance(total, int) else None,
        )
        # Topbar pip: show "◆ i/N — title" for the last non-done milestone.
        if status in ("active", "pending") and title:
            if isinstance(index, int) and isinstance(total, int):
                self.bridge.set_milestone_summary(f"◆ {index}/{total} {title}")
            else:
                self.bridge.set_milestone_summary(f"◆ {title}")
        elif status in ("done", "failed"):
            # Clear the pip when the whole plan is at index == total.
            if isinstance(index, int) and isinstance(total, int) and index >= total:
                self.bridge.set_milestone_summary("")
        self.bridge.scrollToEnd.emit()

    def emit_verification(
        self,
        parent_tool_id: str,
        payload: Any,
    ) -> None:
        payload = payload if isinstance(payload, dict) else {}
        self.model.add_verification(
            parent_tool_id,
            payload.get("checks") or [],
            bool(payload.get("ok", True)),
        )
        self.bridge.scrollToEnd.emit()

    def emit_decision(self, row_id_hint: str, payload: Any) -> None:
        payload = payload if isinstance(payload, dict) else {}
        self.model.add_decision(
            payload.get("decisionId") or row_id_hint or "",
            payload.get("title") or "",
            payload.get("rationale") or "",
            payload.get("alternatives") or [],
            payload.get("tags") or [],
        )
        self.bridge.scrollToEnd.emit()

    def emit_compaction(self, payload: Any) -> None:
        payload = payload if isinstance(payload, dict) else {}
        self.model.add_compaction(
            payload.get("tokensBefore"),
            payload.get("tokensAfter"),
            payload.get("archivePath") or "",
        )
        self.bridge.scrollToEnd.emit()

    def emit_subagent_span(self, action: str, agent: str, task: str) -> None:
        if action == "start":
            self.model.begin_subagent(agent, task)
            self.bridge.set_current_agent(agent or "main")
        else:
            self.model.end_subagent()
            self.bridge.set_current_agent("main")
        self.bridge.scrollToEnd.emit()

    def on_plan_file(self, path: str, markdown: str) -> None:
        self.model.add_plan_file(path, markdown)
        self.bridge.scrollToEnd.emit()

    def on_plan_exited(self) -> None:
        self.model.add_system(
            translate("CADAgent", "Exited plan mode — execution enabled.")
        )
        self.bridge.set_permission_mode("default", persist=False)
        self.bridge.scrollToEnd.emit()

    def request_edit_approval_threadsafe(
        self, req_id: str, summary: str, script: str, cf_future
    ) -> None:
        self.bridge.register_edit_approval(req_id, cf_future, summary, script)

    def set_stream_state(self, row_id: str, is_partial: bool) -> None:
        # Today only the open assistant row streams; the row_id argument is
        # reserved for the eventual per-row version used once subagents
        # interleave their own streams.
        if not is_partial:
            self.model.mark_assistant_final()

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


CADAGENT_HOST_OBJECT_NAME = "CAD Agent"


def _find_host_widget():
    """Locate the C++ ``Gui::CADAgentView`` host registered by MainWindow.

    The host is created in ``MainWindow::setupCADAgentView`` and wrapped by a
    ``QDockWidget`` whose ``objectName`` is also ``"CAD Agent"`` (set by
    ``DockWindowManager::addDockWindow``). We find the QDockWidget first and
    return its ``widget()`` — the inner CADAgentView.
    """
    mw = Gui.getMainWindow()
    if mw is None:
        return None
    for dw in mw.findChildren(QtWidgets.QDockWidget):
        if dw.objectName() == CADAGENT_HOST_OBJECT_NAME:
            inner = dw.widget()
            if inner is not None:
                return inner
    # Last-ditch: any widget with the host objectName that isn't a QDockWidget.
    for w in mw.findChildren(QtWidgets.QWidget, CADAGENT_HOST_OBJECT_NAME):
        if not isinstance(w, QtWidgets.QDockWidget):
            return w
    return None


def attach_panel_to_host():
    """Construct the QML chat panel and inject it into the C++ host shell.

    Idempotent: if a panel is already attached, returns it unchanged.
    Returns the panel or ``None`` if the host is unavailable (e.g. running
    against a FreeCAD build that doesn't ship the CADAgentView shim).
    """
    if QmlChatPanel._instance is not None:
        return QmlChatPanel._instance

    host = _find_host_widget()
    if host is None:
        App.Console.PrintError(
            "CAD Agent: host dock 'CAD Agent' not found. "
            "Rebuild FreeCAD against the current source so MainWindow "
            "registers Std_CADAgentView.\n"
        )
        return None

    panel = QmlChatPanel(host)
    panel.setMinimumWidth(360)
    QmlChatPanel._instance = panel

    # Q_INVOKABLE setContentWidget reparents and replaces the placeholder.
    set_content = getattr(host, "setContentWidget", None)
    if callable(set_content):
        set_content(panel)
    else:
        # Fallback: drop into the host's layout directly.
        layout = host.layout()
        if layout is not None:
            # Remove any placeholder children first.
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            panel.setParent(host)
            layout.addWidget(panel)
        else:
            panel.setParent(host)
    return panel


def get_panel():
    return QmlChatPanel._instance
