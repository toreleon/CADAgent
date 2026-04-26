# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unit tests for ``compact_session`` orchestration and the summary stub.

``rewind.truncate_session`` and ``sessions.mark_compacted`` are stubbed via
monkeypatch — those signatures are introduced by sister Wave-1 units (B and C),
so this test must not depend on either side being merged first.
"""

from __future__ import annotations

import pytest

from agent import compaction


# --- summarize_transcript stub --------------------------------------------


def test_summarize_transcript_wrapper_format():
    rows = [
        {"kind": "user", "text": "make a cube"},
        {"kind": "assistant", "text": "creating a 10mm cube"},
    ]
    out = compaction.summarize_transcript(rows, model="gpt-5-mini", sdk_options=None)
    assert out.startswith("<compaction-summary>\n")
    assert out.endswith("\n</compaction-summary>")
    assert "[user] make a cube" in out
    assert "[assistant] creating a 10mm cube" in out


def test_summarize_transcript_handles_empty_rows():
    out = compaction.summarize_transcript([], model="x", sdk_options=None)
    assert out == "<compaction-summary>\n\n</compaction-summary>"


def test_summarize_transcript_skips_non_dict_and_empty():
    rows = [
        "junk",
        {"kind": "user", "text": ""},
        {"kind": "tool", "text": "ls"},
        None,
    ]
    out = compaction.summarize_transcript(rows, model="x", sdk_options=None)
    assert "[tool] ls" in out
    # Empty user row contributes nothing.
    assert "[user]" not in out


def test_summarize_transcript_truncates_long_body():
    rows = [{"kind": "user", "text": "x" * 10_000}]
    out = compaction.summarize_transcript(rows, model="x", sdk_options=None)
    # body capped to 4000 chars; wrapper adds open/close tags + newlines.
    assert len(out) < 4_200
    assert out.startswith("<compaction-summary>\n")
    assert out.endswith("\n</compaction-summary>")


def test_summarize_transcript_falls_back_to_content_field():
    rows = [{"kind": "assistant", "content": "hello world"}]
    out = compaction.summarize_transcript(rows, model="x", sdk_options=None)
    assert "[assistant] hello world" in out


# --- compact_session orchestration ----------------------------------------


def test_compact_session_fork_invokes_truncate_and_mark(monkeypatch):
    calls: dict = {}

    def fake_truncate(doc, sid, *, keep_through_row_index, fork, seed_summary):
        calls["truncate"] = {
            "doc": doc,
            "sid": sid,
            "keep_through_row_index": keep_through_row_index,
            "fork": fork,
            "seed_summary": seed_summary,
        }
        return "new-sid-123"

    def fake_mark(doc, sid, *, parent_sid):
        calls["mark"] = {"doc": doc, "sid": sid, "parent_sid": parent_sid}

    from agent import rewind, sessions

    monkeypatch.setattr(rewind, "truncate_session", fake_truncate, raising=False)
    monkeypatch.setattr(sessions, "mark_compacted", fake_mark, raising=False)

    sentinel_doc = object()
    summary = "<compaction-summary>\nfoo\n</compaction-summary>"
    result = compaction.compact_session(
        doc=sentinel_doc,
        sid="orig-sid",
        rows=[{"kind": "user", "text": "foo"}],
        summary=summary,
        fork=True,
    )

    assert result == "new-sid-123"
    assert calls["truncate"]["doc"] is sentinel_doc
    assert calls["truncate"]["sid"] == "orig-sid"
    assert calls["truncate"]["keep_through_row_index"] == -1
    assert calls["truncate"]["fork"] is True
    assert calls["truncate"]["seed_summary"] == summary
    assert calls["mark"]["sid"] == "new-sid-123"
    assert calls["mark"]["parent_sid"] == "orig-sid"


def test_compact_session_no_fork_skips_mark(monkeypatch):
    calls: dict = {"mark_called": False}

    def fake_truncate(doc, sid, *, keep_through_row_index, fork, seed_summary):
        return sid  # in-place rewrite returns same sid

    def fake_mark(doc, sid, *, parent_sid):
        calls["mark_called"] = True

    from agent import rewind, sessions

    monkeypatch.setattr(rewind, "truncate_session", fake_truncate, raising=False)
    monkeypatch.setattr(sessions, "mark_compacted", fake_mark, raising=False)

    result = compaction.compact_session(
        doc=object(),
        sid="orig-sid",
        rows=[],
        summary="<compaction-summary>\n\n</compaction-summary>",
        fork=False,
    )

    assert result == "orig-sid"
    assert calls["mark_called"] is False
