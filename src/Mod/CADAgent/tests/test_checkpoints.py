"""Unit tests for ``agent.checkpoints``.

The checkpoint store is filesystem-only, so these tests use ``tmp_path``
and plain text files standing in for ``.FCStd`` blobs.
"""

from __future__ import annotations

import pytest

from agent import checkpoints


SID = "abc123-session"


def _write(path, content: bytes = b"v1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_save_and_restore_round_trip(tmp_path):
    doc = tmp_path / "model.FCStd"
    _write(doc, b"original")

    cp = checkpoints.save(SID, 0, doc)
    assert cp.exists()
    assert cp.read_bytes() == b"original"

    # Mutate the doc, then restore: contents come back.
    doc.write_bytes(b"mutated")
    assert checkpoints.restore(SID, 0, doc) is True
    assert doc.read_bytes() == b"original"


def test_restore_missing_returns_false(tmp_path):
    doc = tmp_path / "model.FCStd"
    _write(doc)
    assert checkpoints.restore(SID, 99, doc) is False


def test_save_missing_doc_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        checkpoints.save(SID, 0, tmp_path / "does-not-exist.FCStd")


def test_list_returns_sorted_turn_indices(tmp_path):
    doc = tmp_path / "model.FCStd"
    _write(doc)
    for i in (2, 0, 5, 1):
        checkpoints.save(SID, i, doc)
    assert checkpoints.list(SID, doc) == [0, 1, 2, 5]


def test_list_unknown_session_is_empty(tmp_path):
    doc = tmp_path / "model.FCStd"
    _write(doc)
    assert checkpoints.list("never-saved", doc) == []


def test_prune_keeps_last_n(tmp_path):
    doc = tmp_path / "model.FCStd"
    _write(doc)
    for i in range(5):
        checkpoints.save(SID, i, doc)

    deleted = checkpoints.prune(SID, doc, keep_last=2)
    assert deleted == [0, 1, 2]
    assert checkpoints.list(SID, doc) == [3, 4]


def test_prune_noop_when_under_limit(tmp_path):
    doc = tmp_path / "model.FCStd"
    _write(doc)
    checkpoints.save(SID, 0, doc)
    assert checkpoints.prune(SID, doc, keep_last=10) == []
    assert checkpoints.list(SID, doc) == [0]


def test_delete_session_removes_dir(tmp_path):
    doc = tmp_path / "model.FCStd"
    _write(doc)
    checkpoints.save(SID, 0, doc)
    checkpoints.save(SID, 1, doc)

    assert checkpoints.delete_session(SID, doc) is True
    assert checkpoints.list(SID, doc) == []
    # Second call is a no-op.
    assert checkpoints.delete_session(SID, doc) is False


def test_invalid_sid_rejected(tmp_path):
    doc = tmp_path / "model.FCStd"
    _write(doc)
    with pytest.raises(ValueError):
        checkpoints.save("../escape", 0, doc)
    # Read-only helpers should fail closed rather than raise.
    assert checkpoints.list("../escape", doc) == []
    assert checkpoints.delete_session("../escape", doc) is False


def test_sessions_isolated_per_doc(tmp_path):
    doc_a = tmp_path / "a" / "alpha.FCStd"
    doc_b = tmp_path / "b" / "beta.FCStd"
    _write(doc_a, b"A")
    _write(doc_b, b"B")

    checkpoints.save(SID, 0, doc_a)
    assert checkpoints.list(SID, doc_a) == [0]
    assert checkpoints.list(SID, doc_b) == []
