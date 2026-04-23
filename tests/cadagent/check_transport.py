"""Phase 0 transport verification for CADAgent v2 redesign.

Goal: confirm the configured LiteLLM proxy (or direct Anthropic) passes through
the three SDK features the v2 plan depends on:

    1. PreToolUse hooks fire for MCP tool calls.
    2. `agents={}` subagent definitions are reachable via the built-in Agent tool.
    3. `permission_mode="plan"` suppresses tool execution and produces a plan text.

Run headlessly outside FreeCAD:

    ANTHROPIC_BASE_URL=http://localhost:4000 \
    ANTHROPIC_API_KEY=sk-... \
    ANTHROPIC_MODEL=claude-opus-4-7 \
    python tests/cadagent/check_transport.py

Exits 0 on success, 1 on any failed probe. Prints a short report to stdout.

Throwaway by design — results are recorded in the plan file, then this script
can be deleted or kept as a diagnostic.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)


@dataclass
class Probe:
    hook_fired: bool = False
    hook_matched_tools: list[str] = field(default_factory=list)
    plan_mode_executed_tool: bool = False
    plan_mode_text_seen: bool = False
    subagent_invoked: bool = False
    errors: list[str] = field(default_factory=list)


PROBE = Probe()


# --- trivial in-process tool so there is something for hooks to match on ----


@tool("echo_probe", "Echo back the text argument unchanged.", {"text": str})
async def echo_probe(args: dict) -> dict:
    text = args.get("text", "")
    return {"content": [{"type": "text", "text": f"echo:{text}"}]}


# --- hook body ---------------------------------------------------------------


async def pretool_probe(input_data, tool_use_id, context):  # SDK hook signature
    name = None
    try:
        name = input_data.get("tool_name") if isinstance(input_data, dict) else getattr(input_data, "tool_name", None)
    except Exception:
        pass
    if name:
        PROBE.hook_fired = True
        PROBE.hook_matched_tools.append(name)
    return {}


# --- driver ------------------------------------------------------------------


def _resolve_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL") or "claude-opus-4-7"


async def probe_hooks_and_tool_call() -> None:
    server = create_sdk_mcp_server(name="cad", tools=[echo_probe])
    options = ClaudeAgentOptions(
        model=_resolve_model(),
        system_prompt=(
            "You are a test harness. When the user says 'run echo', call the "
            "echo_probe tool exactly once with text='hi', then stop."
        ),
        mcp_servers={"cad": server},
        allowed_tools=["mcp__cad__echo_probe"],
        hooks={"PreToolUse": [HookMatcher(matcher="mcp__cad__.*", hooks=[pretool_probe])]},
        permission_mode="bypassPermissions",
        include_partial_messages=False,
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query("run echo")
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                break


async def probe_plan_mode() -> None:
    server = create_sdk_mcp_server(name="cad", tools=[echo_probe])
    options = ClaudeAgentOptions(
        model=_resolve_model(),
        system_prompt=(
            "You are a test harness. Plan mode is on. You must NOT call any tools. "
            "Reply with a one-line plan only."
        ),
        mcp_servers={"cad": server},
        allowed_tools=["mcp__cad__echo_probe"],
        permission_mode="plan",
        include_partial_messages=False,
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Plan how you would call echo_probe. Do not execute.")
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        # ExitPlanMode is the SDK's built-in plan submission tool;
                        # it's expected in plan mode and does not count as "executed".
                        if getattr(block, "name", "") == "ExitPlanMode":
                            continue
                        PROBE.plan_mode_executed_tool = True
                    elif isinstance(block, TextBlock):
                        if (block.text or "").strip():
                            PROBE.plan_mode_text_seen = True
            if isinstance(msg, ResultMessage):
                break


async def probe_subagent() -> None:
    server = create_sdk_mcp_server(name="cad", tools=[echo_probe])
    options = ClaudeAgentOptions(
        model=_resolve_model(),
        system_prompt=(
            "You are a test harness. Delegate the task to the 'echoer' subagent "
            "via the Agent tool. Do not answer directly."
        ),
        mcp_servers={"cad": server},
        allowed_tools=["mcp__cad__echo_probe", "Agent"],
        agents={
            "echoer": AgentDefinition(
                description="Trivial echo subagent used by the transport probe.",
                prompt="Reply with the single word PONG and stop.",
                tools=[],
            )
        },
        permission_mode="bypassPermissions",
        include_partial_messages=False,
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Use the echoer subagent to reply.")
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock) and getattr(block, "name", "") == "Agent":
                        PROBE.subagent_invoked = True
            if isinstance(msg, ResultMessage):
                break


async def main() -> int:
    async def _run(label: str, coro_factory):
        try:
            await coro_factory()
        except Exception as exc:
            PROBE.errors.append(f"{label}: {type(exc).__name__}: {exc}")

    await _run("hooks+tool_call", probe_hooks_and_tool_call)
    await _run("plan_mode", probe_plan_mode)
    await _run("subagent", probe_subagent)

    print("\n=== CADAgent transport probe ===")
    print(f"base_url  : {os.environ.get('ANTHROPIC_BASE_URL', '(default Anthropic)')}")
    print(f"model     : {_resolve_model()}")
    print("--------------------------------")
    print(f"hooks fired            : {PROBE.hook_fired} ({PROBE.hook_matched_tools})")
    print(f"plan mode suppressed   : {not PROBE.plan_mode_executed_tool}")
    print(f"plan mode text seen    : {PROBE.plan_mode_text_seen}")
    print(f"subagent invokable     : {PROBE.subagent_invoked}")
    if PROBE.errors:
        print("errors:")
        for e in PROBE.errors:
            print(f"  - {e}")

    ok = (
        PROBE.hook_fired
        and not PROBE.plan_mode_executed_tool
        and PROBE.subagent_invoked
        and not PROBE.errors
    )
    print("--------------------------------")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
