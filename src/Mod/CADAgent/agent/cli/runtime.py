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
import base64
import json
import mimetypes
import os
import sys
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
)

from .. import memory as project_memory
from ..prompts_cli import CAD_SYSTEM_PROMPT
from ..worker.client import WorkerError, close_shared, get_shared
from . import mcp_tools
from . import verify_gate
from .doc_handle import DocHandle
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


# ---------------------------------------------------------------------------
# auto-probe hook
# ---------------------------------------------------------------------------
#
# After every Bash tool call, look at the active .FCStd. If its mtime moved,
# the script likely mutated geometry — reload the worker's copy and run
# ``inspect.probe`` (bbox + face_types + solids in one round-trip). The
# result is appended to the model's next turn via ``additionalContext`` so
# verification appears "for free" without the agent having to remember.
#
# Failures degrade to a no-op: the model just doesn't get the probe line. We
# never block the Bash result on probe issues — too many legitimate
# intermediate states (e.g. mid-boolean) would tangle the agent loop.


def _active_doc_path() -> str | None:
    p = (os.environ.get("CADAGENT_DOC") or "").strip()
    return p or None


_probe_mtimes: dict[str, float] = {}


def _summarize_probe(probe: dict) -> str:
    """Compact one-line view of the standard probe so the agent sees signal,
    not a 4 KB JSON wall of triage data each turn."""
    bbox = probe.get("bbox") or {}
    size = bbox.get("size") or [0, 0, 0]
    ft = (probe.get("face_types") or {}).get("counts") or {}
    ft_str = ",".join(f"{k}={v}" for k, v in sorted(ft.items()))
    solids = (probe.get("solids") or {}).get("items") or []
    real = [s for s in solids if s.get("n_solids", 0) >= 1]
    invalid = [s["name"] for s in real if not s.get("isValid", True)]
    parts = [
        f"bbox={size[0]:.2f}x{size[1]:.2f}x{size[2]:.2f}",
        f"faces[{ft_str}]" if ft_str else "faces[]",
        f"solids={len(real)}",
    ]
    if invalid:
        parts.append(f"invalid={invalid}")
    return " ".join(parts)


def _summarize_verify(name: str, query: str, result: dict) -> str:
    """One-line summary of a single verify query's result."""
    payload = (result or {}).get("result") or {}
    if "count" in payload:
        return f"{name} `{query}` count={payload['count']}"
    if "size" in payload:
        sz = payload["size"]
        return f"{name} `{query}` size={sz}"
    if "items" in payload:
        return f"{name} `{query}` items={len(payload['items'])}"
    # Fallback — just compact-dump
    return f"{name} `{query}` => {json.dumps(payload, default=str)[:120]}"


async def _run_verifies(client, doc_path: str) -> list[str]:
    """Look up every parameter with a `verify` query and run it."""
    try:
        params = project_memory.get_parameters(DocHandle(doc_path))
    except Exception:
        return []
    out: list[str] = []
    for name, spec in (params or {}).items():
        q = spec.get("verify") if isinstance(spec, dict) else None
        if not q:
            continue
        try:
            r = await client.call("inspect.query", query=str(q))
            out.append(_summarize_verify(name, q, r))
        except WorkerError as exc:
            out.append(f"{name} `{q}` worker-error: {exc}")
        except Exception as exc:
            out.append(f"{name} `{q}` error: {type(exc).__name__}: {exc}")
    return out


_SCRIPT_VERDICT_RE = __import__("re").compile(r"^(RESULT|ERROR):.*", __import__("re").MULTILINE)


def _extract_script_verdict(tool_response: Any) -> str | None:
    """Pull every ``RESULT:`` / ``ERROR:`` line out of a Bash tool response.

    The agent's scripts end with one structured RESULT or ERROR line that
    encodes the script's actual outcome. When the rest of the output is a
    50KB OCC-warning flood, that line gets buried by the SDK's truncation;
    we surface it explicitly so the model always sees the verdict.
    """
    if tool_response is None:
        return None
    text = ""
    if isinstance(tool_response, str):
        text = tool_response
    elif isinstance(tool_response, dict):
        # Bash tool response shape: {"content": [{"type":"text","text":"..."}, ...], ...}
        # or {"stdout": "...", "stderr": "...", "interrupted": ..., ...}
        content = tool_response.get("content")
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    text += "\n" + (blk.get("text") or "")
        for k in ("stdout", "stderr", "output"):
            v = tool_response.get(k)
            if isinstance(v, str):
                text += "\n" + v
    elif isinstance(tool_response, list):
        for blk in tool_response:
            if isinstance(blk, dict) and blk.get("type") == "text":
                text += "\n" + (blk.get("text") or "")
    if not text:
        return None
    full = [m.group(0) for m in _SCRIPT_VERDICT_RE.finditer(text)]
    if not full:
        return None
    return " | ".join(line[:300] for line in full[-3:])


async def _post_bash_probe(input_data, tool_use_id, context):  # noqa: ANN001 — SDK callback signature
    """PostToolUse(Bash) — append script verdict + geometry probe + parameter verifies."""
    pieces: list[str] = []
    # Script verdict — pull RESULT/ERROR lines straight out of the Bash output
    # so the model sees them even when the rest gets truncated.
    try:
        if isinstance(input_data, dict):
            verdict = _extract_script_verdict(input_data.get("tool_response"))
            if verdict:
                pieces.append(f"[script] {verdict}")
    except Exception as exc:
        pieces.append(f"[script] (verdict-extract error: {exc})")
    # Geometry probe + parameter verifies
    try:
        path = _active_doc_path()
        if not path or not os.path.exists(path):
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": " ".join(pieces)}} if pieces else {}
        mtime = os.path.getmtime(path)
        # Always re-run verifies (cheap), but skip the full probe when mtime unchanged.
        full_probe = _probe_mtimes.get(path) != mtime
        _probe_mtimes[path] = mtime
        client = await get_shared()
        await client.call("doc.open", path=path)
        if full_probe:
            await client.call("doc.reload")
            probe = await client.call("inspect.probe")
            pieces.append("[auto-probe] " + _summarize_probe(probe))
        verifies = await _run_verifies(client, path)
        if verifies:
            pieces.append("verify: " + " ; ".join(verifies))
    except WorkerError as exc:
        pieces.append(f"[auto-probe] worker error: {exc}")
    except Exception as exc:
        pieces.append(f"[auto-probe] error: {type(exc).__name__}: {exc}")
    if not pieces:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": " | ".join(pieces),
        }
    }


# ---------------------------------------------------------------------------
# Stop-gate: harness-level enforcement of the spec contract.
#
# The model used to omit features ("simplified for robustness"), claim PASS,
# and exit. Prose can describe the gate; only code can refuse the stop.
# This hook fires when the SDK reports the agent is about to stop. We run
# every parameter's verify query through the worker, and if any fail, we
# return decision="block" with the failed rows in the reason — the SDK
# routes that back as a tool result and the model gets another turn.
#
# Cap at 3 stop-blocks per session so we don't loop indefinitely on a
# verify query the geometry can never satisfy (detector limitation, bad
# verify string, etc.) — on the 3rd attempt we let the stop through with
# the failures persisted to the sidecar so the user sees them.
# ---------------------------------------------------------------------------

_GATE_ATTEMPTS_CAP = 3
_gate_attempts: dict[str, int] = {}


async def _stop_gate(input_data, tool_use_id, context):  # noqa: ANN001 — SDK callback signature
    path = _active_doc_path()
    if not path or not os.path.exists(path):
        return {}
    sys.stderr.write(f"[stop-gate] firing on {path}\n")
    try:
        client = await get_shared()
        await client.call("doc.open", path=path)
        await client.call("doc.reload")
        rows = await verify_gate.run_gate(client, path)
        rows.extend(verify_gate.coverage_rows(path))
    except Exception as exc:
        # Worker dead / sidecar broken — let the stop through; surface the
        # symptom in additionalContext so the user sees it.
        return {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": f"[stop-gate] error: {type(exc).__name__}: {exc}",
            }
        }

    failed = verify_gate.fails(rows)
    attempts = _gate_attempts.get(path, 0)

    # Persist the table so the user can audit it after the run.
    try:
        project_memory.write_note(
            DocHandle(path), "open_questions", "completeness_gate",
            verify_gate.format_table(rows) + f"\n\n(attempt {attempts + 1}/{_GATE_ATTEMPTS_CAP})",
        )
    except Exception as exc:
        sys.stderr.write(f"[stop-gate] persist error: {type(exc).__name__}: {exc}\n")

    if not failed:
        return {}  # all PASS — let the stop through

    if attempts >= _GATE_ATTEMPTS_CAP:
        # Cap hit — let the stop through but tell the model to surface
        # the still-failing rows in its summary.
        return {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": (
                    f"[stop-gate] cap reached ({attempts}/{_GATE_ATTEMPTS_CAP}); "
                    f"{len(failed)} row(s) still FAIL — list them prominently in your final summary, "
                    "do NOT call them 'simplified'.\n"
                    + verify_gate.format_table(rows)
                ),
            }
        }

    _gate_attempts[path] = attempts + 1
    table = verify_gate.format_table(rows)
    fails_brief = ", ".join(f"{r['name']} ({r['detail']})" for r in failed)
    reason = (
        f"Stop blocked by completeness gate (attempt {attempts + 1}/{_GATE_ATTEMPTS_CAP}). "
        f"{len(failed)} verify row(s) FAIL: {fails_brief}. "
        "Emit a Bash that rebuilds the missing/wrong feature(s) — clean up the prior attempt's "
        "named features first (doc.removeObject) so the geometry doesn't double up. "
        "Then verify_spec / inspect again before declaring done.\n\n"
        + table
    )
    return {"decision": "block", "reason": reason}


def build_options(
    *,
    extra_tools: list | None = None,
    extra_allowed_tool_names: list[str] | None = None,
    **overrides: Any,
) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions for the CLI agent.

    ``overrides`` lets in-process hosts (e.g. the FreeCAD dock) replace
    fields like ``permission_mode`` or inject ``can_use_tool`` without
    duplicating the option scaffolding here. ``extra_tools`` and
    ``extra_allowed_tool_names`` let the dock add MCP tools that only
    make sense when running inside FreeCAD (doc inspection / creation).
    """
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    os.environ.setdefault("ANTHROPIC_SMALL_FAST_MODEL", model)

    tool_funcs = list(mcp_tools.TOOL_FUNCS) + list(extra_tools or [])
    server = create_sdk_mcp_server(name="cad", tools=tool_funcs)

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
    allowed = (
        mcp_tools.allowed_tool_names("cad")
        + list(extra_allowed_tool_names or [])
        + sdk_builtins
    )

    kwargs: dict[str, Any] = dict(
        model=model,
        system_prompt=CAD_SYSTEM_PROMPT,
        mcp_servers={"cad": server},
        allowed_tools=allowed,
        agents=build_agents(model),
        permission_mode=os.environ.get("CADAGENT_PERMS", "bypassPermissions"),
        include_partial_messages=True,
        hooks={
            "PostToolUse": [HookMatcher(matcher="Bash", hooks=[_post_bash_probe])],
            "Stop": [HookMatcher(hooks=[_stop_gate])],
        },
        **_thinking_kwargs(),
    )
    kwargs.update(overrides)
    return ClaudeAgentOptions(**kwargs)


def _thinking_kwargs() -> dict[str, Any]:
    """Translate ``CADAGENT_THINKING`` into SDK thinking / effort fields.

    Extended reasoning is verbose and expensive when routed through LiteLLM
    to small models like ``gpt-5-mini`` — default it off. Users who want it
    back can set:

    * ``CADAGENT_THINKING=off``          — disabled (default)
    * ``CADAGENT_THINKING=adaptive``     — model decides per turn
    * ``CADAGENT_THINKING=<int>``        — enabled with that token budget
    * ``CADAGENT_EFFORT=low|medium|high|max`` — optional effort hint
    """
    out: dict[str, Any] = {}
    raw = (os.environ.get("CADAGENT_THINKING") or "").strip().lower()
    if raw in ("", "off", "disabled", "none", "0"):
        out["thinking"] = {"type": "disabled"}
    elif raw == "adaptive":
        out["thinking"] = {"type": "adaptive"}
    else:
        try:
            budget = int(raw)
            if budget > 0:
                out["thinking"] = {"type": "enabled", "budget_tokens": budget}
            else:
                out["thinking"] = {"type": "disabled"}
        except ValueError:
            out["thinking"] = {"type": "disabled"}
    effort = (os.environ.get("CADAGENT_EFFORT") or "").strip().lower()
    if effort in ("low", "medium", "high", "max"):
        out["effort"] = effort
    return out


def _image_block(path: str) -> dict[str, Any]:
    """Build a base64 image content block for the SDK message format."""
    media, _ = mimetypes.guess_type(path)
    if not media or not media.startswith("image/"):
        media = "image/png"  # safe default; vendor accepts the common four
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media, "data": data},
    }


async def _stream_prompt(text: str, images: list[str]) -> AsyncIterator[dict[str, Any]]:
    """Yield one user message with text + image content blocks."""
    content: list[dict[str, Any]] = []
    for img in images:
        content.append(_image_block(img))
    content.append({"type": "text", "text": text})
    yield {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
        "session_id": "default",
    }


async def _drive(prompt: str, images: list[str] | None = None) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write(f"{RED}!{RESET} ANTHROPIC_API_KEY is required\n")
        return 2

    options = build_options()
    stream = Stream()

    images = list(images or [])
    img_note = f" {DIM}(+{len(images)} image{'s' if len(images) != 1 else ''}){RESET}" if images else ""
    sys.stdout.write(f"{ACCENT}>{RESET} {prompt}{img_note}\n")
    sys.stdout.flush()

    # Pre-warm the worker so the first inspect call is sub-100ms instead of
    # paying the ~1.8s FreeCADCmd cold-start mid-conversation.
    try:
        worker = await get_shared()
        doc_path = _active_doc_path()
        if doc_path and os.path.exists(doc_path):
            await worker.call("doc.open", path=doc_path)
            _probe_mtimes[doc_path] = os.path.getmtime(doc_path)
    except Exception as exc:
        sys.stderr.write(f"{DIM}worker pre-warm skipped: {exc}{RESET}\n")

    async with ClaudeSDKClient(options=options) as client:
        if images:
            await client.query(_stream_prompt(prompt, images))
        else:
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

    # Defensive final gate: the SDK's Stop hook only fires when the
    # model issues a clean "I'm done" termination. If the stream ended
    # for any other reason (token cap, model-side hang, an SDK quirk),
    # the gate hasn't run. Run it here unconditionally so the wrapper
    # CLI's exit status reflects spec coverage, not just whether the
    # subprocess exited cleanly.
    exit_code = 0
    try:
        path = _active_doc_path()
        if path and os.path.exists(path):
            client = await get_shared()
            await client.call("doc.open", path=path)
            await client.call("doc.reload")
            rows = await verify_gate.run_gate(client, path)
            rows.extend(verify_gate.coverage_rows(path))
            failed = verify_gate.fails(rows)
            try:
                project_memory.write_note(
                    DocHandle(path), "open_questions", "completeness_gate",
                    verify_gate.format_table(rows) + "\n\n(final, post-stream)",
                )
            except Exception as exc:
                sys.stderr.write(f"[final-gate] persist error: {type(exc).__name__}: {exc}\n")
            if failed:
                sys.stderr.write(
                    f"[final-gate] {len(failed)} row(s) FAIL — see "
                    f"{path}'s sidecar open_questions.completeness_gate\n"
                )
                exit_code = 3  # distinguishes "ran but failed gate" from clean exit
    except Exception as exc:
        sys.stderr.write(f"[final-gate] error: {type(exc).__name__}: {exc}\n")

    try:
        await close_shared()
    except Exception:
        pass
    return exit_code


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        sys.stderr.write("usage: cadagent [--image PATH]... \"<prompt>\"\n")
        return 2
    images: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--image" and i + 1 < len(argv):
            images.append(argv[i + 1])
            i += 2
            continue
        if a.startswith("--image="):
            images.append(a.split("=", 1)[1])
            i += 1
            continue
        rest.append(a)
        i += 1
    prompt = " ".join(rest).strip()
    if not prompt:
        sys.stderr.write("empty prompt\n")
        return 2
    for img in images:
        if not os.path.isfile(img):
            sys.stderr.write(f"image not found: {img}\n")
            return 2

    try:
        return asyncio.run(_drive(prompt, images=images))
    except KeyboardInterrupt:
        sys.stdout.write(f"\n{DIM}interrupted{RESET}\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
