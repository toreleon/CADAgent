"""Tests for sessions schema v3: migration from v1 and v2."""
from __future__ import annotations

import json

from agent import sessions


def _write_index(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _v3_keys() -> set[str]:
    return {"compacted", "compacted_from", "tokens"}


def test_v2_index_is_migrated_to_v3_on_load(fake_doc):
    """A v2 index gains v3 fields (compacted/compacted_from/tokens) on load."""
    path = sessions.index_path(fake_doc)
    _write_index(
        path,
        {
            "schema_version": 2,
            "sessions": [
                {
                    "id": "s1",
                    "title": "old",
                    "first_prompt": "hi",
                    "created_at": "2026-04-01T00:00:00",
                    "updated_at": "2026-04-01T00:00:00",
                    "turn_count": 2,
                    "parent_id": None,
                    "branch_from_turn": None,
                    "archived": False,
                }
            ],
        },
    )

    data = sessions.load(fake_doc)

    assert data["schema_version"] == 3
    entry = data["sessions"][0]
    assert _v3_keys().issubset(entry.keys())
    assert entry["compacted"] is False
    assert entry["compacted_from"] is None
    assert entry["tokens"] == {
        "input_total": 0,
        "output_total": 0,
        "last_seen": None,
    }
    # v2 fields preserved
    assert entry["parent_id"] is None
    assert entry["archived"] is False
    # Existing fields untouched
    assert entry["title"] == "old"
    assert entry["turn_count"] == 2


def test_v2_migration_round_trips_to_disk(fake_doc):
    """The next mutating call rewrites the file at v3 with new fields present."""
    path = sessions.index_path(fake_doc)
    _write_index(
        path,
        {
            "schema_version": 2,
            "sessions": [
                {
                    "id": "s1",
                    "title": "old",
                    "first_prompt": "hi",
                    "created_at": "2026-04-01T00:00:00",
                    "updated_at": "2026-04-01T00:00:00",
                    "turn_count": 2,
                    "parent_id": None,
                    "branch_from_turn": None,
                    "archived": False,
                }
            ],
        },
    )
    assert sessions.rename(fake_doc, "s1", "renamed") is True

    with open(path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["schema_version"] == 3
    entry = on_disk["sessions"][0]
    assert entry["compacted"] is False
    assert entry["compacted_from"] is None
    assert entry["tokens"]["input_total"] == 0
    assert entry["tokens"]["output_total"] == 0
    assert entry["tokens"]["last_seen"] is None
    assert entry["title"] == "renamed"


def test_v1_index_chain_migrates_to_v3(fake_doc):
    """A legacy v1 index migrates straight through v2 to v3 in one load."""
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
    # v2 fields
    assert entry["parent_id"] is None
    assert entry["branch_from_turn"] is None
    assert entry["archived"] is False
    # v3 fields
    assert entry["compacted"] is False
    assert entry["compacted_from"] is None
    assert entry["tokens"] == {
        "input_total": 0,
        "output_total": 0,
        "last_seen": None,
    }
