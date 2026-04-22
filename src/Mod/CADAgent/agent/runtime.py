# SPDX-License-Identifier: LGPL-2.1-or-later
"""Runtime wrapper around ClaudeSDKClient for the CAD Agent.

Runs the SDK on a dedicated background thread with its own asyncio event loop,
and marshals panel updates onto the Qt GUI thread via signals. This keeps the
SDK's anyio / asyncio assumptions happy while never blocking FreeCAD's main
event loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import sys
import threading
import time
import traceback


# Set CADAGENT_DEBUG=1 in the environment (or in Preferences → CADAgent) to
# stream per-message timing to stderr. Use it to confirm whether delta events
# arrive progressively from the proxy or in one burst at the end.
_DEBUG = bool(os.environ.get("CADAGENT_DEBUG"))

# Per-turn stopwatch, reset when ask() sends a query. Lets the debug log print
# seconds-since-query rather than raw monotonic time, so "burst at the end"
# vs "spread across the turn" is obvious at a glance.
_turn_t0: float | None = None


def _dbg(tag: str) -> None:
    if _DEBUG:
        try:
            if _turn_t0 is None:
                stamp = f"{time.monotonic():.3f}"
            else:
                stamp = f"+{time.monotonic() - _turn_t0:6.3f}s"
            print(
                f"[cadagent {stamp}] {tag}",
                file=sys.__stderr__,
                flush=True,
            )
        except Exception:
            pass

import FreeCAD as App

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore

# FreeCAD's GUI replaces sys.stderr with a C++-backed stream whose __class__
# attribute isn't introspectable the way @dataclass(f.default.__class__) needs.
# claude_agent_sdk's ClaudeAgentOptions defaults `debug_stderr = sys.stderr`
# at import time, so that introspection blows up. Restore the original stream
# for the duration of the import.
_saved_stderr = sys.stderr
try:
    sys.stderr = sys.__stderr__ or sys.stdout
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        StreamEvent,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
    )
finally:
    sys.stderr = _saved_stderr

from . import sessions as cad_sessions
from . import tools as cad_tools
from . import ui_bridge
from .context import wrap_user_message
from .permissions import make_can_use_tool
from .prompts import CAD_SYSTEM_PROMPT


PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/CADAgent"


def _resolve_api_key() -> str:
    params = App.ParamGet(PARAM_PATH)
    key = params.GetString("ApiKey", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "No LiteLLM proxy key configured. Set one in "
            "Preferences \u2192 CAD Agent, or export ANTHROPIC_API_KEY."
        )
    return key


def _resolve_base_url() -> str:
    params = App.ParamGet(PARAM_PATH)
    url = (
        params.GetString("BaseURL", "")
        or os.environ.get("ANTHROPIC_BASE_URL", "")
    )
    if not url:
        raise RuntimeError(
            "No LiteLLM proxy URL configured. Set one in "
            "Preferences \u2192 CAD Agent (e.g. http://localhost:4000), "
            "or export ANTHROPIC_BASE_URL."
        )
    return url


def _resolve_model() -> str:
    params = App.ParamGet(PARAM_PATH)
    return params.GetString("Model", "claude-opus-4-7") or "claude-opus-4-7"


def _resolve_permission_mode() -> str:
    params = App.ParamGet(PARAM_PATH)
    mode = params.GetString("PermissionMode", "default") or "default"
    if mode not in {"default", "acceptEdits", "plan", "bypassPermissions"}:
        mode = "default"
    return mode


class _PanelProxy(QtCore.QObject):
    """Marshals panel calls from the worker thread onto the Qt GUI thread.

    Each signal is connected with a QueuedConnection (automatic for
    cross-thread emitters) so the slot executes on the panel's thread.
    """

    assistantText = QtCore.Signal(str)
    thinking = QtCore.Signal(str)
    toolUse = QtCore.Signal(str, str, object)
    toolResult = QtCore.Signal(str, object, bool)
    resultMsg = QtCore.Signal(object)
    turnComplete = QtCore.Signal()
    error = QtCore.Signal(str)
    permissionRequest = QtCore.Signal(str, object, object)  # name, input, cf_future
    askUserQuestion = QtCore.Signal(object, object)  # questions, cf_future
    sessionChanged = QtCore.Signal(str)  # new session_id (captured from SDK)

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

    def _on_permission_request(self, tool_name, tool_input, cf_future):
        """Runs on the GUI thread — asks the panel, resolves the cf_future
        when the user clicks Apply or Reject."""
        try:
            self._panel.request_permission_threadsafe(
                tool_name, tool_input, cf_future
            )
        except Exception as exc:
            if not cf_future.done():
                cf_future.set_exception(exc)

    def _on_ask_user_question(self, questions, cf_future):
        """Runs on the GUI thread — surfaces an AskUserQuestion card."""
        try:
            self._panel.ask_user_question_threadsafe(questions, cf_future)
        except Exception as exc:
            if not cf_future.done():
                cf_future.set_exception(exc)


class AgentRuntime:
    def __init__(self, panel):
        self.panel = panel
        self._proxy = _PanelProxy(panel)
        ui_bridge.set_proxy(self._proxy)
        self.client: ClaudeSDKClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._current_future: concurrent.futures.Future | None = None
        # Session state: None = start a fresh session on next turn.
        # After the first ResultMessage we capture the SDK's session_id here
        # so we can record it in the per-document index.
        self._resume_session_id: str | None = None
        self._active_session_id: str | None = None
        self._pending_first_prompt: str | None = None
        self._active_doc = None

    # --- worker thread --------------------------------------------------

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

    # --- session --------------------------------------------------------

    async def _ensure_client(self) -> None:
        if self.client is not None:
            return
        os.environ["ANTHROPIC_API_KEY"] = _resolve_api_key()
        os.environ["ANTHROPIC_BASE_URL"] = _resolve_base_url()
        model = _resolve_model()
        # LiteLLM typically only exposes the models configured in its proxy
        # and rejects the SDK's default Haiku used for background tasks (title
        # generation, compaction). Pin the small/fast model to the configured
        # model so every request routes to something the proxy recognises.
        os.environ["ANTHROPIC_MODEL"] = model
        os.environ["ANTHROPIC_SMALL_FAST_MODEL"] = model
        server = cad_tools.build_mcp_server()
        options = ClaudeAgentOptions(
            model=model,
            system_prompt=CAD_SYSTEM_PROMPT,
            mcp_servers={"cad": server},
            allowed_tools=cad_tools.allowed_tool_names(),
            can_use_tool=make_can_use_tool(self._proxy),
            permission_mode=_resolve_permission_mode(),
            include_partial_messages=True,
            resume=self._resume_session_id,
        )
        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()

    async def ask(self, user_text: str) -> None:
        try:
            await self._ensure_client()
            assert self.client is not None
            self._pending_first_prompt = user_text
            wrapped = wrap_user_message(user_text)
            global _turn_t0
            _turn_t0 = time.monotonic()
            await self.client.query(wrapped)
            _dbg("ask: sent query, awaiting stream")
            async for msg in self.client.receive_response():
                self._route_message(msg)
        except Exception as exc:
            self._proxy.error.emit(
                f"{exc}\n\n{traceback.format_exc(limit=3)}"
            )
        finally:
            self._proxy.turnComplete.emit()

    def _route_message(self, msg) -> None:
        if isinstance(msg, StreamEvent):
            ev = msg.event or {}
            ev_type = ev.get("type")
            if ev_type == "content_block_delta":
                delta = ev.get("delta") or {}
                dtype = delta.get("type")
                if dtype == "text_delta":
                    text = delta.get("text") or ""
                    if text:
                        _dbg(f"text_delta len={len(text)}")
                        self._proxy.assistantText.emit(text)
                elif dtype == "thinking_delta":
                    text = delta.get("thinking") or ""
                    if text:
                        _dbg(f"thinking_delta len={len(text)}")
                        self._proxy.thinking.emit(text)
            else:
                _dbg(f"StreamEvent type={ev_type}")
            return
        _dbg(f"msg={type(msg).__name__}")
        if isinstance(msg, AssistantMessage):
            sid = getattr(msg, "session_id", None)
            if sid:
                self._capture_session_id(sid)
            for block in msg.content:
                if isinstance(block, TextBlock):
                    # Text already streamed via StreamEvent deltas; skip to avoid
                    # duplicating it on the final non-partial AssistantMessage.
                    pass
                elif isinstance(block, ToolUseBlock):
                    self._proxy.toolUse.emit(
                        getattr(block, "id", ""), block.name, block.input
                    )
                    try:
                        cad_tools.mark_tool(block.name)
                    except Exception:
                        pass
                elif isinstance(block, ThinkingBlock):
                    self._proxy.thinking.emit(block.thinking)
                elif isinstance(block, ToolResultBlock):
                    self._proxy.toolResult.emit(
                        getattr(block, "tool_use_id", ""),
                        block.content,
                        getattr(block, "is_error", False),
                    )
        elif isinstance(msg, ResultMessage):
            sid = getattr(msg, "session_id", None)
            if sid:
                self._capture_session_id(sid)
            self._record_turn_in_index()
            self._proxy.resultMsg.emit(msg)

    def _capture_session_id(self, session_id: str) -> None:
        if session_id and session_id != self._active_session_id:
            self._active_session_id = session_id
            self._proxy.sessionChanged.emit(session_id)

    def _record_turn_in_index(self) -> None:
        if not self._active_session_id or self._active_doc is None:
            return
        try:
            cad_sessions.record_turn(
                self._active_doc,
                self._active_session_id,
                self._pending_first_prompt,
            )
        except Exception:
            pass
        self._pending_first_prompt = None

    # --- entry points ---------------------------------------------------

    def submit(self, user_text: str) -> None:
        """Fire-and-forget entry point called from the Qt GUI thread."""
        if (
            self._current_future is not None
            and not self._current_future.done()
        ):
            self.panel.show_error("A previous turn is still running.")
            return
        if self._active_doc is None:
            self._active_doc = App.ActiveDocument
        loop = self._ensure_loop()
        self._current_future = asyncio.run_coroutine_threadsafe(
            self.ask(user_text), loop
        )

    # --- session lifecycle ---------------------------------------------

    def bind_document(self, doc) -> None:
        """Associate turns with ``doc`` for per-document session indexing."""
        self._active_doc = doc

    def active_session_id(self) -> str | None:
        return self._active_session_id

    def _turn_in_flight(self) -> bool:
        return (
            self._current_future is not None
            and not self._current_future.done()
        )

    def start_new_session(self) -> bool:
        """Discard the current SDK client so the next turn starts fresh."""
        if self._turn_in_flight():
            return False
        self._resume_session_id = None
        self._active_session_id = None
        self._pending_first_prompt = None
        self._teardown_client()
        return True

    def resume_session(self, session_id: str) -> bool:
        """Discard the current client and resume ``session_id`` on next turn."""
        if self._turn_in_flight():
            return False
        self._resume_session_id = session_id
        self._active_session_id = session_id
        self._pending_first_prompt = None
        self._teardown_client()
        return True

    def _teardown_client(self) -> None:
        if self.client is None:
            return
        if self._loop is None:
            self.client = None
            return
        asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)

    async def _interrupt(self) -> None:
        if self.client is not None:
            try:
                await self.client.interrupt()
            except Exception:
                pass

    def interrupt(self) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._interrupt(), self._loop)

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
