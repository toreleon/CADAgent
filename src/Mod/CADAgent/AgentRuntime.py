# SPDX-License-Identifier: LGPL-2.1-or-later
"""Runtime wrapper around ClaudeSDKClient for the CAD Agent.

Runs the SDK on a dedicated background thread with its own asyncio event loop,
and marshals panel updates onto the Qt GUI thread via signals. This keeps the
SDK's anyio / asyncio assumptions happy while never blocking FreeCAD's main
event loop.
"""

import asyncio
import concurrent.futures
import os
import sys
import threading
import traceback

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

import tools as cad_tools
from permissions import Decision, make_can_use_tool
from prompts import CAD_SYSTEM_PROMPT


PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/CADAgent"


def _resolve_api_key() -> str:
    params = App.ParamGet(PARAM_PATH)
    key = params.GetString("ApiKey", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "No ANTHROPIC_API_KEY configured. Set one in "
            "Preferences \u2192 CAD Agent, or export ANTHROPIC_API_KEY. "
            "When routing through a LiteLLM proxy, use the proxy's key "
            "(e.g. sk-1234)."
        )
    return key


def _resolve_base_url() -> str:
    params = App.ParamGet(PARAM_PATH)
    return (
        params.GetString("BaseURL", "")
        or os.environ.get("ANTHROPIC_BASE_URL", "")
    )


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


class AgentRuntime:
    def __init__(self, panel):
        self.panel = panel
        self._proxy = _PanelProxy(panel)
        self.client: ClaudeSDKClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._current_future: concurrent.futures.Future | None = None

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
        base_url = _resolve_base_url()
        if base_url:
            os.environ["ANTHROPIC_BASE_URL"] = base_url
        server = cad_tools.build_mcp_server()
        options = ClaudeAgentOptions(
            model=_resolve_model(),
            system_prompt=CAD_SYSTEM_PROMPT,
            mcp_servers={"cad": server},
            allowed_tools=cad_tools.allowed_tool_names(),
            can_use_tool=make_can_use_tool(self._proxy),
            permission_mode=_resolve_permission_mode(),
            include_partial_messages=True,
        )
        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()

    async def ask(self, user_text: str) -> None:
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
            self._proxy.turnComplete.emit()

    def _route_message(self, msg) -> None:
        if isinstance(msg, StreamEvent):
            ev = msg.event or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = delta.get("text") or ""
                    if text:
                        self._proxy.assistantText.emit(text)
                elif delta.get("type") == "thinking_delta":
                    text = delta.get("thinking") or ""
                    if text:
                        self._proxy.thinking.emit(text)
            return
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    # Text already streamed via StreamEvent deltas; skip to avoid
                    # duplicating it on the final non-partial AssistantMessage.
                    pass
                elif isinstance(block, ToolUseBlock):
                    self._proxy.toolUse.emit(
                        getattr(block, "id", ""), block.name, block.input
                    )
                elif isinstance(block, ThinkingBlock):
                    self._proxy.thinking.emit(block.thinking)
                elif isinstance(block, ToolResultBlock):
                    self._proxy.toolResult.emit(
                        getattr(block, "tool_use_id", ""),
                        block.content,
                        getattr(block, "is_error", False),
                    )
        elif isinstance(msg, ResultMessage):
            self._proxy.resultMsg.emit(msg)

    # --- entry points ---------------------------------------------------

    def submit(self, user_text: str) -> None:
        """Fire-and-forget entry point called from the Qt GUI thread."""
        if (
            self._current_future is not None
            and not self._current_future.done()
        ):
            self.panel.show_error("A previous turn is still running.")
            return
        loop = self._ensure_loop()
        self._current_future = asyncio.run_coroutine_threadsafe(
            self.ask(user_text), loop
        )

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
