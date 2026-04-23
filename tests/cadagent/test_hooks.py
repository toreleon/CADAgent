"""Unit tests for agent/hooks.py.

Hooks are pure-data: they receive dicts and return dicts. No FreeCAD, no Qt,
no network. Test them directly.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def hooks():
    mod_dir = Path(__file__).resolve().parents[2] / "src" / "Mod" / "CADAgent"
    sys.path.insert(0, str(mod_dir))
    if "agent.hooks" in sys.modules:
        del sys.modules["agent.hooks"]
    import agent.hooks as h
    return h


def _run(coro):
    return asyncio.run(coro)


# --- preflight -------------------------------------------------------------


def test_preflight_allows_valid_pad(hooks):
    out = _run(hooks.preflight_cad(
        {"tool_name": "mcp__cad__pad", "tool_input": {"sketch": "Sketch", "length": 5.0}},
        None, None,
    ))
    assert out == {}


def test_preflight_denies_zero_length_pad(hooks):
    out = _run(hooks.preflight_cad(
        {"tool_name": "mcp__cad__pad", "tool_input": {"length": 0}},
        None, None,
    ))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "length" in reason and "> 0" in reason


def test_preflight_denies_negative_radius_cylinder(hooks):
    out = _run(hooks.preflight_cad(
        {"tool_name": "mcp__cad__make_cylinder", "tool_input": {"radius": -1, "height": 5}},
        None, None,
    ))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_preflight_denies_non_numeric_length(hooks):
    out = _run(hooks.preflight_cad(
        {"tool_name": "mcp__cad__make_box", "tool_input": {"length": "tall", "width": 1, "height": 1}},
        None, None,
    ))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "must be a number" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_preflight_ignores_missing_optional_fields(hooks):
    # pocket has two optional numeric fields — only those present get checked.
    out = _run(hooks.preflight_cad(
        {"tool_name": "mcp__cad__pocket", "tool_input": {"sketch": "S", "length": 3}},
        None, None,
    ))
    assert out == {}


def test_preflight_requires_milestone_id(hooks):
    out = _run(hooks.preflight_cad(
        {"tool_name": "mcp__cad__mark_milestone_done", "tool_input": {"milestone_id": ""}},
        None, None,
    ))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "milestone_id" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_preflight_rejects_emit_plan_without_milestones(hooks):
    out = _run(hooks.preflight_cad(
        {"tool_name": "mcp__cad__emit_plan", "tool_input": {"milestones": []}},
        None, None,
    ))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "milestones" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_preflight_allows_unknown_tools(hooks):
    # The hook is only opinionated about CAD tools it knows. Everything else
    # (Bash, Read, user-added tools) must pass through unchanged.
    out = _run(hooks.preflight_cad(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        None, None,
    ))
    assert out == {}


# --- postflight ------------------------------------------------------------


def _mcp_body(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def test_postflight_flags_invalid_solid(hooks):
    out = _run(hooks.postflight_cad(
        {
            "tool_name": "mcp__cad__pad",
            "tool_response": _mcp_body({"ok": True, "is_valid_solid": False, "created": ["Pad"]}),
        },
        None, None,
    ))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "is_valid_solid" in ctx
    assert "verify_feature" in ctx


def test_postflight_surfaces_warnings(hooks):
    out = _run(hooks.postflight_cad(
        {
            "tool_name": "mcp__cad__boolean_op",
            "tool_response": _mcp_body({
                "ok": True, "is_valid_solid": True, "warnings": ["tiny face tolerance"],
            }),
        },
        None, None,
    ))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "tiny face tolerance" in ctx


def test_postflight_silent_on_clean_result(hooks):
    out = _run(hooks.postflight_cad(
        {
            "tool_name": "mcp__cad__make_box",
            "tool_response": _mcp_body({"ok": True, "is_valid_solid": True, "warnings": []}),
        },
        None, None,
    ))
    assert out == {}


def test_postflight_nudges_on_sketch_dof_positive(hooks):
    out = _run(hooks.postflight_cad(
        {
            "tool_name": "mcp__cad__verify_sketch",
            "tool_response": _mcp_body({"ok": True, "dof": 3, "malformed": [], "conflicting": []}),
        },
        None, None,
    ))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "DoF=3" in ctx
    assert "add_sketch_constraint" in ctx


def test_postflight_nudges_on_sketch_dof_negative(hooks):
    out = _run(hooks.postflight_cad(
        {
            "tool_name": "mcp__cad__close_sketch",
            "tool_response": _mcp_body({
                "ok": True, "dof": -1, "conflicting": [7, 8], "malformed": [],
            }),
        },
        None, None,
    ))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "DoF=-1" in ctx
    assert "[7, 8]" in ctx


def test_postflight_surfaces_error_payload(hooks):
    out = _run(hooks.postflight_cad(
        {
            "tool_name": "mcp__cad__pad",
            "tool_response": _mcp_body({
                "ok": False,
                "error": {
                    "kind": "sketch_underconstrained",
                    "message": "DoF=2",
                    "hint": "add horizontal + vertical dimension",
                    "recover_tools": ["add_sketch_constraint"],
                },
            }),
        },
        None, None,
    ))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "sketch_underconstrained" in ctx
    assert "add_sketch_constraint" in ctx
    assert "DoF=2" in ctx


def test_postflight_noop_on_unparseable_response(hooks):
    # Response isn't our shape — hook stays silent rather than guess.
    out = _run(hooks.postflight_cad(
        {"tool_name": "mcp__cad__pad", "tool_response": "some string"},
        None, None,
    ))
    assert out == {}


def test_postflight_noop_on_non_geometry_tool(hooks):
    # Read-only tool whose response doesn't warrant geometry hints.
    out = _run(hooks.postflight_cad(
        {
            "tool_name": "mcp__cad__list_documents",
            "tool_response": _mcp_body({"ok": True, "documents": ["d1"]}),
        },
        None, None,
    ))
    assert out == {}


# --- subagent stop ---------------------------------------------------------


def test_on_subagent_stop_returns_empty_dict(hooks, capsys):
    out = _run(hooks.on_subagent_stop(
        {"agent_type": "reviewer", "agent_id": "agent-42"},
        None, None,
    ))
    assert out == {}
    captured = capsys.readouterr()
    assert "subagent stop" in captured.err
    assert "reviewer" in captured.err
