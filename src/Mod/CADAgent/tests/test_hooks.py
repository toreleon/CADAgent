# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unit tests for ``agent.hooks``.

Covers settings discovery + override, regex matcher, the four documented
result paths from the executor (block / allow / timeout / malformed), and
the no-op when no settings file exists. Subprocess invocations are stubbed
via monkeypatch so the suite runs offline.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent import hooks


@pytest.fixture(autouse=True)
def _isolate_hooks(tmp_path, monkeypatch):
    """Point hooks at tmp dirs and flush its mtime cache between tests."""
    user = tmp_path / "user_settings.json"
    monkeypatch.setattr(hooks, "_USER_SETTINGS_PATH", user)
    hooks._clear_cache()
    yield
    hooks._clear_cache()


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> MagicMock:
    res = MagicMock()
    res.stdout = stdout
    res.stderr = stderr
    res.returncode = returncode
    return res


# --- settings discovery --------------------------------------------------


def test_missing_settings_returns_empty(tmp_path):
    """No user, no project → empty merged dict, no hooks fire."""
    result = hooks.run("PreToolUse", {"tool_name": "Bash"})
    assert result.decision is None
    assert result.message is None


def test_project_overrides_user(tmp_path, monkeypatch):
    """Project settings.json fully replaces user `hooks` block."""
    user = tmp_path / "user_settings.json"
    monkeypatch.setattr(hooks, "_USER_SETTINGS_PATH", user)
    _write(user, {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "user-cmd"}]}]}})

    proj_dir = tmp_path / "doc"
    proj_dir.mkdir()
    _write(proj_dir / ".cadagent" / "settings.json",
           {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "proj-cmd"}]}]}})

    merged = hooks.load_settings(str(proj_dir))
    cmd = merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd == "proj-cmd"


def test_settings_cache_invalidated_on_mtime(tmp_path, monkeypatch):
    """Editing settings.json picks up without a process restart."""
    user = tmp_path / "user_settings.json"
    monkeypatch.setattr(hooks, "_USER_SETTINGS_PATH", user)
    _write(user, {"hooks": {"Stop": []}})
    hooks.load_settings()
    # Bump mtime + change content.
    import os
    os.utime(user, (1, 1))
    _write(user, {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}})
    os.utime(user, (2, 2))
    merged = hooks.load_settings()
    assert merged["hooks"]["Stop"]


# --- executor: result paths ---------------------------------------------


def _install_pretooluse(user_path: Path, matcher: str = ".*", command: str = "fake-hook") -> None:
    _write(user_path, {
        "hooks": {
            "PreToolUse": [
                {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
            ]
        }
    })


def test_block_decision(monkeypatch):
    user = hooks._USER_SETTINGS_PATH
    _install_pretooluse(user)
    monkeypatch.setattr(
        hooks.subprocess, "run",
        lambda *a, **kw: _completed(json.dumps({"decision": "block", "message": "no"}))
    )
    res = hooks.run("PreToolUse", {"tool_name": "Bash"})
    assert res.decision == "block"
    assert res.message == "no"


def test_allow_decision(monkeypatch):
    user = hooks._USER_SETTINGS_PATH
    _install_pretooluse(user)
    monkeypatch.setattr(
        hooks.subprocess, "run",
        lambda *a, **kw: _completed(json.dumps({"decision": "allow"}))
    )
    res = hooks.run("PreToolUse", {"tool_name": "Bash"})
    assert res.decision == "allow"


def test_timeout_is_noop(monkeypatch):
    user = hooks._USER_SETTINGS_PATH
    _install_pretooluse(user)

    def _boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="fake-hook", timeout=5)

    monkeypatch.setattr(hooks.subprocess, "run", _boom)
    res = hooks.run("PreToolUse", {"tool_name": "Bash"})
    assert res.decision is None
    assert res.message is None


def test_malformed_stdout_is_noop(monkeypatch):
    user = hooks._USER_SETTINGS_PATH
    _install_pretooluse(user)
    monkeypatch.setattr(
        hooks.subprocess, "run",
        lambda *a, **kw: _completed("not json at all")
    )
    res = hooks.run("PreToolUse", {"tool_name": "Bash"})
    assert res.decision is None


def test_nonzero_exit_is_noop(monkeypatch):
    user = hooks._USER_SETTINGS_PATH
    _install_pretooluse(user)
    monkeypatch.setattr(
        hooks.subprocess, "run",
        lambda *a, **kw: _completed("", returncode=1, stderr="boom")
    )
    res = hooks.run("PreToolUse", {"tool_name": "Bash"})
    assert res.decision is None


# --- matcher regex -------------------------------------------------------


def test_matcher_regex_filters_tool_name(monkeypatch):
    user = hooks._USER_SETTINGS_PATH
    _install_pretooluse(user, matcher="^Bash$", command="bash-only")
    calls = []

    def _record(argv, **kw):
        calls.append(argv[0])
        return _completed(json.dumps({"decision": "allow"}))

    monkeypatch.setattr(hooks.subprocess, "run", _record)

    res_match = hooks.run("PreToolUse", {"tool_name": "Bash"})
    assert res_match.decision == "allow"
    assert calls == ["bash-only"]

    calls.clear()
    res_skip = hooks.run("PreToolUse", {"tool_name": "Read"})
    assert res_skip.decision is None
    assert calls == []


def test_empty_matcher_matches_all(monkeypatch):
    user = hooks._USER_SETTINGS_PATH
    _write(user, {
        "hooks": {
            "PreToolUse": [
                {"hooks": [{"type": "command", "command": "fallback"}]}
            ]
        }
    })
    monkeypatch.setattr(
        hooks.subprocess, "run",
        lambda *a, **kw: _completed(json.dumps({"decision": "allow"}))
    )
    res = hooks.run("PreToolUse", {"tool_name": "anything"})
    assert res.decision == "allow"


def test_userpromptsubmit_ignores_matcher(monkeypatch):
    """For non-tool events the matcher is irrelevant; every entry runs."""
    user = hooks._USER_SETTINGS_PATH
    _write(user, {
        "hooks": {
            "UserPromptSubmit": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "ups"}]}
            ]
        }
    })
    monkeypatch.setattr(
        hooks.subprocess, "run",
        lambda *a, **kw: _completed(json.dumps({"decision": "block", "message": "stop"}))
    )
    res = hooks.run("UserPromptSubmit", {"prompt": "hi"})
    assert res.decision == "block"
    assert res.message == "stop"


def test_block_short_circuits_remaining_hooks(monkeypatch):
    """First `block` wins; no later hook is spawned."""
    user = hooks._USER_SETTINGS_PATH
    _write(user, {
        "hooks": {
            "Stop": [
                {"hooks": [
                    {"type": "command", "command": "first"},
                    {"type": "command", "command": "second"},
                ]}
            ]
        }
    })
    seen = []

    def _record(argv, **kw):
        seen.append(argv[0])
        return _completed(json.dumps({"decision": "block"}))

    monkeypatch.setattr(hooks.subprocess, "run", _record)
    hooks.run("Stop", {})
    assert seen == ["first"]


def test_unknown_event_is_noop(monkeypatch):
    monkeypatch.setattr(hooks.subprocess, "run", lambda *a, **kw: _completed("{}"))
    res = hooks.run("NotARealEvent", {})
    assert res.decision is None
