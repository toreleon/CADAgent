# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qt signal marshalling between the asyncio worker thread and the panel.

``PanelProxy`` is a ``QObject`` whose signals fire on the asyncio thread
and are auto-marshalled to the Qt main thread via Qt's queued
connection. The QML panel binds slots to these signals; the runtime
``emit`` s on the worker thread without touching Qt directly.

Step 9 moves the class verbatim out of ``cli/dock_runtime.py`` (where
it was named ``_PanelProxy``) and renames it ``PanelProxy`` since it
now crosses a module boundary. Reserved-for-future signals stay for
back-compat; Step 17 audits and prunes the truly unused ones.
"""

from __future__ import annotations

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore

from ..tools import short_name


class PanelProxy(QtCore.QObject):
    """Marshals messages from the worker asyncio thread onto the GUI thread.

    Mirrors the signal surface the QML panel binds to in
    :mod:`agent.ui.qml_panel`. Signals not produced by the CLI agent (e.g.
    milestone/verification/decision events) are still declared so the
    panel's ``hasattr`` connects don't fail; they simply never fire.
    """

    assistantText = QtCore.Signal(str)
    thinking = QtCore.Signal(str)
    toolUse = QtCore.Signal(str, str, object)
    toolResult = QtCore.Signal(str, object, bool)
    resultMsg = QtCore.Signal(object)
    turnComplete = QtCore.Signal()
    error = QtCore.Signal(str)
    permissionRequest = QtCore.Signal(str, object, object)
    askUserQuestion = QtCore.Signal(object, object)
    sessionChanged = QtCore.Signal(str)

    # Reserved for future parity with the deleted integrated runtime.
    milestoneUpsert = QtCore.Signal(str, str, str, object, object)
    verificationResult = QtCore.Signal(str, object)
    decisionRecorded = QtCore.Signal(str, object)
    compactionEvent = QtCore.Signal(object)
    contextUsage = QtCore.Signal(int, int)
    compactingChanged = QtCore.Signal(bool)
    subagentSpan = QtCore.Signal(str, str, str)
    permissionModeChanged = QtCore.Signal(str)
    streamState = QtCore.Signal(str, bool)
    todosUpdate = QtCore.Signal(object)
    # Plan-mode scaffolding (M1).
    planFile = QtCore.Signal(str, str)  # (path, markdown)
    planExited = QtCore.Signal()
    # Edit-approval scaffolding (M3).
    editApprovalRequest = QtCore.Signal(str, str, str, object)  # (reqId, summary, script, cf_future)
    # Hook lifecycle event — (event_name, payload_dict, result_dict). Consumed
    # by W2-E to render hook activity rows; safe to leave unconnected.
    hookEvent = QtCore.Signal(str, object, object)
    # Active document changed — fires when the runtime's tracked workspace
    # path moves to a new document (or to None). Consumed by W2-D's
    # WorkspaceChip to refresh its label.
    activeDocChanged = QtCore.Signal(str)
    # Worker-thread rewind asks the GUI thread to reload the active document
    # from disk after a checkpoint restore. Path is the .FCStd file.
    docReloadRequested = QtCore.Signal(str)
    # Mode suggestion (Step 14). The runtime emits when the user's prompt
    # looks like it should shift modes — UI surfaces a dismissible chip
    # ("Switch to Ask?"). Never auto-flips. Args: (suggested_mode, reason).
    modeSuggested = QtCore.Signal(str, str)

    def __init__(self, panel):
        super().__init__(panel)
        self._panel = panel
        self.assistantText.connect(panel.append_assistant_text)
        self.thinking.connect(panel.append_thinking)
        self.toolUse.connect(panel.announce_tool_use)
        self.toolResult.connect(panel.announce_tool_result)
        self.resultMsg.connect(panel.record_result)
        self.turnComplete.connect(panel.mark_turn_complete)
        self.error.connect(panel.show_error)
        self.permissionRequest.connect(self._on_permission_request)
        self.askUserQuestion.connect(self._on_ask_user_question)
        if hasattr(panel, "on_session_changed"):
            self.sessionChanged.connect(panel.on_session_changed)
        if hasattr(panel, "set_stream_state"):
            self.streamState.connect(panel.set_stream_state)
        if hasattr(panel, "update_todos"):
            self.todosUpdate.connect(panel.update_todos)
        if hasattr(panel, "upsert_milestone"):
            self.milestoneUpsert.connect(panel.upsert_milestone)
        if hasattr(panel, "on_plan_file"):
            self.planFile.connect(panel.on_plan_file)
        if hasattr(panel, "on_plan_exited"):
            self.planExited.connect(panel.on_plan_exited)
        self.editApprovalRequest.connect(self._on_edit_approval_request)
        if hasattr(panel, "reload_doc"):
            self.docReloadRequested.connect(panel.reload_doc)
        bridge = getattr(panel, "bridge", None)
        if bridge is not None:
            if hasattr(bridge, "_on_context_usage"):
                try:
                    self.contextUsage.connect(bridge._on_context_usage)
                except Exception:
                    pass
            if hasattr(bridge, "_on_compacting_changed"):
                try:
                    self.compactingChanged.connect(bridge._on_compacting_changed)
                except Exception:
                    pass
            try:
                self.compactionEvent.connect(panel.emit_compaction)
            except Exception:
                pass

    def _on_edit_approval_request(self, req_id, summary, script, cf_future):
        try:
            self._panel.request_edit_approval_threadsafe(
                req_id, summary, script, cf_future
            )
        except Exception as exc:
            if not cf_future.done():
                cf_future.set_exception(exc)

    def _on_permission_request(self, tool_name, tool_input, cf_future):
        try:
            self._panel.request_permission_threadsafe(
                short_name(tool_name), tool_input, cf_future
            )
        except Exception as exc:
            if not cf_future.done():
                cf_future.set_exception(exc)

    def _on_ask_user_question(self, questions, cf_future):
        try:
            self._panel.ask_user_question_threadsafe(questions, cf_future)
        except Exception as exc:
            if not cf_future.done():
                cf_future.set_exception(exc)


__all__ = ["PanelProxy"]
