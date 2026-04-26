# SPDX-License-Identifier: LGPL-2.1-or-later
"""Per-document chat session index.

The claude_agent_sdk persists full transcripts itself (under
``~/.claude/projects/<cwd-hash>/``) and exposes them via ``list_sessions()``
and ``get_session_messages()``. We only need to remember *which* SDK session
IDs belong to which FreeCAD document, plus lightweight display metadata.

Schema (v2)::

    {
        "schema_version": 2,
        "sessions": [
            {
                "id": "<uuid>",
                "title": "...",
                "first_prompt": "...",
                "created_at": "2026-04-21T19:50:10",
                "updated_at": "2026-04-21T19:55:02",
                "turn_count": 3,
                "parent_id": null,         # v2: source sid if branched
                "branch_from_turn": null,  # v2: turn index this branch forked at
                "archived": false          # v2: hide from default listings
            },
            ...
        ]
    }

v1 entries (lacking ``parent_id`` / ``branch_from_turn`` / ``archived``) are
auto-migrated on load with default values, and the index is re-saved on the
next mutating call.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile

import FreeCAD as App


SCHEMA_VERSION = 2
MAX_TITLE_LEN = 80

# v2 fields injected into legacy session entries on load.
_V2_DEFAULTS = {
    "parent_id": None,
    "branch_from_turn": None,
    "archived": False,
}


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


def _migrate_in_memory(data: dict) -> dict:
    """Bring a loaded index dict up to the current schema version.

    Adds v2 fields with defaults to any session entry that lacks them and
    bumps ``schema_version``. Pure in-memory; the next ``_save`` persists.
    """
    data["schema_version"] = SCHEMA_VERSION
    sessions = data.get("sessions") or []
    for entry in sessions:
        if not isinstance(entry, dict):
            continue
        for key, default in _V2_DEFAULTS.items():
            if key not in entry:
                entry[key] = default
    data["sessions"] = sessions
    return data


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
        return _migrate_in_memory(merged)
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
        **_V2_DEFAULTS,
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


def list_branches_of(doc, session_id: str) -> list[dict]:
    """Return session entries whose ``parent_id`` matches ``session_id``.

    Order: newest ``updated_at`` first. Includes archived branches.
    """
    branches = [
        entry
        for entry in load(doc).get("sessions") or []
        if entry.get("parent_id") == session_id
    ]
    branches.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return branches


def _set_archived(doc, session_id: str, value: bool) -> bool:
    data = load(doc)
    for entry in data.get("sessions") or []:
        if entry.get("id") == session_id:
            entry["archived"] = bool(value)
            _save(doc, data)
            return True
    return False


def archive(doc, session_id: str) -> bool:
    """Mark ``session_id`` as archived. Returns True if the entry existed."""
    return _set_archived(doc, session_id, True)


def unarchive(doc, session_id: str) -> bool:
    """Inverse of :func:`archive`."""
    return _set_archived(doc, session_id, False)


def assemble_history_tree(entries: list[dict]) -> list[dict]:
    """Group ``entries`` into roots with one nesting level of branches.

    Roots are entries with ``parent_id is None``. A branch whose ``parent_id``
    points at another branch (grandchild) is re-attached under its nearest
    root ancestor so callers (the QML history popup) only need to render a
    single level of nesting. Branches whose parent is missing fall back to
    being rendered as their own top-level row. Input dicts are never mutated.
    """
    if not entries:
        return []
    by_id = {
        e.get("id"): e
        for e in entries
        if isinstance(e, dict) and e.get("id")
    }

    def _root_id(sid: str) -> str | None:
        seen: set[str] = set()
        cur = sid
        while cur and cur not in seen:
            seen.add(cur)
            entry = by_id.get(cur)
            if entry is None:
                return None
            parent = entry.get("parent_id")
            if parent is None:
                return cur
            cur = parent
        return None

    out: list[dict] = []
    root_index: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("parent_id") is not None:
            continue
        cloned = dict(entry)
        cloned["children"] = []
        root_index[cloned.get("id")] = len(out)
        out.append(cloned)
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("parent_id") is None:
            continue
        root = _root_id(entry.get("id"))
        if root is None or root not in root_index:
            cloned = dict(entry)
            cloned["children"] = []
            out.append(cloned)
            continue
        out[root_index[root]]["children"].append(dict(entry))
    return out


def truncate_rows(doc, session_id: str, keep_through_index: int) -> list:
    """Truncate persisted rows for ``session_id`` to ``rows[: keep_through_index + 1]``.

    Returns the truncated row list. Negative ``keep_through_index`` clears
    the transcript. Returns ``[]`` if no rows have been persisted yet.
    """
    rows = load_rows(doc, session_id)
    if not rows:
        return []
    if keep_through_index < 0:
        truncated: list = []
    else:
        truncated = list(rows[: keep_through_index + 1])
    save_rows(doc, session_id, truncated)
    return truncated


def clone_metadata(
    doc,
    src_sid: str,
    new_sid: str,
    branch_from_turn: int,
) -> dict | None:
    """Clone ``src_sid``'s session-index entry into a new ``new_sid`` branch.

    The new entry inherits the source's ``title`` / ``first_prompt`` and
    records ``parent_id=src_sid`` + ``branch_from_turn``. Returns the new
    entry, or ``None`` if the source sid is not in the index.

    Coordinates with the upcoming v2 schema (W1-D): ``parent_id``,
    ``branch_from_turn``, and ``archived`` are written via direct dict
    assignment so the entry is well-formed whether or not v2 has shipped
    yet. Reading v2-only fields elsewhere should use ``.get()``.
    """
    data = load(doc)
    sessions = data.get("sessions") or []
    src = None
    for entry in sessions:
        if isinstance(entry, dict) and entry.get("id") == src_sid:
            src = entry
            break
    if src is None:
        return None

    now = _now_iso()
    base_title = src.get("title") or "Untitled chat"
    new_entry = {
        "id": new_sid,
        "title": f"{base_title} (fork)",
        "first_prompt": src.get("first_prompt") or "",
        "created_at": now,
        "updated_at": now,
        "turn_count": int(branch_from_turn or 0),
        "parent_id": src_sid,
        "branch_from_turn": int(branch_from_turn or 0),
        "archived": False,
    }
    # Idempotent: drop any pre-existing entry with the same id.
    sessions = [
        e for e in sessions
        if not (isinstance(e, dict) and e.get("id") == new_sid)
    ]
    sessions.append(new_entry)
    data["sessions"] = sessions
    _save(doc, data)
    return new_entry


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
