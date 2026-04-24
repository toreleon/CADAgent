# SPDX-License-Identifier: LGPL-2.1-or-later
"""In-FreeCAD host for the standalone CLI agent.

The CLI runtime in :mod:`agent.cli.runtime` is designed for headless use
(``scripts/cadagent``). This module wraps it so the FreeCAD chat dock can
drive the same agent without spawning a subprocess: the SDK runs on a
dedicated worker asyncio loop, while the QML panel — and any FreeCAD doc
mutations — stay on the Qt GUI thread.

The agent owns document lifecycle: it can list, create, open, switch,
and reload documents through the MCP tools in :mod:`agent.cli.dock_tools`
— think of it like a shell session that can ``cd`` between projects.
Geometry still happens via ``Bash → FreeCADCmd`` subprocesses (the CLI
agent's contract); we save the active doc before each turn and auto-reload
it after, so the GUI reflects whatever the subprocess wrote.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
import traceback
from typing import Any

import FreeCAD as App

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .. import gui_thread, ui_bridge
from ..permissions import make_can_use_tool
from . import dock_tools, runtime as cli_runtime


_MCP_PREFIX = "mcp__cad__"


def _strip_prefix(name: str) -> str:
    if isinstance(name, str) and name.startswith(_MCP_PREFIX):
        return name[len(_MCP_PREFIX):]
    return name


class _PanelProxy(QtCore.QObject):
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
    subagentSpan = QtCore.Signal(str, str, str)
    permissionModeChanged = QtCore.Signal(str)
    streamState = QtCore.Signal(str, bool)

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

    def _on_permission_request(self, tool_name, tool_input, cf_future):
        try:
            self._panel.request_permission_threadsafe(
                _strip_prefix(tool_name), tool_input, cf_future
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


def _reload_active_doc_if_stale() -> None:
    """Re-open the active document so the GUI reflects subprocess writes.

    The CLI agent writes geometry via ``Bash → FreeCADCmd``, which mutates
    the ``.FCStd`` on disk while the GUI still holds the pre-Bash copy in
    memory. We close + re-open whenever the file's mtime is newer than the
    one we observed before the turn started.
    """
    doc = App.ActiveDocument
    if doc is None:
        return
    path = getattr(doc, "FileName", "") or ""
    if not path or not os.path.exists(path):
        return
    try:
        name = doc.Name
        App.closeDocument(name)
        new_doc = App.openDocument(path)
        App.setActiveDocument(new_doc.Name)
        try:
            new_doc.recompute()
        except Exception:
            pass
    except Exception:
        try:
            doc.recompute()
        except Exception:
            pass


def _snapshot_active_doc() -> dict:
    """Save the active doc if dirty and return a small summary."""
    doc = App.ActiveDocument
    if doc is None:
        return {"path": None, "name": None, "label": None, "object_count": 0}
    path = getattr(doc, "FileName", "") or ""
    if path:
        try:
            doc.save()
        except Exception:
            pass
    return {
        "path": path or None,
        "name": getattr(doc, "Name", "") or None,
        "label": getattr(doc, "Label", "") or None,
        "object_count": len(getattr(doc, "Objects", []) or []),
    }


def _build_preamble(snap: dict) -> str:
    if snap.get("path"):
        return (
            f"[GUI context] Active FreeCAD document: "
            f"{snap.get('label') or snap.get('name')!r} at {snap['path']!r} "
            f"({snap.get('object_count', 0)} objects). Pass this path as "
            f"the ``doc`` argument to ``memory_*`` / ``plan_*`` tools. "
            f"You may also use ``gui_documents_list``, ``gui_open_document``, "
            f"``gui_new_document``, or ``gui_set_active_document`` to work "
            f"on a different file when the request calls for it. The dock "
            f"auto-reloads the active doc in the GUI at end of turn."
        )
    return (
        "[GUI context] No FreeCAD document is open. Use "
        "``gui_new_document`` to create one (returns its on-disk path for "
        "``memory_*`` / ``plan_*`` tools), or ``gui_open_document`` to "
        "open an existing .FCStd. For pure questions or memory work no "
        "document is required."
    )


class DockRuntime:
    """Chat-panel-facing wrapper around the CLI agent.

    Public API mirrors what :class:`agent.ui.qml_panel.QmlChatPanel`
    expects: ``submit(text)``, ``interrupt()``, ``start_new_session()``.
    """

    def __init__(self, panel):
        self.panel = panel
        self._proxy = _PanelProxy(panel)
        ui_bridge.set_proxy(self._proxy)
        self.client: ClaudeSDKClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._current_future: concurrent.futures.Future | None = None
        self._workspace_path: str | None = None

    # --- worker thread -------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            try:
                loop.run_forever()
            finally:
                loop.close()

        self._thread = threading.Thread(
            target=_run, name="CADAgentAsyncio", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=5)
        assert self._loop is not None
        return self._loop

    # --- session -------------------------------------------------------

    async def _ensure_client(self) -> None:
        if self.client is not None:
            return
        # Pull LLM config from FreeCAD's parameter store first (set via the
        # "Configure LLM…" menu / dialog), with ANTHROPIC_* env vars as
        # fallback for headless / dev launches.
        params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/CADAgent")
        api_key = params.GetString("ApiKey", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = params.GetString("BaseURL", "") or os.environ.get("ANTHROPIC_BASE_URL", "")
        model = params.GetString("Model", "") or os.environ.get("ANTHROPIC_MODEL", "")
        if not api_key:
            raise RuntimeError(
                "No LLM API key configured. Use the CAD Agent menu → "
                "'Configure LLM…' to set the API key (and optional base URL "
                "for a LiteLLM proxy)."
            )
        os.environ["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            os.environ["ANTHROPIC_BASE_URL"] = base_url
        if model:
            os.environ["ANTHROPIC_MODEL"] = model
        # Tell the CLI runtime where the workspace .FCStd is so its MCP memory
        # tools (which key off the sidecar path) operate on the right doc.
        if self._workspace_path:
            os.environ["CADAGENT_DOC"] = self._workspace_path
        options = cli_runtime.build_options(
            extra_tools=dock_tools.TOOL_FUNCS,
            extra_allowed_tool_names=dock_tools.allowed_tool_names("cad"),
            permission_mode="default",
            can_use_tool=make_can_use_tool(self._proxy),
        )
        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()

    async def _ask(self, user_text: str) -> None:
        try:
            await self._ensure_client()
            assert self.client is not None
            await self.client.query(user_text)
            async for msg in self.client.receive_response():
                self._route_message(msg)
        except Exception as exc:
            self._proxy.error.emit(
                f"{exc}\n\n{traceback.format_exc(limit=3)}"
            )
        finally:
            try:
                gui_thread.run_sync(_reload_active_doc_if_stale, timeout=30.0)
            except Exception:
                pass
            self._proxy.turnComplete.emit()

    def _route_message(self, msg) -> None:
        if isinstance(msg, StreamEvent):
            ev = msg.event or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                dtype = delta.get("type")
                if dtype == "text_delta":
                    text = delta.get("text") or ""
                    if text:
                        self._proxy.assistantText.emit(text)
                elif dtype == "thinking_delta":
                    text = delta.get("thinking") or ""
                    if text:
                        self._proxy.thinking.emit(text)
            return
        if isinstance(msg, AssistantMessage):
            self._proxy.streamState.emit("", False)
            for block in msg.content:
                if isinstance(block, TextBlock):
                    pass  # already streamed via deltas
                elif isinstance(block, ToolUseBlock):
                    self._proxy.toolUse.emit(
                        getattr(block, "id", ""),
                        _strip_prefix(block.name),
                        block.input,
                    )
                elif isinstance(block, ThinkingBlock):
                    self._proxy.thinking.emit(block.thinking)
        elif isinstance(msg, UserMessage):
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        self._proxy.toolResult.emit(
                            getattr(block, "tool_use_id", ""),
                            block.content,
                            bool(getattr(block, "is_error", False) or False),
                        )
        elif isinstance(msg, ResultMessage):
            sid = getattr(msg, "session_id", None)
            if sid:
                self._proxy.sessionChanged.emit(sid)
            self._proxy.resultMsg.emit(msg)

    # --- entry points --------------------------------------------------

    def submit(self, user_text: str) -> None:
        if (
            self._current_future is not None
            and not self._current_future.done()
        ):
            self.panel.show_error("A previous turn is still running.")
            return
        try:
            snap = gui_thread.run_sync(_snapshot_active_doc, timeout=30.0)
        except Exception as exc:
            self.panel.show_error(f"Could not inspect active document: {exc}")
            return
        self._workspace_path = snap.get("path")
        wrapped = f"{_build_preamble(snap)}\n\n{user_text}"
        loop = self._ensure_loop()
        self._current_future = asyncio.run_coroutine_threadsafe(
            self._ask(wrapped), loop
        )

    def interrupt(self) -> None:
        if self._loop is None or self.client is None:
            return

        async def _interrupt():
            try:
                await self.client.interrupt()
            except Exception:
                pass

        asyncio.run_coroutine_threadsafe(_interrupt(), self._loop)

    def _turn_in_flight(self) -> bool:
        return (
            self._current_future is not None
            and not self._current_future.done()
        )

    def start_new_session(self) -> bool:
        if self._turn_in_flight():
            return False
        if self.client is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)
        return True

    async def _aclose(self) -> None:
        if self.client is not None:
            try:
                await self.client.__aexit__(None, None, None)
            finally:
                self.client = None

    def aclose(self) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)
