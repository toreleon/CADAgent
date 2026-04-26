# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unit tests for ``SessionTokens`` accumulation."""

from __future__ import annotations

from dataclasses import dataclass

from agent.compaction import SessionTokens


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


def test_accumulate_object_form():
    tokens = SessionTokens()
    tokens.accumulate(_Usage(input_tokens=100, output_tokens=40, cache_read_input_tokens=10))
    assert tokens.input_total == 100
    assert tokens.output_total == 40
    assert tokens.cache_read_total == 10
    assert tokens.last_turn_total == 140
    assert tokens.effective_context_used() == 140


def test_accumulate_dict_form():
    tokens = SessionTokens()
    tokens.accumulate(
        {"input_tokens": 200, "output_tokens": 50, "cache_read_input_tokens": 25}
    )
    assert tokens.input_total == 200
    assert tokens.output_total == 50
    assert tokens.cache_read_total == 25
    assert tokens.last_turn_total == 250


def test_accumulate_missing_keys_default_to_zero():
    tokens = SessionTokens()
    tokens.accumulate({"input_tokens": 10})  # output_tokens, cache_read missing
    assert tokens.input_total == 10
    assert tokens.output_total == 0
    assert tokens.cache_read_total == 0
    assert tokens.last_turn_total == 10


def test_accumulate_none_does_nothing():
    tokens = SessionTokens()
    tokens.accumulate(None)
    assert tokens.input_total == 0
    assert tokens.output_total == 0
    assert tokens.last_turn_total == 0


def test_accumulate_object_missing_attrs_default_zero():
    class Sparse:
        input_tokens = 7

    tokens = SessionTokens()
    tokens.accumulate(Sparse())
    assert tokens.input_total == 7
    assert tokens.output_total == 0
    assert tokens.cache_read_total == 0
    assert tokens.last_turn_total == 7


def test_multiple_turns_sum():
    tokens = SessionTokens()
    tokens.accumulate(_Usage(100, 20, 5))
    tokens.accumulate(_Usage(50, 30, 0))
    tokens.accumulate({"input_tokens": 25, "output_tokens": 10})
    assert tokens.input_total == 175
    assert tokens.output_total == 60
    assert tokens.cache_read_total == 5
    assert tokens.last_turn_total == 35  # last turn only
    assert tokens.effective_context_used() == 235


def test_effective_context_excludes_cache_reads():
    tokens = SessionTokens()
    tokens.accumulate(_Usage(input_tokens=100, output_tokens=0, cache_read_input_tokens=5000))
    # cache reads should NOT count against the window
    assert tokens.effective_context_used() == 100


def test_reset_zeroes_everything():
    tokens = SessionTokens()
    tokens.accumulate(_Usage(100, 50, 25))
    tokens.reset()
    assert tokens.input_total == 0
    assert tokens.output_total == 0
    assert tokens.cache_read_total == 0
    assert tokens.last_turn_total == 0


def test_reset_with_seed_size_seeds_input_total():
    tokens = SessionTokens()
    tokens.accumulate(_Usage(100, 50, 25))
    tokens.reset(seed_size=750)
    assert tokens.input_total == 750
    assert tokens.output_total == 0
    assert tokens.cache_read_total == 0
    assert tokens.last_turn_total == 0
    assert tokens.effective_context_used() == 750


def test_non_int_usage_values_coerced_to_zero():
    tokens = SessionTokens()
    tokens.accumulate({"input_tokens": "bad", "output_tokens": None})
    assert tokens.input_total == 0
    assert tokens.output_total == 0
