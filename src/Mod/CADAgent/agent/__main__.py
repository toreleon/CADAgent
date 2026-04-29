# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless CLI entry point for testing the agent without FreeCAD's GUI.

Usage:

    python -m agent [--doc PATH] [--model MODEL] "your prompt"
    echo "your prompt" | python -m agent --doc /tmp/part.FCStd

Or, since the agent uses the worker subprocess for ``inspect.*`` tools,
you usually want to run it under ``pixi`` so ``CADAGENT_FREECADCMD`` is
set and a real FreeCADCmd is on PATH:

    pixi run python -m agent "describe the active doc"

Defaults:

* ``ANTHROPIC_BASE_URL=http://localhost:4141/`` (the LiteLLM proxy).
* ``ANTHROPIC_API_KEY=dummy``.
* ``ANTHROPIC_MODEL=gpt-5-mini``.
* ``CADAGENT_PERMS=bypassPermissions`` (autonomous; no approval prompts).

The CLI does **not** import any FreeCAD GUI module, so the doc-lifecycle
tools (``gui_*``) are not registered. ``inspect`` and ``verify_spec`` work
because they go through the worker subprocess (``FreeCADCmd`` runs the
real FreeCAD); ``memory_*`` and ``plan_*`` are pure-Python and work too.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .runtime.options import build_options
from .tools import short_name


def _set_default_env() -> None:
    os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:4141/")
    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
    os.environ.setdefault("ANTHROPIC_MODEL", "gpt-5-mini")
    os.environ.setdefault("CADAGENT_PERMS", "bypassPermissions")


def _format_tool_input(payload: Any, max_len: int = 200) -> str:
    s = repr(payload)
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _format_tool_result(blocks: Any, max_len: int = 400) -> str:
    """Pull the first text block out of a ToolResult content list."""
    if isinstance(blocks, str):
        text = blocks
    elif isinstance(blocks, list):
        parts: list[str] = []
        for blk in blocks:
            if isinstance(blk, dict):
                t = blk.get("text") or blk.get("content")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(blk, str):
                parts.append(blk)
        text = "\n".join(parts)
    else:
        text = repr(blocks)
    text = text.strip()
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


async def _drive_turn(client: ClaudeSDKClient, prompt: str) -> int:
    """Submit one prompt, stream events to stdout, return exit code."""
    await client.query(prompt)
    rc = 0
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    sys.stdout.write(block.text)
                    sys.stdout.flush()
                elif isinstance(block, ThinkingBlock):
                    sys.stderr.write(f"\n[thinking] {block.thinking}\n")
                elif isinstance(block, ToolUseBlock):
                    name = short_name(block.name)
                    sys.stderr.write(
                        f"\n[tool {name}] {_format_tool_input(block.input)}\n"
                    )
        elif isinstance(msg, UserMessage):
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    sys.stderr.write(
                        f"[result] {_format_tool_result(block.content)}\n"
                    )
        elif isinstance(msg, ResultMessage):
            usage = getattr(msg, "usage", None)
            if usage:
                sys.stderr.write(f"\n[usage] {usage}\n")
            rc = 0 if (getattr(msg, "subtype", "") or "").startswith("success") else (rc or 1)
    sys.stdout.write("\n")
    return rc


async def _run(prompt: str, doc: str | None, model: str | None) -> int:
    doc_abs: str | None = None
    if doc:
        doc_abs = os.path.abspath(os.path.expanduser(doc))
        os.environ["CADAGENT_DOC"] = doc_abs
    if model:
        os.environ["ANTHROPIC_MODEL"] = model

    if doc_abs:
        prompt = (
            f"[CLI context] Workspace .FCStd: {doc_abs!r}. Pass this exact "
            f"path as the ``doc`` argument to ``memory_*`` / ``plan_*`` / "
            f"``inspect`` tools.\n\n{prompt}"
        )

    options = build_options()
    async with ClaudeSDKClient(options=options) as client:
        return await _drive_turn(client, prompt)


def main(argv: list[str] | None = None) -> int:
    _set_default_env()
    p = argparse.ArgumentParser(
        prog="python -m agent",
        description="Headless CLI for the CAD Agent (no FreeCAD GUI required).",
    )
    p.add_argument(
        "prompt",
        nargs="?",
        help="The user message. If omitted, read from stdin.",
    )
    p.add_argument(
        "--doc",
        help="Absolute path to the .FCStd to operate on (sets CADAGENT_DOC).",
    )
    p.add_argument(
        "--model",
        help="Override ANTHROPIC_MODEL for this run.",
    )
    args = p.parse_args(argv)

    prompt = args.prompt
    if prompt is None:
        if sys.stdin.isatty():
            p.error("no prompt given and stdin is a TTY")
        prompt = sys.stdin.read().strip()
    if not prompt:
        p.error("empty prompt")

    return asyncio.run(_run(prompt, args.doc, args.model))


if __name__ == "__main__":
    raise SystemExit(main())
