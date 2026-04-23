# SPDX-License-Identifier: LGPL-2.1-or-later
"""Claude Agent SDK hooks for the CAD Agent verification loop.

Hooks run in the SDK worker, NOT on the Qt GUI thread. They may only read
pure-data snapshots (tool_input dicts, tool_response payloads, the
``agent.tools._shared._LAST_RESULT`` cache) and return a ``SyncHookJSONOutput``
dict. They MUST NOT touch ``FreeCAD.ActiveDocument``, ``FreeCADGui``, or any
Qt object: a blocking GUI read from a hook will deadlock against the next
transaction ``run_sync`` is already waiting on.

What each hook does:

- ``preflight_cad`` (PreToolUse):  cheap, stateless input validation. Rejects
  malformed arguments (zero/negative lengths, empty milestone ids) with a
  structured reason so the agent re-plans.
- ``postflight_cad`` (PostToolUse): inspects the tool's structured payload.
  If the tool reports an invalid solid, missing output, or recoverable error,
  injects ``additionalContext`` nudging the agent to call the right recovery
  tool (``verify_sketch``, ``add_sketch_constraint``, …).
- ``on_subagent_stop`` (SubagentStop): logs the transition to stderr so
  orchestration debugging is tractable. UI panel wiring lands in Phase 4.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
from typing import Any


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------


# Tools whose `length` / `depth` / `radius` arg must be strictly positive.
_POSITIVE_NUMERIC_TOOLS: dict[str, tuple[str, ...]] = {
    "mcp__cad__pad": ("length",),
    "mcp__cad__pocket": ("length", "depth"),
    "mcp__cad__make_box": ("length", "width", "height"),
    "mcp__cad__make_cylinder": ("radius", "height"),
    "mcp__cad__make_sphere": ("radius",),
    "mcp__cad__make_cone": ("radius1", "radius2", "height"),
    "mcp__cad__make_parametric_box": ("length", "width", "height"),
    "mcp__cad__make_parametric_cylinder": ("radius", "height"),
    "mcp__cad__make_parametric_plate": ("length", "width", "thickness"),
    "mcp__cad__fillet": ("radius",),
    "mcp__cad__chamfer": ("size",),
}


# Tools where a named id is required and must be non-empty.
_REQUIRED_STRING_IDS: dict[str, tuple[str, ...]] = {
    "mcp__cad__mark_milestone_active": ("milestone_id",),
    "mcp__cad__mark_milestone_done": ("milestone_id",),
    "mcp__cad__mark_milestone_failed": ("milestone_id",),
}


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


async def preflight_cad(input_data: dict, tool_use_id: str | None, context) -> dict:
    """PreToolUse hook: reject obviously-invalid CAD tool calls early."""
    tool_name = input_data.get("tool_name") or ""
    tool_input = input_data.get("tool_input") or {}

    fields = _POSITIVE_NUMERIC_TOOLS.get(tool_name)
    if fields:
        for f in fields:
            if f not in tool_input:
                continue
            try:
                v = float(tool_input[f])
            except (TypeError, ValueError):
                return _deny(
                    f"{tool_name}: argument '{f}' must be a number, got {tool_input[f]!r}."
                )
            if v <= 0:
                return _deny(
                    f"{tool_name}: argument '{f}' must be > 0, got {v}. "
                    f"If you are undoing a feature, use delete_object instead."
                )

    ids = _REQUIRED_STRING_IDS.get(tool_name)
    if ids:
        for f in ids:
            if not (tool_input.get(f) or "").strip():
                return _deny(
                    f"{tool_name}: '{f}' is required. Call get_active_milestone "
                    f"first to discover the current milestone id."
                )

    # emit_plan needs at least one milestone (also enforced by the JSON schema
    # but the SDK's message on schema-level rejection is less actionable).
    if tool_name == "mcp__cad__emit_plan":
        ms = tool_input.get("milestones") or []
        if not isinstance(ms, list) or not ms:
            return _deny(
                "emit_plan: milestones[] is required and must contain at least one "
                "entry. Each milestone needs a title and ideally acceptance_criteria."
            )

    return {}


# ---------------------------------------------------------------------------
# postflight
# ---------------------------------------------------------------------------


# Tools whose response payload carries a geometry summary worth inspecting.
_GEOMETRY_TOOLS: set[str] = {
    "mcp__cad__pad",
    "mcp__cad__pocket",
    "mcp__cad__fillet",
    "mcp__cad__chamfer",
    "mcp__cad__boolean_op",
    "mcp__cad__make_box",
    "mcp__cad__make_cylinder",
    "mcp__cad__make_sphere",
    "mcp__cad__make_cone",
    "mcp__cad__make_parametric_box",
    "mcp__cad__make_parametric_cylinder",
    "mcp__cad__make_parametric_plate",
    "mcp__cad__add_corner_holes",
}


def _extract_response_body(tool_response: Any) -> dict | None:
    """Our tools wrap JSON inside ``content[0].text``. Pull it back out.

    Returns the parsed dict on success, ``None`` if we can't make sense of the
    shape — in that case the postflight hook does nothing rather than guess.
    """
    if isinstance(tool_response, dict) and "content" in tool_response:
        content = tool_response.get("content") or []
        if content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return None
    # Some tools return the dict directly (not wrapped in MCP content).
    if isinstance(tool_response, dict) and ("ok" in tool_response or "error" in tool_response):
        return tool_response
    return None


def _geometry_hint(body: dict) -> str | None:
    """Produce an actionable hint when a geometry tool reports a bad result."""
    if body.get("is_valid_solid") is False:
        return (
            "The tool returned is_valid_solid=false. Call verify_feature on the "
            "created object to get specific failure diagnostics, then consider "
            "adjusting input dimensions or undoing with delete_object."
        )
    warnings = body.get("warnings") or []
    if warnings:
        return (
            f"The tool reported warnings: {warnings}. These are usually "
            "recoverable — consult verify_feature or preview_topology before "
            "the next mutating tool call to confirm the geometry is sound."
        )
    return None


def _sketch_hint(body: dict) -> str | None:
    """Sketch-specific postflight: nudge toward DoF=0 when still underconstrained."""
    dof = body.get("dof")
    if dof is None:
        return None
    try:
        dof = int(dof)
    except (TypeError, ValueError):
        return None
    if dof > 0:
        return (
            f"Sketch has DoF={dof} — still underconstrained. Call "
            "add_sketch_constraint until DoF=0 before padding or pocketing. "
            "verify_sketch reports which constraints are missing."
        )
    if dof < 0:
        conflicting = body.get("conflicting") or []
        return (
            f"Sketch has DoF={dof} with conflicting constraints {conflicting}. "
            "Remove or relax the most recent constraint and verify again."
        )
    return None


async def postflight_cad(input_data: dict, tool_use_id: str | None, context) -> dict:
    """PostToolUse hook: inspect the tool payload and add recovery hints."""
    tool_name = input_data.get("tool_name") or ""
    body = _extract_response_body(input_data.get("tool_response"))
    if body is None:
        return {}

    # Error payloads: surface the error kind / hint to the agent as context.
    if isinstance(body, dict) and body.get("ok") is False:
        err = body.get("error") or {}
        kind = err.get("kind") or "internal_error"
        msg = err.get("message") or "(no message)"
        hint = err.get("hint") or ""
        recover = err.get("recover_tools") or []
        ctx_parts = [f"{tool_name} returned error kind={kind!r}: {msg}"]
        if hint:
            ctx_parts.append(f"hint: {hint}")
        if recover:
            ctx_parts.append(f"recovery tools: {recover}")
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n".join(ctx_parts),
            },
        }

    hint = None
    if tool_name in _GEOMETRY_TOOLS:
        hint = _geometry_hint(body)
    elif tool_name == "mcp__cad__verify_sketch" or tool_name == "mcp__cad__close_sketch":
        hint = _sketch_hint(body)

    if hint:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": hint,
            },
        }
    return {}


# ---------------------------------------------------------------------------
# subagent lifecycle
# ---------------------------------------------------------------------------


async def on_subagent_stop(input_data: dict, tool_use_id: str | None, context) -> dict:
    """Log that a subagent finished. Panel wiring lands in Phase 4."""
    agent_type = input_data.get("agent_type") or "?"
    agent_id = input_data.get("agent_id") or "?"
    sys.stderr.write(
        f"[cadagent hooks] subagent stop: type={agent_type} id={agent_id}\n"
    )
    sys.stderr.flush()
    return {}


# ---------------------------------------------------------------------------
# PreCompact — archive transcripts before the SDK summarises them
# ---------------------------------------------------------------------------


def _transcript_archive_dir(cwd: str) -> str:
    """Return the directory we archive transcripts into.

    Honours ``CADAGENT_TRANSCRIPT_DIR`` when set (lets tests point to a
    scratch path). Otherwise writes alongside the project at
    ``<cwd>/.cadagent.transcripts``.
    """
    env = os.environ.get("CADAGENT_TRANSCRIPT_DIR")
    if env:
        return env
    base = cwd or os.getcwd()
    return os.path.join(base, ".cadagent.transcripts")


async def archive_on_precompact(input_data: dict, tool_use_id: str | None, context) -> dict:
    """PreCompact hook: copy the live transcript to an archive path.

    Compaction rewrites the on-disk transcript to a summary. Archiving it
    first gives us:
      - fodder for the Phase 1 replay harness (deterministic input).
      - a forensic trail when the agent does something surprising in long
        sessions.

    Failures are swallowed — the hook must not block the compaction it
    can't control anyway.
    """
    src = input_data.get("transcript_path") or ""
    session = input_data.get("session_id") or "unknown-session"
    cwd = input_data.get("cwd") or ""
    trigger = input_data.get("trigger") or "auto"
    try:
        if src and os.path.exists(src):
            archive_dir = _transcript_archive_dir(cwd)
            os.makedirs(archive_dir, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
            dest = os.path.join(
                archive_dir, f"{session}-{stamp}-{trigger}.jsonl"
            )
            shutil.copyfile(src, dest)
            sys.stderr.write(
                f"[cadagent hooks] precompact archive: {dest}\n"
            )
            sys.stderr.flush()
    except Exception as exc:  # hook must never raise
        sys.stderr.write(
            f"[cadagent hooks] precompact archive failed ({trigger}): {exc}\n"
        )
        sys.stderr.flush()
    return {}
