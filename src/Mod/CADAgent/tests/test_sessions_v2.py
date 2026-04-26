"""Tests for sessions schema v2: migration, branch listing, archive flag."""
from __future__ import annotations

import json

from agent import sessions


def _write_index(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_v1_index_is_migrated_on_load(fake_doc):
    """A legacy v1 index gains v2 fields with defaults and bumped version."""
    path = sessions.index_path(fake_doc)
    _write_index(
        path,
        {
            "schema_version": 1,
            "sessions": [
                {
                    "id": "s1",
                    "title": "old",
                    "first_prompt": "hi",
                    "created_at": "2026-04-01T00:00:00",
                    "updated_at": "2026-04-01T00:00:00",
                    "turn_count": 2,
                }
            ],
        },
    )

    data = sessions.load(fake_doc)

    assert data["schema_version"] == 3
    entry = data["sessions"][0]
    assert entry["parent_id"] is None
    assert entry["branch_from_turn"] is None
    assert entry["archived"] is False
    # Existing fields untouched
    assert entry["title"] == "old"
    assert entry["turn_count"] == 2


def test_v1_index_with_no_schema_version_migrates(fake_doc):
    """An index missing ``schema_version`` is treated as legacy and migrated."""
    path = sessions.index_path(fake_doc)
    _write_index(
        path,
        {"sessions": [{"id": "s1", "title": "x", "turn_count": 1}]},
    )
    data = sessions.load(fake_doc)
    assert data["schema_version"] == 3
    assert data["sessions"][0]["archived"] is False
    assert data["sessions"][0]["parent_id"] is None


def test_migration_persists_after_next_save(fake_doc):
    """The next mutating call rewrites the file at v2."""
    path = sessions.index_path(fake_doc)
    _write_index(
        path,
        {
            "schema_version": 1,
            "sessions": [
                {
                    "id": "s1",
                    "title": "old",
                    "first_prompt": "hi",
                    "created_at": "2026-04-01T00:00:00",
                    "updated_at": "2026-04-01T00:00:00",
                    "turn_count": 2,
                }
            ],
        },
    )
    # Trigger a save via rename.
    assert sessions.rename(fake_doc, "s1", "renamed") is True

    with open(path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["schema_version"] == 3
    assert on_disk["sessions"][0]["archived"] is False
    assert on_disk["sessions"][0]["parent_id"] is None
    assert on_disk["sessions"][0]["title"] == "renamed"


def test_list_branches_of_returns_children(fake_doc):
    """Sessions with matching ``parent_id`` are returned by branch listing."""
    sessions.record_turn(fake_doc, "s1", "root prompt")
    sessions.record_turn(fake_doc, "s2", "child a")
    sessions.record_turn(fake_doc, "s3", "child b")
    sessions.record_turn(fake_doc, "s4", "unrelated")

    # Manually wire two of them as branches of s1.
    data = sessions.load(fake_doc)
    for entry in data["sessions"]:
        if entry["id"] in ("s2", "s3"):
            entry["parent_id"] = "s1"
            entry["branch_from_turn"] = 1
    sessions._save(fake_doc, data)

    branches = sessions.list_branches_of(fake_doc, "s1")
    branch_ids = {b["id"] for b in branches}
    assert branch_ids == {"s2", "s3"}
    assert all(b["parent_id"] == "s1" for b in branches)
    # No branches for an id with no children.
    assert sessions.list_branches_of(fake_doc, "s4") == []


def test_archive_and_unarchive_persist(fake_doc):
    sessions.record_turn(fake_doc, "s1", "hello")
    assert sessions.find(fake_doc, "s1")["archived"] is False

    assert sessions.archive(fake_doc, "s1") is True
    assert sessions.find(fake_doc, "s1")["archived"] is True

    # Persisted on disk
    with open(sessions.index_path(fake_doc), "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["sessions"][0]["archived"] is True

    assert sessions.unarchive(fake_doc, "s1") is True
    assert sessions.find(fake_doc, "s1")["archived"] is False

    # Unknown id returns False, no crash.
    assert sessions.archive(fake_doc, "nope") is False
