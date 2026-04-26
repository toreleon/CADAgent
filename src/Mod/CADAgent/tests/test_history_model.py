"""Tests for the history-popup tree assembly used by the QML bridge."""
from __future__ import annotations

from agent.sessions import assemble_history_tree


def test_empty_input_returns_empty_list():
    assert assemble_history_tree([]) == []


def test_root_only_entries_have_empty_children():
    entries = [
        {"id": "a", "parent_id": None, "title": "A"},
        {"id": "b", "parent_id": None, "title": "B"},
    ]
    out = assemble_history_tree(entries)
    assert [e["id"] for e in out] == ["a", "b"]
    assert all(e["children"] == [] for e in out)


def test_branches_nest_under_their_parent():
    entries = [
        {"id": "root", "parent_id": None, "title": "R"},
        {"id": "fork1", "parent_id": "root", "title": "F1", "branch_from_turn": 2},
        {"id": "fork2", "parent_id": "root", "title": "F2", "branch_from_turn": 4},
    ]
    out = assemble_history_tree(entries)
    assert len(out) == 1
    assert out[0]["id"] == "root"
    assert [c["id"] for c in out[0]["children"]] == ["fork1", "fork2"]


def test_grandchildren_flatten_under_root():
    entries = [
        {"id": "root", "parent_id": None},
        {"id": "child", "parent_id": "root"},
        {"id": "grand", "parent_id": "child"},
    ]
    out = assemble_history_tree(entries)
    assert len(out) == 1
    assert out[0]["id"] == "root"
    child_ids = [c["id"] for c in out[0]["children"]]
    assert set(child_ids) == {"child", "grand"}


def test_orphan_branch_becomes_top_level_row():
    entries = [
        {"id": "fork", "parent_id": "missing"},
    ]
    out = assemble_history_tree(entries)
    assert [e["id"] for e in out] == ["fork"]
    assert out[0]["children"] == []


def test_input_dicts_are_not_mutated():
    entries = [
        {"id": "root", "parent_id": None, "title": "R"},
        {"id": "fork", "parent_id": "root"},
    ]
    assemble_history_tree(entries)
    assert "children" not in entries[0]
    assert "children" not in entries[1]
