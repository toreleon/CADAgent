# SPDX-License-Identifier: LGPL-2.1-or-later
"""Per-session workspace checkpoint store.

For each ``(doc, session)`` we keep a directory of ``.FCStd`` snapshots,
one per turn, alongside the user's document on disk:

    <doc_dir>/<doc_stem>.cadagent.checkpoints.d/
        <sid>/
            turn-0.fcstd
            turn-1.fcstd
            ...

The store is intentionally filesystem-only — no FreeCAD imports — so it can
be exercised in unit tests with plain files. Real I/O errors propagate;
"normal" not-found cases (missing checkpoint, missing session dir) return
``False`` / empty results.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

# Allow only safe-looking session ids on disk: alnum / dash / underscore.
# The SDK uses UUIDs, so this is permissive enough; anything else is
# rejected to avoid path traversal via crafted ``sid`` values.
_SID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_TURN_RE = re.compile(r"^turn-(\d+)\.fcstd$")


def _checkpoints_root(doc_path: str | Path) -> Path:
    """Return ``<doc_dir>/<doc_stem>.cadagent.checkpoints.d`` for ``doc_path``."""
    p = Path(doc_path)
    return p.with_name(f"{p.stem}.cadagent.checkpoints.d")


def _session_dir(sid: str, doc_path: str | Path) -> Path:
    if not sid or not _SID_RE.match(sid):
        raise ValueError(f"invalid session id: {sid!r}")
    return _checkpoints_root(doc_path) / sid


def _turn_file(sid: str, turn_index: int, doc_path: str | Path) -> Path:
    if not isinstance(turn_index, int) or turn_index < 0:
        raise ValueError(f"invalid turn index: {turn_index!r}")
    return _session_dir(sid, doc_path) / f"turn-{turn_index}.fcstd"


def save(sid: str, turn_index: int, doc_path: str | Path) -> Path:
    """Copy ``doc_path`` to its checkpoint slot. Returns the checkpoint path.

    Raises ``FileNotFoundError`` if ``doc_path`` does not exist (this is a
    real error: callers asked us to checkpoint a doc they think is on disk).
    """
    src = Path(doc_path)
    if not src.exists():
        raise FileNotFoundError(f"document not found: {src}")
    dest = _turn_file(sid, turn_index, doc_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def restore(sid: str, turn_index: int, doc_path: str | Path) -> bool:
    """Copy the checkpoint back over ``doc_path``. Returns True on success.

    Returns False if no checkpoint exists for ``(sid, turn_index)``.
    """
    src = _turn_file(sid, turn_index, doc_path)
    if not src.exists():
        return False
    dest = Path(doc_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def list(sid: str, doc_path: str | Path) -> list[int]:  # noqa: A001
    """Return sorted turn indices with checkpoints for ``sid``. Empty if none."""
    try:
        sdir = _session_dir(sid, doc_path)
    except ValueError:
        return []
    if not sdir.is_dir():
        return []
    out: list[int] = []
    for entry in sdir.iterdir():
        m = _TURN_RE.match(entry.name)
        if m and entry.is_file():
            out.append(int(m.group(1)))
    out.sort()
    return out


def prune(sid: str, doc_path: str | Path, keep_last: int = 20) -> list[int]:
    """Delete oldest checkpoints beyond ``keep_last``. Returns deleted indices."""
    if keep_last < 0:
        raise ValueError("keep_last must be >= 0")
    indices = list(sid, doc_path)
    if len(indices) <= keep_last:
        return []
    to_delete = indices[: len(indices) - keep_last]
    sdir = _session_dir(sid, doc_path)
    deleted: list[int] = []
    for idx in to_delete:
        path = sdir / f"turn-{idx}.fcstd"
        try:
            path.unlink()
            deleted.append(idx)
        except FileNotFoundError:
            # Race / already gone — treat as success.
            deleted.append(idx)
    return deleted


def delete_session(sid: str, doc_path: str | Path) -> bool:
    """Remove the entire ``<sid>/`` directory. Returns True if it existed."""
    try:
        sdir = _session_dir(sid, doc_path)
    except ValueError:
        return False
    if not sdir.exists():
        return False
    shutil.rmtree(sdir)
    return True
