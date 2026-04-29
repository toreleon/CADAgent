# SPDX-License-Identifier: LGPL-2.1-or-later
"""Permission hook bridging the Claude Agent SDK `can_use_tool` callback to the
inline Apply / Reject cards rendered by ChatPanel.

The SDK callback runs on the asyncio worker thread; the panel lives on the Qt
GUI thread. A `concurrent.futures.Future` carries the user's decision back
across that boundary.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from . import hooks, ui_bridge
from .tools import MCP_PREFIX
from .tools.categories import Category, names_for, names_with_prefix


# SDK built-ins that never mutate state — auto-allowed alongside the MCP
# tools tagged READ / INSPECT.
_SDK_READ_ONLY = {"Read", "Grep", "Glob", "TodoWrite"}


# Tools whose invocation should be surfaced as a stageable "edit" rather
# than a generic permission prompt. The user sees an intent summary + the
# raw script (for Bash) and clicks Apply / Reject. UX classification, not
# a tool category — kept explicit to make the mapping obvious.
MUTATING_TOOLS = {
    "Bash",
    "Write",
    f"{MCP_PREFIX}gui_new_document",
    f"{MCP_PREFIX}gui_open_document",
}


# Tools that never mutate the document — auto-allow to keep the UX snappy.
# Derived from the READ + INSPECT categories so adding a new read-only
# MCP tool only requires updating ``agent.tools.categories``.
READ_ONLY_TOOLS = _SDK_READ_ONLY | set(names_for(Category.READ, Category.INSPECT))


# Plan-metadata tools are consumed by the dock runtime itself (the results
# are turned into milestone rows / plan files). They never reach the user
# as a prompt regardless of mode. Derived from the ``plan_`` prefix plus
# ``exit_plan_mode``.
PLAN_META_TOOLS = set(names_with_prefix("plan_")) | {f"{MCP_PREFIX}exit_plan_mode"}


# File-edit-class tools. Under ``acceptEdits`` mode these auto-allow; Bash
# is deliberately *not* in this set (shell execution stays gated, matching
# the Claude Code convention where acceptEdits covers edits but not
# arbitrary command execution). Doc lifecycle + sidecar writes — derived
# from DOC_LIFECYCLE + the ``memory_`` writeable subset.
FILE_EDIT_TOOLS = (
    {"Write"}
    | set(names_for(Category.DOC_LIFECYCLE))
    | {
        f"{MCP_PREFIX}memory_note_write",
        f"{MCP_PREFIX}memory_parameter_set",
        f"{MCP_PREFIX}memory_decision_record",
    }
)


_INTENT_HINTS = (
    ("Pad", "create a Pad"),
    ("Pocket", "create a Pocket"),
    ("Fillet", "add a Fillet"),
    ("Chamfer", "add a Chamfer"),
    ("Sketcher::SketchObject", "create a Sketch"),
    ("addObject", "add a FreeCAD object"),
    ("recompute", "recompute the document"),
    ("saveAs", "save the document"),
)


def _summarise_edit(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """Best-effort one-liner for the EditApprovalRow + the raw script body.

    The summary is a hint, not a contract — the agent's own narration in the
    surrounding assistant text is the authoritative description.
    """
    data = tool_input or {}
    if tool_name == "Bash":
        cmd = str(data.get("command") or "")
        desc = str(data.get("description") or "").strip()
        intent = desc or _guess_intent(cmd) or "Run shell command"
        return (f"Bash: {intent}", cmd)
    if tool_name == "Write":
        path = str(data.get("file_path") or "")
        content = str(data.get("content") or "")
        return (f"Write file: {path}", content)
    if tool_name.endswith("gui_new_document"):
        return (f"Create FreeCAD document at {data.get('path', '?')}", "")
    if tool_name.endswith("gui_open_document"):
        return (f"Open FreeCAD document at {data.get('path', '?')}", "")
    return (tool_name, str(data))


def _guess_intent(cmd: str) -> str:
    for needle, intent in _INTENT_HINTS:
        if needle in cmd:
            return intent
    return ""


def is_dry_run(tool_input: dict) -> bool:
    """Dry-run invocations never touch the document — auto-allow them."""
    return bool((tool_input or {}).get("dry_run"))


@dataclass
class Decision:
    """User's verdict from a PermissionRow.

    ``scope`` is one of:

    * ``"once"`` — allow this specific invocation only.
    * ``"always"`` — allow this tool for the rest of the session; subsequent
      calls skip the prompt.
    * ``"deny"`` — reject this invocation; ``allowed`` is False.

    ``allowed`` stays for back-compat (and is False only when ``scope=="deny"``).
    """
    allowed: bool
    reason: str = ""
    scope: str = "once"


# Session-scoped allowlist: tool names the user has ticked "Allow always" for.
# Cleared when ``make_can_use_tool`` is recreated — i.e. on new session /
# client rebuild. A simple module-level set is fine because the runtime builds
# exactly one callback per live client.
_SESSION_ALLOWLIST: set[str] = set()


def clear_session_allowlist() -> None:
    """Invoked by the runtime when a new session begins."""
    _SESSION_ALLOWLIST.clear()


def session_allowlist() -> set[str]:
    return set(_SESSION_ALLOWLIST)


def make_can_use_tool(proxy, permission_mode: str = "default", doc_dir_provider=None):
    """Return a `can_use_tool` coroutine that asks the GUI thread via `proxy`.

    `proxy` is a `_PanelProxy` QObject whose `permissionRequest` signal is
    connected to a slot that creates a card on the panel and resolves the
    provided concurrent.futures.Future on Apply / Reject.

    ``permission_mode`` is the effective mode for the current SDK client.
    When the SDK receives a ``can_use_tool`` callback, it delegates every
    decision to us regardless of its own permission mode — so we replicate
    the mode semantics here:

    * ``bypassPermissions`` — allow everything without prompting.
    * ``acceptEdits`` — auto-allow mutating tools; still prompt for anything
      else that isn't explicitly read-only.
    * ``default`` / ``plan`` — prompt as before.
    """

    auto_allow_all = permission_mode == "bypassPermissions"
    auto_allow_edits = permission_mode == "acceptEdits"
    plan_only = permission_mode == "plan"

    async def can_use_tool(tool_name, tool_input, context=None):
        # PreToolUse hook runs first — a user-configured command can block
        # any tool (including read-only) before mode logic kicks in. Hook
        # failures are swallowed so settings.json typos can't crash the
        # agent loop.
        try:
            doc_dir = None
            if doc_dir_provider is not None:
                try:
                    doc_dir = doc_dir_provider()
                except Exception:
                    doc_dir = None
            hook_result = hooks.run(
                "PreToolUse",
                {"tool_name": tool_name, "input": tool_input},
                doc_dir=doc_dir,
            )
        except Exception:
            hook_result = None
        if hook_result is not None and hook_result.decision == "block":
            return PermissionResultDeny(
                message=hook_result.message or "Blocked by PreToolUse hook"
            )

        # AskUserQuestion is a built-in SDK tool. Per the Agent SDK docs, the
        # client handles it in can_use_tool and returns the user's answers as
        # `updated_input`; the SDK then feeds those back to the model as the
        # tool result. See https://code.claude.com/docs/en/agent-sdk/user-input
        if tool_name == "AskUserQuestion":
            questions = list((tool_input or {}).get("questions") or [])
            answer_list = await ui_bridge.ask_user(questions)
            # The SDK feeds ``answers`` back to the model keyed by the original
            # question wording. If a question only has a `header` (no
            # `question` text), fall back to the header — and finally to an
            # indexed placeholder — so every question maps to a distinct key.
            # Without this, multiple answers collapse into the empty-string
            # key and the model re-asks the same questions in plain text.
            answers: dict[str, str] = {}
            for idx, (q, ans) in enumerate(zip(questions, answer_list or [])):
                if not isinstance(ans, dict) or ans.get("skipped"):
                    continue
                key = q.get("question") or q.get("header") or f"question_{idx}"
                sel = ans.get("selected")
                if isinstance(sel, list):
                    answers[key] = ", ".join(str(s) for s in sel)
                elif sel:
                    answers[key] = str(sel)
            return PermissionResultAllow(
                updated_input={"questions": questions, "answers": answers}
            )

        if tool_name in READ_ONLY_TOOLS or is_dry_run(tool_input):
            return PermissionResultAllow(updated_input=tool_input)

        # Plan-meta tools are always allowed — the dock runtime consumes
        # their results to render milestone rows / plan files; prompting for
        # them would break the plan-mode handshake.
        if tool_name in PLAN_META_TOOLS:
            return PermissionResultAllow(updated_input=tool_input)

        if auto_allow_all:
            return PermissionResultAllow(updated_input=tool_input)

        # Plan mode: block every remaining tool without prompting. The agent
        # is expected to research via read-only tools and call
        # ``exit_plan_mode``; any mutating call is a protocol violation and
        # should fail fast so the user can review the plan first.
        if plan_only:
            return PermissionResultDeny(
                message=(
                    "Plan mode is active — tool execution is disabled until "
                    "the agent calls exit_plan_mode and the user approves "
                    "the plan."
                )
            )

        if auto_allow_edits and tool_name in FILE_EDIT_TOOLS:
            return PermissionResultAllow(updated_input=tool_input)

        if tool_name in _SESSION_ALLOWLIST:
            return PermissionResultAllow(updated_input=tool_input)

        cf: concurrent.futures.Future = concurrent.futures.Future()
        if tool_name in MUTATING_TOOLS:
            summary, script = _summarise_edit(tool_name, tool_input)
            import uuid
            req_id = uuid.uuid4().hex
            proxy.editApprovalRequest.emit(req_id, summary, script, cf)
        else:
            proxy.permissionRequest.emit(tool_name, tool_input, cf)
        decision = await asyncio.wrap_future(cf)
        if decision.scope == "always" and decision.allowed:
            _SESSION_ALLOWLIST.add(tool_name)
        if decision.allowed:
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=decision.reason or "User rejected this action.")

    return can_use_tool
