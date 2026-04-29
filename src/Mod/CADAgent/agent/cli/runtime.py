# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared agent runtime used by the in-FreeCAD chat dock.

Builds the ``ClaudeAgentOptions`` (system prompt, MCP tool surface, hooks,
subagents, thinking config) consumed by :mod:`agent.cli.dock_runtime`. The
post-Bash auto-probe hook and the Stop completeness gate live here so the
behaviour is identical regardless of which host wires up the SDK client.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, create_sdk_mcp_server

from .. import memory as project_memory
from ..prompts_cli import CAD_SYSTEM_PROMPT
from ..worker.client import WorkerError, get_shared
from . import mcp_tools
from . import verify_gate
from .doc_handle import DocHandle
from .subagents import build_agents


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


_SCRIPT_VERDICT_RE = re.compile(r"^(RESULT|ERROR):.*", re.MULTILINE)


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
    try:
        if isinstance(input_data, dict):
            verdict = _extract_script_verdict(input_data.get("tool_response"))
            if verdict:
                pieces.append(f"[script] {verdict}")
    except Exception as exc:
        pieces.append(f"[script] (verdict-extract error: {exc})")
    try:
        path = _active_doc_path()
        if not path or not os.path.exists(path):
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": " ".join(pieces)}} if pieces else {}
        mtime = os.path.getmtime(path)
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
        return {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": f"[stop-gate] error: {type(exc).__name__}: {exc}",
            }
        }

    failed = verify_gate.fails(rows)
    attempts = _gate_attempts.get(path, 0)

    try:
        project_memory.write_note(
            DocHandle(path), "open_questions", "completeness_gate",
            verify_gate.format_table(rows) + f"\n\n(attempt {attempts + 1}/{_GATE_ATTEMPTS_CAP})",
        )
    except Exception as exc:
        sys.stderr.write(f"[stop-gate] persist error: {type(exc).__name__}: {exc}\n")

    if not failed:
        return {}

    if attempts >= _GATE_ATTEMPTS_CAP:
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
    """Build ClaudeAgentOptions for the in-FreeCAD agent.

    ``overrides`` lets the dock replace fields like ``permission_mode`` or
    inject ``can_use_tool`` without duplicating the option scaffolding here.
    ``extra_tools`` and ``extra_allowed_tool_names`` let the dock add MCP
    tools that only make sense when running inside FreeCAD (doc inspection /
    creation).
    """
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    os.environ.setdefault("ANTHROPIC_SMALL_FAST_MODEL", model)

    tool_funcs = list(mcp_tools.TOOL_FUNCS) + list(extra_tools or [])
    server = create_sdk_mcp_server(name="cad", tools=tool_funcs)

    # SDK built-ins the agent is allowed to use. Deliberately excluding Edit:
    # the agent is supposed to write new .py scripts via Bash heredocs,
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
