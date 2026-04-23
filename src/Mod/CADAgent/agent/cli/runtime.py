# SPDX-License-Identifier: LGPL-2.1-or-later
"""Standalone CLI runtime.

Runs ``ClaudeSDKClient`` in a plain Python process — no FreeCAD import, no Qt,
no MCP verb surface. Drives FreeCAD via the built-in ``Bash`` tool and keeps
the memory / plan MCP tools for sidecar I/O.

Usage:
    python -m agent.cli "your prompt here"
    # or via the wrapper:
    scripts/cadagent "your prompt here"

Environment:
    ANTHROPIC_API_KEY   required
    ANTHROPIC_BASE_URL  optional (LiteLLM proxy)
    ANTHROPIC_MODEL     default: claude-opus-4-7
    CADAGENT_DOC        default: $PWD/.fc-home/part.FCStd — the working .FCStd path
    CADAGENT_PERMS      default 'bypassPermissions' (non-interactive)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

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
    UserMessage,
    create_sdk_mcp_server,
)

from ..prompts_cli import CAD_SYSTEM_PROMPT
from . import mcp_tools
from .subagents import build_agents


# ---------------------------------------------------------------------------
# terminal output (small, stdout-only; stripped-down cli.py's CliPanel)
# ---------------------------------------------------------------------------

_NO_COLOR = not sys.stdout.isatty() or bool(os.environ.get("NO_COLOR"))


def _c(seq: str) -> str:
    return "" if _NO_COLOR else seq


DIM = _c("\033[2m")
BOLD = _c("\033[1m")
ITAL = _c("\033[3m")
ACCENT = _c("\033[38;5;39m")
GREEN = _c("\033[32m")
RED = _c("\033[31m")
RESET = _c("\033[0m")


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _preview(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _truncate(value.replace("\n", " "), limit)
    if isinstance(value, list):
        parts = []
        for block in value:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block, default=str))
        return _truncate(" ".join(parts).replace("\n", " "), limit)
    try:
        return _truncate(json.dumps(value, default=str), limit)
    except Exception:
        return _truncate(str(value), limit)


class Stream:
    """One-shot terminal streamer. Keeps enough state to not duplicate output."""

    def __init__(self) -> None:
        self._assistant_open = False
        self._thinking_open = False
        self._tool_names: dict[str, str] = {}

    def assistant_text(self, text: str) -> None:
        if self._thinking_open:
            sys.stdout.write(RESET + "\n")
            self._thinking_open = False
        if not self._assistant_open:
            sys.stdout.write(f"\n{ACCENT}⏺{RESET} ")
            self._assistant_open = True
        sys.stdout.write(text)
        sys.stdout.flush()

    def thinking(self, text: str) -> None:
        if self._assistant_open:
            sys.stdout.write("\n")
            self._assistant_open = False
        if not self._thinking_open:
            sys.stdout.write(f"\n{DIM}{ITAL}✻ ")
            self._thinking_open = True
        sys.stdout.write(text)
        sys.stdout.flush()

    def close_streams(self) -> None:
        if self._assistant_open or self._thinking_open:
            sys.stdout.write(RESET + "\n")
        self._assistant_open = False
        self._thinking_open = False

    def tool_use(self, tool_id: str, name: str, tool_input: Any) -> None:
        self.close_streams()
        self._tool_names[tool_id or ""] = name
        inp = _preview(tool_input, 240)
        body = f"{name}({DIM}{inp}{RESET})" if inp else f"{name}()"
        sys.stdout.write(f"{ACCENT}⏺{RESET} {BOLD}{body}{RESET}\n")
        sys.stdout.flush()

    def tool_result(self, tool_id: str, content: Any, is_error: bool) -> None:
        if tool_id and tool_id not in self._tool_names:
            return
        self._tool_names.pop(tool_id or "", None)
        color = RED if is_error else GREEN
        label = "ERR" if is_error else "OK"
        body = _preview(content, 480)
        sys.stdout.write(f"  {DIM}⎿{RESET} {color}{label}{RESET} {DIM}{body}{RESET}\n")
        sys.stdout.flush()

    def result(self, msg: ResultMessage) -> None:
        self.close_streams()
        cost = getattr(msg, "total_cost_usd", None) or getattr(msg, "cost_usd", None)
        usage = getattr(msg, "usage", None)
        toks = None
        if usage is not None:
            in_t = getattr(usage, "input_tokens", None)
            out_t = getattr(usage, "output_tokens", None)
            if in_t is None and isinstance(usage, dict):
                in_t = usage.get("input_tokens")
                out_t = usage.get("output_tokens")
            if in_t is not None or out_t is not None:
                toks = (in_t or 0) + (out_t or 0)
        parts = []
        if toks is not None:
            parts.append(f"{toks:,} tok")
        if cost is not None:
            parts.append(f"${cost:.4f}")
        if parts:
            sys.stdout.write(f"{DIM}  {' · '.join(parts)}{RESET}\n")
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# async driver
# ---------------------------------------------------------------------------


_MCP_PREFIX = "mcp__cad__"


def _strip_prefix(name: str) -> str:
    return name[len(_MCP_PREFIX):] if name.startswith(_MCP_PREFIX) else name


def _build_options() -> ClaudeAgentOptions:
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    os.environ.setdefault("ANTHROPIC_SMALL_FAST_MODEL", model)

    server = create_sdk_mcp_server(name="cad", tools=mcp_tools.TOOL_FUNCS)

    # SDK built-ins the agent is allowed to use. Deliberately excluding Edit:
    # the CLI agent is supposed to write new .py scripts via Bash heredocs,
    # not edit source files.
    sdk_builtins = [
        "Bash",
        "Read",
        "Grep",
        "Glob",
        "Write",
        "AskUserQuestion",
        "Agent",
        "TodoWrite",
    ]
    allowed = mcp_tools.allowed_tool_names("cad") + sdk_builtins

    return ClaudeAgentOptions(
        model=model,
        system_prompt=CAD_SYSTEM_PROMPT,
        mcp_servers={"cad": server},
        allowed_tools=allowed,
        agents=build_agents(),
        permission_mode=os.environ.get("CADAGENT_PERMS", "bypassPermissions"),
        include_partial_messages=True,
    )


async def _drive(prompt: str) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write(f"{RED}!{RESET} ANTHROPIC_API_KEY is required\n")
        return 2

    options = _build_options()
    stream = Stream()

    sys.stdout.write(f"{ACCENT}>{RESET} {prompt}\n")
    sys.stdout.flush()

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, StreamEvent):
                ev = msg.event or {}
                if ev.get("type") == "content_block_delta":
                    delta = ev.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        txt = delta.get("text") or ""
                        if txt:
                            stream.assistant_text(txt)
                    elif delta.get("type") == "thinking_delta":
                        txt = delta.get("thinking") or ""
                        if txt:
                            stream.thinking(txt)
                continue
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        stream.tool_use(
                            getattr(block, "id", ""),
                            _strip_prefix(block.name),
                            block.input,
                        )
                    elif isinstance(block, ThinkingBlock):
                        stream.thinking(block.thinking)
                    elif isinstance(block, TextBlock):
                        # already streamed via text_delta
                        pass
            elif isinstance(msg, UserMessage):
                # Tool results come back wrapped in a UserMessage.
                content = getattr(msg, "content", None)
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, ToolResultBlock):
                            stream.tool_result(
                                getattr(block, "tool_use_id", ""),
                                block.content,
                                bool(getattr(block, "is_error", False) or False),
                            )
            elif isinstance(msg, ResultMessage):
                stream.result(msg)

    stream.close_streams()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        sys.stderr.write("usage: cadagent \"<prompt>\"\n")
        return 2
    prompt = " ".join(argv).strip()
    if not prompt:
        sys.stderr.write("empty prompt\n")
        return 2

    try:
        return asyncio.run(_drive(prompt))
    except KeyboardInterrupt:
        sys.stdout.write(f"\n{DIM}interrupted{RESET}\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
