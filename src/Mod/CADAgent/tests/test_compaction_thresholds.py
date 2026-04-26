# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unit tests for context-window sizing, threshold check, and error detection."""

from __future__ import annotations

import pytest

from agent import compaction


# --- context_limit_for ---------------------------------------------------


def test_exact_match_claude_sonnet():
    assert compaction.context_limit_for("claude-3-5-sonnet") == 200_000


def test_exact_match_gpt5_mini():
    assert compaction.context_limit_for("gpt-5-mini") == 400_000


def test_exact_match_gpt4o():
    assert compaction.context_limit_for("gpt-4o") == 128_000


def test_prefix_match_dated_snapshot_picks_longest_key():
    # Both "claude-3-5-sonnet" and (hypothetically shorter) prefixes might
    # match; longest wins.
    assert (
        compaction.context_limit_for("claude-3-5-sonnet-20241022") == 200_000
    )


def test_prefix_match_gpt5_variant():
    assert compaction.context_limit_for("gpt-5-mini-2025-08-07") == 400_000


def test_unknown_model_falls_back_to_default():
    assert (
        compaction.context_limit_for("some-future-model")
        == compaction.DEFAULT_CONTEXT_LIMIT
    )


def test_empty_model_returns_default():
    assert (
        compaction.context_limit_for("") == compaction.DEFAULT_CONTEXT_LIMIT
    )


def test_settings_override_wins():
    settings = {"compaction": {"context_limit": 1234}}
    assert compaction.context_limit_for("claude-3-5-sonnet", settings) == 1234


def test_settings_override_invalid_falls_through():
    settings = {"compaction": {"context_limit": "not-an-int"}}
    assert (
        compaction.context_limit_for("claude-3-5-sonnet", settings) == 200_000
    )


def test_settings_override_zero_falls_through():
    settings = {"compaction": {"context_limit": 0}}
    assert (
        compaction.context_limit_for("claude-3-5-sonnet", settings) == 200_000
    )


# --- should_auto_compact -------------------------------------------------


def test_should_auto_compact_below_threshold():
    assert not compaction.should_auto_compact(used=100_000, limit=200_000)


def test_should_auto_compact_at_default_threshold():
    # 95% of 200k = 190k; equal triggers.
    assert compaction.should_auto_compact(used=190_000, limit=200_000)


def test_should_auto_compact_above_threshold():
    assert compaction.should_auto_compact(used=199_000, limit=200_000)


def test_should_auto_compact_custom_pct():
    settings = {"compaction": {"trigger_pct": 0.5}}
    assert compaction.should_auto_compact(
        used=100_000, limit=200_000, settings=settings
    )
    assert not compaction.should_auto_compact(
        used=99_999, limit=200_000, settings=settings
    )


def test_should_auto_compact_invalid_pct_uses_default():
    settings = {"compaction": {"trigger_pct": 5.0}}  # out of range
    assert not compaction.should_auto_compact(
        used=100_000, limit=200_000, settings=settings
    )


def test_should_auto_compact_zero_limit_returns_false():
    assert not compaction.should_auto_compact(used=10, limit=0)


# --- is_context_overflow_error ------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 400 - context_length_exceeded: This model's context window is 200000 tokens.",
        "prompt is too long: 250000 tokens > 200000 maximum",
        "Request exceeds the maximum context length supported by the model.",
        "Total input length is 305000 which exceeds the limit",
        "too many tokens in request body",
        "Error: context length is 256000 but request had 270000",
    ],
)
def test_overflow_message_substrings(message):
    assert compaction.is_context_overflow_error(RuntimeError(message))


def test_overflow_status_code_400_with_token():
    class FakeAPIErr(Exception):
        def __init__(self, msg, status_code):
            super().__init__(msg)
            self.status_code = status_code

    exc = FakeAPIErr("Bad request: token budget exceeded", 400)
    assert compaction.is_context_overflow_error(exc)


def test_overflow_status_code_413_with_token():
    class FakeAPIErr(Exception):
        def __init__(self, msg, status_code):
            super().__init__(msg)
            self.status_code = status_code

    exc = FakeAPIErr("Payload too large; token count high", 413)
    assert compaction.is_context_overflow_error(exc)


def test_status_code_400_without_token_keyword_is_not_overflow():
    class FakeAPIErr(Exception):
        def __init__(self, msg, status_code):
            super().__init__(msg)
            self.status_code = status_code

    exc = FakeAPIErr("Invalid request: missing field", 400)
    assert not compaction.is_context_overflow_error(exc)


def test_unrelated_error_is_not_overflow():
    assert not compaction.is_context_overflow_error(
        RuntimeError("connection reset by peer")
    )
