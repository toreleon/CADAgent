"""Tests for v3 compaction + token helpers in agent.sessions."""
from __future__ import annotations

from agent import sessions


# --- mark_compacted ---------------------------------------------------------


def test_mark_compacted_updates_existing_entry(fake_doc):
    sessions.record_turn(fake_doc, "parent", "root prompt")
    sessions.record_turn(fake_doc, "child", "post-compact prompt")

    sessions.mark_compacted(fake_doc, "child", "parent")

    entry = sessions.find(fake_doc, "child")
    assert entry["compacted"] is True
    assert entry["compacted_from"] == "parent"
    # parent untouched
    parent = sessions.find(fake_doc, "parent")
    assert parent["compacted"] is False
    assert parent["compacted_from"] is None


def test_mark_compacted_creates_stub_when_missing(fake_doc):
    sessions.record_turn(fake_doc, "parent", "the original prompt")

    sessions.mark_compacted(fake_doc, "new-sid", "parent")

    stub = sessions.find(fake_doc, "new-sid")
    assert stub is not None
    assert stub["compacted"] is True
    assert stub["compacted_from"] == "parent"
    assert stub["title"] == sessions.find(fake_doc, "parent")["title"]
    assert stub["first_prompt"] == "the original prompt"
    assert stub["turn_count"] == 0
    assert stub["tokens"] == {
        "input_total": 0,
        "output_total": 0,
        "last_seen": None,
    }


def test_mark_compacted_creates_stub_with_defaults_when_parent_missing(fake_doc):
    sessions.mark_compacted(fake_doc, "orphan", "ghost-parent")

    stub = sessions.find(fake_doc, "orphan")
    assert stub is not None
    assert stub["compacted"] is True
    assert stub["compacted_from"] == "ghost-parent"
    assert stub["title"] == "Untitled chat"


def test_mark_compacted_is_idempotent(fake_doc):
    sessions.record_turn(fake_doc, "parent", "p")
    sessions.mark_compacted(fake_doc, "child", "parent")
    sessions.mark_compacted(fake_doc, "child", "parent")
    sessions.mark_compacted(fake_doc, "child", "parent")

    matches = [s for s in sessions.list_sessions(fake_doc) if s["id"] == "child"]
    assert len(matches) == 1
    assert matches[0]["compacted"] is True
    assert matches[0]["compacted_from"] == "parent"


# --- update_tokens ----------------------------------------------------------


def test_update_tokens_accumulates_across_calls(fake_doc):
    sessions.record_turn(fake_doc, "s1", "hi")

    sessions.update_tokens(fake_doc, "s1", {"input_tokens": 10, "output_tokens": 5})
    sessions.update_tokens(fake_doc, "s1", {"input_tokens": 3, "output_tokens": 7})

    tokens = sessions.get_tokens(fake_doc, "s1")
    assert tokens["input_total"] == 13
    assert tokens["output_total"] == 12
    assert tokens["last_seen"] is not None


def test_update_tokens_tolerates_none_and_empty(fake_doc):
    sessions.record_turn(fake_doc, "s1", "hi")

    sessions.update_tokens(fake_doc, "s1", None)
    sessions.update_tokens(fake_doc, "s1", {})

    tokens = sessions.get_tokens(fake_doc, "s1")
    assert tokens == {"input_total": 0, "output_total": 0, "last_seen": None}


def test_update_tokens_tolerates_missing_keys(fake_doc):
    sessions.record_turn(fake_doc, "s1", "hi")

    sessions.update_tokens(fake_doc, "s1", {"input_tokens": 4})
    sessions.update_tokens(fake_doc, "s1", {"output_tokens": 2})

    tokens = sessions.get_tokens(fake_doc, "s1")
    assert tokens["input_total"] == 4
    assert tokens["output_total"] == 2


def test_update_tokens_unknown_sid_is_noop(fake_doc):
    # Should not raise, should not create an entry.
    sessions.update_tokens(fake_doc, "ghost", {"input_tokens": 1, "output_tokens": 1})
    assert sessions.find(fake_doc, "ghost") is None


# --- get_tokens -------------------------------------------------------------


def test_get_tokens_returns_default_for_unknown_sid(fake_doc):
    assert sessions.get_tokens(fake_doc, "nope") == {
        "input_total": 0,
        "output_total": 0,
        "last_seen": None,
    }


def test_get_tokens_returns_default_for_fresh_session(fake_doc):
    sessions.record_turn(fake_doc, "s1", "hi")
    assert sessions.get_tokens(fake_doc, "s1") == {
        "input_total": 0,
        "output_total": 0,
        "last_seen": None,
    }
