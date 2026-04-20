# SPDX-License-Identifier: LGPL-2.1-or-later
"""Runtime wrapper around ClaudeSDKClient for the CAD Agent.

Owns the asyncio lifetime of a single chat session. Streams assistant text and
tool-use events back to the ChatPanel.
"""

import asyncio
import os
import sys
import traceback

import FreeCAD as App

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
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
    )
finally:
    sys.stderr = _saved_stderr

import tools as cad_tools
from permissions import make_can_use_tool
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
    """Optional override. When set, the SDK talks to a LiteLLM proxy (or any
    Anthropic-compatible gateway) instead of api.anthropic.com.
    """
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


class AgentRuntime:
    def __init__(self, panel):
        self.panel = panel
        self.client: ClaudeSDKClient | None = None
        self._current_task: asyncio.Task | None = None

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
            can_use_tool=make_can_use_tool(self.panel),
            permission_mode=_resolve_permission_mode(),
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
            self.panel.show_error(
                f"{exc}\n\n{traceback.format_exc(limit=3)}"
            )
        finally:
            self.panel.mark_turn_complete()

    def _route_message(self, msg) -> None:
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    self.panel.append_assistant_text(block.text)
                elif isinstance(block, ToolUseBlock):
                    self.panel.announce_tool_use(
                        getattr(block, "id", ""), block.name, block.input
                    )
                elif isinstance(block, ThinkingBlock):
                    self.panel.append_thinking(block.thinking)
                elif isinstance(block, ToolResultBlock):
                    self.panel.announce_tool_result(
                        getattr(block, "tool_use_id", ""),
                        block.content,
                        getattr(block, "is_error", False),
                    )
        elif isinstance(msg, ResultMessage):
            self.panel.record_result(msg)

    def submit(self, user_text: str) -> None:
        """Fire-and-forget entry point called from the Qt UI thread."""
        if self._current_task is not None and not self._current_task.done():
            self.panel.show_error("A previous turn is still running.")
            return
        loop = asyncio.get_event_loop()
        self._current_task = loop.create_task(self.ask(user_text))

    async def interrupt(self) -> None:
        if self.client is not None:
            try:
                await self.client.interrupt()
            except Exception:
                pass

    async def aclose(self) -> None:
        if self.client is not None:
            try:
                await self.client.__aexit__(None, None, None)
            finally:
                self.client = None
