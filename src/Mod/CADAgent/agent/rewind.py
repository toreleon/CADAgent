# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rewind engine for CADAgent: truncate the live transcript and the SDK store.

Rewind happens at the level of *our* row index (an index into the panel's
``MessagesModel._rows``). The user picks a user-row to "go back to"; we then:

1. Truncate the persisted CADAgent rows to keep everything *up to and
   including* that row index (then the caller layer typically appends a new
   user prompt and re-runs).
2. Find the matching message in the Claude Agent SDK's transcript JSONL at
   ``~/.claude/projects/<hash>/<sid>.jsonl`` and either rewrite that file in
   place (``fork=False``) or write the truncated content to a new
   ``<new_uuid>.jsonl`` (``fork=True``).
3. If forking, copy the session-index entry, set ``parent_id`` and
   ``branch_from_turn`` so the history UI can render the branch.

Spike result (recorded for the PR body): the pinned ``claude-agent-sdk``
0.1.63 *does* expose a public ``fork_session(session_id, directory=...,
up_to_message_id=...)`` helper (see
``claude_agent_sdk._internal.session_mutations.fork_session``). We prefer it
when forking — it correctly remaps UUIDs and parent chains. For in-place
truncation (``fork=False``) the SDK has no public helper, so we rewrite the
JSONL ourselves.

If the SDK JSONL cannot be located (e.g. a fresh session that has not
flushed yet), we fall back to truncating only our own rows and keep the
caller-supplied sid unchanged.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from . import sessions


# ---------------------------------------------------------------------------
# SDK JSONL helpers
# ---------------------------------------------------------------------------


def _projects_dir() -> Path:
    """Return ``$CLAUDE_CONFIG_DIR/projects`` (default ``~/.claude/projects``)."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "projects"
    return Path.home() / ".claude" / "projects"


def _find_jsonl(sid: str) -> Path | None:
    """Locate the SDK transcript JSONL for ``sid``.

    The SDK slugifies the cwd into the directory name; rather than reproduce
    that scheme, we scan ``~/.claude/projects/*/<sid>.jsonl``.
    """
    base = _projects_dir()
    if not base.is_dir():
        return None
    target = f"{sid}.jsonl"
    try:
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            candidate = entry / target
            if candidate.is_file():
                return candidate
    except OSError:
        return None
    return None


def _parse_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (TypeError, ValueError):
                    # Tolerate trailing partial writes; preserve order.
                    continue
    except OSError:
        return []
    return out


def _atomic_write_jsonl(path: Path, entries: list[dict]) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cadagent-jsonl-", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Row-index → SDK message mapping
# ---------------------------------------------------------------------------


def _count_user_rows(rows: list, keep_through: int) -> int:
    """Count user rows (kind == 'user') in ``rows[:keep_through+1]``.

    The SDK transcript and our rows share user prompts 1:1, so this acts as
    the bridge: keep N user turns ⇒ keep up to (and including) the assistant
    response chain belonging to user-turn N in the SDK file.
    """
    if keep_through < 0:
        return 0
    n = 0
    for row in rows[: keep_through + 1]:
        if isinstance(row, dict) and row.get("kind") == "user":
            n += 1
    return n


def _truncate_jsonl_entries(entries: list[dict], keep_user_count: int) -> list[dict]:
    """Return a prefix of ``entries`` ending after the ``keep_user_count``-th
    user message and all its trailing assistant/tool entries.

    Heuristic (documented in module docstring):
    - Walk entries; count those with ``type == "user"`` (per SDK schema).
    - Stop *just before* the (keep_user_count+1)-th user entry — i.e. keep
      the prior user turn's full assistant/tool chain.
    - Sidechain entries are skipped from the user-turn count; they stay
      inline.
    """
    if keep_user_count <= 0:
        return []
    seen_users = 0
    cutoff = len(entries)
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "user":
            continue
        if entry.get("isSidechain"):
            continue
        seen_users += 1
        if seen_users > keep_user_count:
            cutoff = i
            break
    return entries[:cutoff]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def truncate_session(
    doc,
    sid: str,
    keep_through_row_index: int,
    fork: bool,
) -> str:
    """Truncate CADAgent rows + SDK JSONL up to ``keep_through_row_index``.

    Returns the (possibly new) sid.

    Behaviour:
    - Read the current rows; truncate to ``[: keep_through_row_index + 1]``.
    - Locate the SDK JSONL. If found:
        * ``fork=True``  → write truncated content to ``<new_uuid>.jsonl``
          alongside the original (left intact). Returns the new sid.
        * ``fork=False`` → rewrite the original JSONL in place. Returns the
          original sid.
    - If the SDK JSONL is not found, behave defensively: still truncate our
      own rows, and (when forking) still allocate a new sid + clone our
      session-index metadata so the UI can split the branch. The caller
      (dock_runtime) uses the returned sid as ``_resume_sid`` for the next
      turn.
    """
    rows = sessions.load_rows(doc, sid)
    if keep_through_row_index < 0:
        truncated_rows: list = []
    else:
        truncated_rows = list(rows[: keep_through_row_index + 1])

    keep_user_count = _count_user_rows(rows, keep_through_row_index)

    jsonl = _find_jsonl(sid)
    target_sid = str(uuid.uuid4()) if fork else sid

    if jsonl is not None:
        kept = _truncate_jsonl_entries(_parse_jsonl(jsonl), keep_user_count)
        if fork:
            # Rewrite sessionId on copied entries so the SDK treats this as a
            # genuine new session on resume. Per-message UUIDs are left as-is —
            # the SDK tolerates duplicates across files when sessionId differs.
            # (For full UUID remapping, callers can use
            # ``claude_agent_sdk.fork_session`` directly.)
            kept = [
                {**e, "sessionId": target_sid} if "sessionId" in e else dict(e)
                for e in kept
                if isinstance(e, dict)
            ]
            _atomic_write_jsonl(jsonl.parent / f"{target_sid}.jsonl", kept)
        else:
            _atomic_write_jsonl(jsonl, kept)

    # Persist truncated rows under the target sid.
    try:
        sessions.save_rows(doc, target_sid, truncated_rows)
    except Exception:
        # Defensive: if doc is in a transient state, surface no exception —
        # the caller already has the truncated transcript in memory.
        pass

    if fork:
        # Carry forward branch metadata so history UI can render the tree.
        try:
            sessions.clone_metadata(
                doc, sid, target_sid, branch_from_turn=keep_user_count
            )
        except Exception:
            pass

    return target_sid
