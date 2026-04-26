# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for ``rewind.truncate_session(..., seed_summary=...)`` (Wave 1, Unit B).

The seed_summary parameter prepends a synthetic user/assistant exchange to a
forked JSONL so a freshly-forked SDK session resumes with the compaction
summary as its first turn.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest


def _make_jsonl(path: Path, sid: str, n_user_turns: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i in range(n_user_turns):
        lines.append(json.dumps({
            "type": "user",
            "uuid": str(uuid.uuid4()),
            "sessionId": sid,
            "parentUuid": None,
            "message": {"content": f"user turn {i}"},
        }))
        lines.append(json.dumps({
            "type": "assistant",
            "uuid": str(uuid.uuid4()),
            "sessionId": sid,
            "parentUuid": None,
            "message": {"content": f"assistant reply {i}"},
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


@pytest.fixture
def projects_home(tmp_path, monkeypatch):
    home = tmp_path / "claude_home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    (home / "projects" / "stub").mkdir(parents=True, exist_ok=True)
    return home / "projects" / "stub"


def _seed_rows(fake_doc, sid):
    from agent import sessions

    rows = [
        {"rowId": "r0", "kind": "user", "text": "u0"},
        {"rowId": "r1", "kind": "assistant", "text": "a0"},
        {"rowId": "r2", "kind": "user", "text": "u1"},
        {"rowId": "r3", "kind": "assistant", "text": "a1"},
        {"rowId": "r4", "kind": "user", "text": "u2"},
        {"rowId": "r5", "kind": "assistant", "text": "a2"},
    ]
    sessions.save_rows(fake_doc, sid, rows)
    sessions.record_turn(fake_doc, sid, "first")
    return rows


def test_fork_with_seed_summary_prepends_synthetic_exchange(fake_doc, projects_home):
    from agent import rewind

    sid = str(uuid.uuid4())
    jsonl = projects_home / f"{sid}.jsonl"
    _make_jsonl(jsonl, sid, n_user_turns=3)
    _seed_rows(fake_doc, sid)

    summary = "<compaction-summary>X</compaction-summary>"
    out_sid = rewind.truncate_session(
        fake_doc, sid, keep_through_row_index=3, fork=True, seed_summary=summary
    )
    assert out_sid != sid

    new_jsonl = projects_home / f"{out_sid}.jsonl"
    assert new_jsonl.exists()
    entries = _read_jsonl(new_jsonl)

    # First two rows are the synthetic exchange.
    assert len(entries) >= 2
    syn_user, syn_assistant = entries[0], entries[1]

    assert syn_user["type"] == "user"
    assert syn_user["parentUuid"] is None
    assert syn_user["sessionId"] == out_sid
    assert syn_user["message"]["content"][0]["text"] == summary

    assert syn_assistant["type"] == "assistant"
    assert syn_assistant["parentUuid"] == syn_user["uuid"]
    assert syn_assistant["sessionId"] == out_sid
    assert (
        syn_assistant["message"]["content"][0]["text"]
        == "Acknowledged. Continuing from the summary above."
    )

    # The first real row's parentUuid is re-chained to the synthetic assistant.
    assert entries[2]["parentUuid"] == syn_assistant["uuid"]

    # Original JSONL untouched.
    assert len(_read_jsonl(jsonl)) == 6


def test_fork_default_seed_summary_none_has_no_synthetic_head(fake_doc, projects_home):
    from agent import rewind

    sid = str(uuid.uuid4())
    jsonl = projects_home / f"{sid}.jsonl"
    _make_jsonl(jsonl, sid, n_user_turns=3)
    _seed_rows(fake_doc, sid)

    out_sid = rewind.truncate_session(
        fake_doc, sid, keep_through_row_index=3, fork=True
    )
    new_jsonl = projects_home / f"{out_sid}.jsonl"
    entries = _read_jsonl(new_jsonl)

    # No synthetic head: the first row is a real user turn from the original
    # transcript ("user turn 0"), not the acknowledgement text.
    assert entries[0]["type"] == "user"
    assert entries[0]["message"]["content"] == "user turn 0"
    # No row contains the synthetic acknowledgement.
    for e in entries:
        msg = e.get("message", {})
        content = msg.get("content")
        if isinstance(content, list):
            for c in content:
                assert "Acknowledged. Continuing from the summary above." not in (
                    c.get("text", "") if isinstance(c, dict) else ""
                )


def test_fork_false_ignores_seed_summary(fake_doc, projects_home):
    from agent import rewind

    sid = str(uuid.uuid4())
    jsonl = projects_home / f"{sid}.jsonl"
    _make_jsonl(jsonl, sid, n_user_turns=3)
    _seed_rows(fake_doc, sid)

    summary = "<compaction-summary>should be ignored</compaction-summary>"
    out_sid = rewind.truncate_session(
        fake_doc,
        sid,
        keep_through_row_index=3,
        fork=False,
        seed_summary=summary,
    )
    assert out_sid == sid

    entries = _read_jsonl(jsonl)
    # In-place rewrite: 2 user turns (truncated), no synthetic head.
    assert entries[0]["type"] == "user"
    assert entries[0]["message"]["content"] == "user turn 0"
    for e in entries:
        msg = e.get("message", {})
        content = msg.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    assert summary not in c.get("text", "")
