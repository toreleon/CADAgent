"""Tests for the rewind engine (W1-B).

Covers:
- ``sessions.truncate_rows`` and ``sessions.clone_metadata``
- ``rewind.truncate_session`` JSONL truncation in place (fork=False)
- ``rewind.truncate_session`` fork (fork=True): produces a new sid, leaves
  the original JSONL intact, clones session-index metadata.
- Defensive behaviour when SDK JSONL is absent.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jsonl(path: Path, sid: str, n_user_turns: int = 3) -> None:
    """Write a synthetic SDK transcript with ``n_user_turns`` user/assistant pairs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i in range(n_user_turns):
        lines.append(json.dumps({
            "type": "user",
            "uuid": str(uuid.uuid4()),
            "sessionId": sid,
            "message": {"content": f"user turn {i}"},
        }))
        lines.append(json.dumps({
            "type": "assistant",
            "uuid": str(uuid.uuid4()),
            "sessionId": sid,
            "message": {"content": f"assistant reply {i}"},
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _user_turn_count(path: Path) -> int:
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") == "user" and not obj.get("isSidechain"):
            n += 1
    return n


@pytest.fixture
def projects_home(tmp_path, monkeypatch):
    """Redirect SDK projects dir into tmp_path via CLAUDE_CONFIG_DIR."""
    home = tmp_path / "claude_home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    (home / "projects" / "stub").mkdir(parents=True, exist_ok=True)
    return home / "projects" / "stub"


# ---------------------------------------------------------------------------
# sessions.truncate_rows / clone_metadata
# ---------------------------------------------------------------------------


def test_truncate_rows_keeps_prefix(fake_doc):
    from agent import sessions

    sid = str(uuid.uuid4())
    rows = [
        {"rowId": "r0", "kind": "user", "text": "hello"},
        {"rowId": "r1", "kind": "assistant", "text": "hi"},
        {"rowId": "r2", "kind": "user", "text": "hello again"},
        {"rowId": "r3", "kind": "assistant", "text": "hi again"},
    ]
    sessions.save_rows(fake_doc, sid, rows)
    out = sessions.truncate_rows(fake_doc, sid, keep_through_index=1)
    assert [r["rowId"] for r in out] == ["r0", "r1"]
    assert sessions.load_rows(fake_doc, sid) == out


def test_truncate_rows_negative_clears(fake_doc):
    from agent import sessions

    sid = str(uuid.uuid4())
    sessions.save_rows(fake_doc, sid, [{"rowId": "r0", "kind": "user"}])
    out = sessions.truncate_rows(fake_doc, sid, keep_through_index=-1)
    assert out == []
    assert sessions.load_rows(fake_doc, sid) == []


def test_clone_metadata_creates_branch_entry(fake_doc):
    from agent import sessions

    src_sid = str(uuid.uuid4())
    sessions.record_turn(fake_doc, src_sid, "first prompt for source session")

    new_sid = str(uuid.uuid4())
    entry = sessions.clone_metadata(fake_doc, src_sid, new_sid, branch_from_turn=2)
    assert entry is not None
    assert entry["id"] == new_sid
    assert entry["parent_id"] == src_sid
    assert entry["branch_from_turn"] == 2
    assert entry["archived"] is False
    assert "(fork)" in entry["title"]

    # Persisted in the index.
    found = sessions.find(fake_doc, new_sid)
    assert found == entry


def test_clone_metadata_missing_src_returns_none(fake_doc):
    from agent import sessions

    out = sessions.clone_metadata(fake_doc, "no-such-sid", "new", branch_from_turn=0)
    assert out is None


# ---------------------------------------------------------------------------
# rewind.truncate_session — fork=False (in-place rewrite)
# ---------------------------------------------------------------------------


def test_truncate_session_in_place(fake_doc, projects_home):
    import agent.rewind as rewind
    from agent import sessions

    sid = str(uuid.uuid4())
    jsonl = projects_home / f"{sid}.jsonl"
    _make_jsonl(jsonl, sid, n_user_turns=3)

    rows = [
        {"rowId": "r0", "kind": "user", "text": "u0"},
        {"rowId": "r1", "kind": "assistant", "text": "a0"},
        {"rowId": "r2", "kind": "user", "text": "u1"},
        {"rowId": "r3", "kind": "assistant", "text": "a1"},
        {"rowId": "r4", "kind": "user", "text": "u2"},
        {"rowId": "r5", "kind": "assistant", "text": "a2"},
    ]
    sessions.save_rows(fake_doc, sid, rows)

    # Keep through r3 (assistant of turn 2). That's 2 user rows in the slice.
    out_sid = rewind.truncate_session(
        fake_doc, sid, keep_through_row_index=3, fork=False
    )
    assert out_sid == sid

    # Our rows truncated.
    assert sessions.load_rows(fake_doc, sid) == rows[:4]

    # SDK JSONL truncated to 2 user turns (in-place rewrite).
    assert jsonl.exists()
    assert _user_turn_count(jsonl) == 2


# ---------------------------------------------------------------------------
# rewind.truncate_session — fork=True (new sid, original intact)
# ---------------------------------------------------------------------------


def test_truncate_session_fork(fake_doc, projects_home):
    from agent import rewind, sessions

    sid = str(uuid.uuid4())
    jsonl = projects_home / f"{sid}.jsonl"
    _make_jsonl(jsonl, sid, n_user_turns=3)

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

    out_sid = rewind.truncate_session(
        fake_doc, sid, keep_through_row_index=3, fork=True
    )
    assert out_sid != sid
    # Sanity: looks like a UUID.
    uuid.UUID(out_sid)

    # Original JSONL untouched (3 user turns still there).
    assert _user_turn_count(jsonl) == 3
    # New JSONL exists with 2 user turns.
    new_jsonl = projects_home / f"{out_sid}.jsonl"
    assert new_jsonl.exists()
    assert _user_turn_count(new_jsonl) == 2

    # New rows persisted under new sid (truncated).
    assert sessions.load_rows(fake_doc, out_sid) == rows[:4]
    # Original rows intact.
    assert sessions.load_rows(fake_doc, sid) == rows

    # Branch metadata recorded.
    branch = sessions.find(fake_doc, out_sid)
    assert branch is not None
    assert branch["parent_id"] == sid
    assert branch["branch_from_turn"] == 2


# ---------------------------------------------------------------------------
# Defensive behaviour: SDK JSONL absent
# ---------------------------------------------------------------------------


def test_truncate_session_no_jsonl_only_truncates_rows(fake_doc, projects_home):
    from agent import rewind, sessions

    sid = str(uuid.uuid4())
    rows = [
        {"rowId": "r0", "kind": "user", "text": "u0"},
        {"rowId": "r1", "kind": "assistant", "text": "a0"},
        {"rowId": "r2", "kind": "user", "text": "u1"},
    ]
    sessions.save_rows(fake_doc, sid, rows)

    # No JSONL written for ``sid``: defensive path.
    out_sid = rewind.truncate_session(
        fake_doc, sid, keep_through_row_index=1, fork=False
    )
    assert out_sid == sid
    assert sessions.load_rows(fake_doc, sid) == rows[:2]


def test_truncate_session_fork_no_jsonl_still_branches(fake_doc, projects_home):
    from agent import rewind, sessions

    sid = str(uuid.uuid4())
    rows = [
        {"rowId": "r0", "kind": "user", "text": "u0"},
        {"rowId": "r1", "kind": "assistant", "text": "a0"},
    ]
    sessions.save_rows(fake_doc, sid, rows)
    sessions.record_turn(fake_doc, sid, "first")

    out_sid = rewind.truncate_session(
        fake_doc, sid, keep_through_row_index=1, fork=True
    )
    assert out_sid != sid
    uuid.UUID(out_sid)
    # Truncated rows under new sid (here the slice is the full list).
    assert sessions.load_rows(fake_doc, out_sid) == rows
    # Branch metadata recorded.
    assert sessions.find(fake_doc, out_sid) is not None
