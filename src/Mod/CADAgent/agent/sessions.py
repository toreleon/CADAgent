# SPDX-License-Identifier: LGPL-2.1-or-later
"""Per-document chat session index.

The claude_agent_sdk persists full transcripts itself (under
``~/.claude/projects/<cwd-hash>/``) and exposes them via ``list_sessions()``
and ``get_session_messages()``. We only need to remember *which* SDK session
IDs belong to which FreeCAD document, plus lightweight display metadata.

Schema::

    {
        "schema_version": 1,
        "sessions": [
            {
                "id": "<uuid>",
                "title": "...",
                "first_prompt": "...",
                "created_at": "2026-04-21T19:50:10",
                "updated_at": "2026-04-21T19:55:02",
                "turn_count": 3
            },
            ...
        ]
    }
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile

import FreeCAD as App


SCHEMA_VERSION = 1
MAX_TITLE_LEN = 80


def _now_iso() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _default() -> dict:
    return {"schema_version": SCHEMA_VERSION, "sessions": []}


def index_path(doc) -> str:
    """Return the on-disk sessions index path for ``doc``.

    Mirrors ``memory.sidecar_path``: saved docs get a sidecar next to the
    ``.FCStd``; unsaved docs use the FreeCAD user data dir keyed by Name.
    """
    file_name = getattr(doc, "FileName", "") or ""
    if file_name:
        base, _ext = os.path.splitext(file_name)
        return base + ".cadagent.sessions.json"
    unsaved_dir = os.path.join(App.getUserAppDataDir(), "CADAgent", "unsaved")
    os.makedirs(unsaved_dir, exist_ok=True)
    return os.path.join(unsaved_dir, f"{doc.Name}.cadagent.sessions.json")


def _transcript_dir(doc) -> str:
    """Directory holding per-session row transcripts beside the index."""
    idx = index_path(doc)
    # strip trailing ".json" → "<base>.cadagent.sessions"; append ".d"
    d = (idx[:-5] if idx.endswith(".json") else idx) + ".d"
    os.makedirs(d, exist_ok=True)
    return d


def transcript_path(doc, session_id: str) -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return os.path.join(_transcript_dir(doc), f"{safe}.json")


def save_rows(doc, session_id: str, rows: list) -> str:
    """Atomically write the full ``_rows`` list for a session."""
    path = transcript_path(doc, session_id)
    payload = {"schema_version": SCHEMA_VERSION, "rows": list(rows or [])}
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".cadagent-transcript-", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return path


def load_rows(doc, session_id: str) -> list:
    path = transcript_path(doc, session_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("rows") if isinstance(data, dict) else None
    return list(rows) if isinstance(rows, list) else []


def load(doc) -> dict:
    path = index_path(doc)
    if not os.path.exists(path):
        return _default()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default()
        merged = _default()
        merged.update(data)
        if not isinstance(merged.get("sessions"), list):
            merged["sessions"] = []
        return merged
    except (OSError, json.JSONDecodeError):
        return _default()


def _save(doc, data: dict) -> str:
    path = index_path(doc)
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".cadagent-sessions-", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return path


def _derive_title(prompt: str) -> str:
    text = (prompt or "").strip().splitlines()[0] if prompt else ""
    text = text.strip()
    if len(text) > MAX_TITLE_LEN:
        text = text[: MAX_TITLE_LEN - 1].rstrip() + "\u2026"
    return text or "Untitled chat"


def list_sessions(doc) -> list[dict]:
    """Return session entries for ``doc``, newest first."""
    data = load(doc)
    sessions = list(data.get("sessions") or [])
    sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return sessions


def find(doc, session_id: str) -> dict | None:
    for entry in load(doc).get("sessions") or []:
        if entry.get("id") == session_id:
            return entry
    return None


def record_turn(doc, session_id: str, first_prompt: str | None) -> dict:
    """Upsert ``session_id`` into ``doc``'s index and bump turn count.

    Returns the updated entry.
    """
    data = load(doc)
    sessions = data.get("sessions") or []
    now = _now_iso()
    for entry in sessions:
        if entry.get("id") == session_id:
            entry["updated_at"] = now
            entry["turn_count"] = int(entry.get("turn_count") or 0) + 1
            if not entry.get("first_prompt") and first_prompt:
                entry["first_prompt"] = first_prompt
                entry["title"] = _derive_title(first_prompt)
            data["sessions"] = sessions
            _save(doc, data)
            return entry
    entry = {
        "id": session_id,
        "title": _derive_title(first_prompt or ""),
        "first_prompt": (first_prompt or "").strip(),
        "created_at": now,
        "updated_at": now,
        "turn_count": 1,
    }
    sessions.append(entry)
    data["sessions"] = sessions
    _save(doc, data)
    return entry


def rename(doc, session_id: str, title: str) -> bool:
    data = load(doc)
    for entry in data.get("sessions") or []:
        if entry.get("id") == session_id:
            entry["title"] = title.strip() or entry.get("title") or "Untitled chat"
            _save(doc, data)
            return True
    return False


def delete(doc, session_id: str) -> bool:
    data = load(doc)
    sessions = data.get("sessions") or []
    new_sessions = [s for s in sessions if s.get("id") != session_id]
    removed = len(new_sessions) != len(sessions)
    if removed:
        data["sessions"] = new_sessions
        _save(doc, data)
    try:
        tpath = transcript_path(doc, session_id)
        if os.path.exists(tpath):
            os.unlink(tpath)
    except OSError:
        pass
    return removed
