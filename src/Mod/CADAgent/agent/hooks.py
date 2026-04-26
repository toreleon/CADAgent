# SPDX-License-Identifier: LGPL-2.1-or-later
"""Claude-Code-style hooks engine for CADAgent.

Loads ``settings.json`` from two locations and lets external commands react
to lifecycle events (``PreToolUse``, ``PostToolUse``, ``UserPromptSubmit``,
``Stop``). A blocking hook can deny a tool call or abort a prompt; any other
outcome is informational.

Settings discovery (project overrides user, top-level key replace):

* ``~/.config/cadagent/settings.json`` — user
* ``<doc_dir>/.cadagent/settings.json`` — project (per active document)

Schema mirrors Claude Code::

    {"hooks": {
        "PreToolUse":        [{"matcher": "regex", "hooks": [{"type": "command", "command": "..."}]}],
        "PostToolUse":       [...],
        "UserPromptSubmit":  [...],
        "Stop":              [...]
    }}

The executor never raises into the agent loop: timeouts, non-zero exits, and
malformed stdout all degrade to a non-blocking ``HookResult``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_USER_SETTINGS_PATH = Path.home() / ".config" / "cadagent" / "settings.json"
_PROJECT_REL = Path(".cadagent") / "settings.json"

_VALID_EVENTS = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop")
_TIMEOUT_SECONDS = 5.0


@dataclass
class HookResult:
    """Outcome of running matched hooks for a single event.

    ``decision`` is ``"block"``, ``"allow"``, or ``None`` (no opinion).
    The first matched hook that returns ``"block"`` short-circuits the rest;
    otherwise the last non-None decision wins. ``output`` carries the
    optional ``hookSpecificOutput`` field for downstream consumers.
    """
    decision: str | None = None
    message: str | None = None
    output: dict | None = None
    event: str = ""


# --- settings loading ----------------------------------------------------
#
# Cache keyed by the resolved (user_path, project_path) tuple. We re-read
# whenever either file's mtime changes so live edits to settings.json take
# effect without a runtime restart.

_settings_cache: dict[tuple[str, str], tuple[tuple[float, float], dict]] = {}


def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        _log.debug("hooks: ignoring settings at %s (%s)", path, exc)
        return {}


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _project_path(doc_dir: str | None) -> Path | None:
    if not doc_dir:
        return None
    try:
        return Path(doc_dir) / _PROJECT_REL
    except (TypeError, ValueError):
        return None


def load_settings(doc_dir: str | None = None) -> dict:
    """Return merged settings dict, with project keys overriding user keys.

    Top-level keys are *replaced*, not deep-merged: a project ``hooks`` block
    fully shadows the user ``hooks`` block. This keeps the override model
    obvious — easier than reasoning about per-event list concatenation.
    """
    user_path = _USER_SETTINGS_PATH
    proj_path = _project_path(doc_dir)
    proj_str = str(proj_path) if proj_path else ""
    key = (str(user_path), proj_str)
    mtimes = (_mtime(user_path), _mtime(proj_path) if proj_path else 0.0)

    cached = _settings_cache.get(key)
    if cached is not None and cached[0] == mtimes:
        return cached[1]

    merged: dict = dict(_read_json(user_path)) if user_path.exists() else {}
    if proj_path and proj_path.exists():
        for k, v in _read_json(proj_path).items():
            merged[k] = v
    _settings_cache[key] = (mtimes, merged)
    return merged


def _clear_cache() -> None:
    """Test helper — flush the mtime cache."""
    _settings_cache.clear()


def settings_source(doc_dir: str | None = None) -> tuple[str, dict]:
    """Return ``(source, merged_settings)`` for the topbar indicator.

    ``source`` is one of ``"project"``, ``"user"``, or ``"none"``. Project
    wins when its settings.json exists (mirrors the override semantics in
    :func:`load_settings`); user wins when only the user file exists; and
    ``"none"`` means neither file is present even if ``load_settings``
    returned a cached empty dict.
    """
    proj_path = _project_path(doc_dir)
    settings = load_settings(doc_dir)
    if proj_path is not None and proj_path.exists():
        return "project", settings
    if _USER_SETTINGS_PATH.exists():
        return "user", settings
    return "none", settings


# --- execution -----------------------------------------------------------


def _matches(matcher: str | None, tool_name: str) -> bool:
    """Return True if ``matcher`` (regex) matches ``tool_name``.

    Empty / missing matcher always matches. Bad regex degrades to "match all"
    so a typo in settings.json doesn't silently disable every hook.
    """
    if not matcher:
        return True
    try:
        return re.search(matcher, tool_name or "") is not None
    except re.error:
        _log.warning("hooks: invalid matcher regex %r — treating as match-all", matcher)
        return True


def _iter_commands(entries: list, event_name: str, tool_name: str):
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if event_name in ("PreToolUse", "PostToolUse"):
            if not _matches(entry.get("matcher"), tool_name):
                continue
        for h in entry.get("hooks") or []:
            if not isinstance(h, dict):
                continue
            if h.get("type") != "command":
                continue
            cmd = h.get("command")
            if isinstance(cmd, str) and cmd.strip():
                yield cmd


def _run_one(command: str, payload_json: str) -> dict | None:
    """Spawn one hook command, return parsed stdout JSON or None."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        _log.warning("hooks: cannot parse command %r (%s)", command, exc)
        return None
    if not argv:
        return None
    try:
        proc = subprocess.run(
            argv,
            input=payload_json,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log.info("hooks: command %r failed (%s)", command, exc)
        return None
    if proc.returncode != 0:
        _log.info(
            "hooks: command %r exited %d: %s",
            command, proc.returncode, (proc.stderr or "").strip()[:200],
        )
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return {}
    try:
        data = json.loads(out)
    except (TypeError, ValueError):
        _log.info("hooks: command %r produced non-JSON stdout", command)
        return None
    return data if isinstance(data, dict) else None


def run(
    event_name: str,
    payload: dict | None = None,
    doc_dir: str | None = None,
) -> HookResult:
    """Execute every hook registered for ``event_name`` and aggregate results.

    Never raises. The first ``"block"`` decision short-circuits remaining
    hooks; otherwise the last non-None decision and its message win.
    """
    result = HookResult(event=event_name)
    if event_name not in _VALID_EVENTS:
        return result
    payload = payload or {}
    try:
        settings = load_settings(doc_dir)
    except Exception as exc:  # defensive — load_settings already swallows
        _log.debug("hooks: settings load failed (%s)", exc)
        return result
    entries = ((settings.get("hooks") or {}).get(event_name)) or []
    if not entries:
        return result

    tool_name = str(payload.get("tool_name") or "")
    payload_json = json.dumps(payload, default=str)

    for command in _iter_commands(entries, event_name, tool_name):
        try:
            data = _run_one(command, payload_json)
        except Exception as exc:  # belt-and-braces
            _log.debug("hooks: unexpected error from %r (%s)", command, exc)
            data = None
        if not data:
            continue
        decision = data.get("decision")
        message = data.get("message")
        output = data.get("hookSpecificOutput")
        if decision in ("block", "allow"):
            result.decision = decision
        if isinstance(message, str):
            result.message = message
        if isinstance(output, dict):
            result.output = output
        if decision == "block":
            break
    return result


# Public re-exports for tests / external consumers.
__all__ = ["HookResult", "run", "load_settings", "settings_source"]
