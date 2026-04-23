# SPDX-License-Identifier: LGPL-2.1-or-later
"""Per-document project memory stored as a JSON sidecar next to the .FCStd.

The sidecar outlives a single agent turn and is inlined into each turn's
context snapshot so the agent always sees design intent, typed decision
records, and the current milestone plan.

Schema v2 (backwards-compatible with v1):

    {
        "schema_version": 2,
        "design_intent": "",
        "parameters": {"Thickness": {"value": 10.0, "unit": "mm", "note": ""}},
        "decisions": [
            {
                "id": "d-001",
                "ts": "2026-04-23T10:00:00",
                "goal": "...",
                "constraints": [...],
                "alternatives": [...],
                "choice": "...",
                "rationale": "...",
                "depends_on": ["d-000"],
                "milestone": "m-001"   # optional
            }
        ],
        "plan": {
            "id": "p-001",
            "created_ts": "...",
            "status": "active",          # active | done | abandoned
            "milestones": [
                {
                    "id": "m-001",
                    "title": "...",
                    "acceptance_criteria": [...],
                    "tool_hints": [...],
                    "status": "pending", # pending | active | done | failed
                    "session_id": None,
                    "started_ts": None,
                    "completed_ts": None,
                    "notes": ""
                }
            ]
        },
        "naming": {}
    }

v1 -> v2 upgrade is in-memory only on load: old ``{"ts", "text"}`` decisions are
rehydrated into the typed shape with ``rationale = text`` and a synthetic id.
The sidecar on disk stays v1 until the next writer mutates it.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from typing import Iterable

import FreeCAD as App


SCHEMA_VERSION = 2

MILESTONE_STATUSES = ("pending", "active", "done", "failed")
PLAN_STATUSES = ("active", "done", "abandoned")


# ---------------------------------------------------------------------------
# defaults & upgrade path
# ---------------------------------------------------------------------------


def _default() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "design_intent": "",
        "parameters": {},
        "decisions": [],
        "plan": None,
        "naming": {},
    }


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _upgrade_decision(entry: dict, index: int) -> dict:
    """Coerce a v1 or partial v2 decision into a full v2 record.

    Idempotent: a fully-typed v2 entry round-trips unchanged.
    """
    if not isinstance(entry, dict):
        return {
            "id": f"d-legacy-{index:03d}",
            "ts": _now(),
            "goal": "",
            "constraints": [],
            "alternatives": [],
            "choice": "",
            "rationale": str(entry),
            "depends_on": [],
        }
    out = {
        "id": entry.get("id") or f"d-legacy-{index:03d}",
        "ts": entry.get("ts") or _now(),
        "goal": entry.get("goal", ""),
        "constraints": list(entry.get("constraints") or []),
        "alternatives": list(entry.get("alternatives") or []),
        "choice": entry.get("choice", ""),
        "rationale": entry.get("rationale", "") or entry.get("text", ""),
        "depends_on": list(entry.get("depends_on") or []),
    }
    if "milestone" in entry:
        out["milestone"] = entry["milestone"]
    # Preserve the original free-text field so context.py's existing renderer
    # (which reads d["text"]) keeps working during the migration.
    if entry.get("text") and not out.get("text"):
        out["text"] = entry["text"]
    elif not entry.get("text") and out.get("rationale"):
        out["text"] = out["rationale"]
    return out


def _upgrade(data: dict) -> dict:
    """Coerce an on-disk dict into the in-memory v2 shape. Does not write."""
    merged = _default()
    merged.update(data or {})
    merged["parameters"] = dict(merged.get("parameters") or {})
    merged["naming"] = dict(merged.get("naming") or {})
    decisions = list(merged.get("decisions") or [])
    merged["decisions"] = [_upgrade_decision(d, i) for i, d in enumerate(decisions)]
    plan = merged.get("plan")
    if plan is not None and not isinstance(plan, dict):
        plan = None
    if plan is not None:
        plan.setdefault("milestones", [])
        plan["milestones"] = [_upgrade_milestone(m, i) for i, m in enumerate(plan["milestones"] or [])]
        plan.setdefault("status", "active")
        plan.setdefault("created_ts", _now())
        plan.setdefault("id", "p-001")
    merged["plan"] = plan
    merged["schema_version"] = SCHEMA_VERSION  # in-memory shape is always current
    return merged


def _upgrade_milestone(entry: dict, index: int) -> dict:
    if not isinstance(entry, dict):
        entry = {"title": str(entry)}
    status = entry.get("status") or "pending"
    if status not in MILESTONE_STATUSES:
        status = "pending"
    return {
        "id": entry.get("id") or f"m-{index + 1:03d}",
        "title": entry.get("title", ""),
        "acceptance_criteria": list(entry.get("acceptance_criteria") or []),
        "tool_hints": list(entry.get("tool_hints") or []),
        "status": status,
        "session_id": entry.get("session_id"),
        "started_ts": entry.get("started_ts"),
        "completed_ts": entry.get("completed_ts"),
        "notes": entry.get("notes", ""),
    }


# ---------------------------------------------------------------------------
# disk I/O
# ---------------------------------------------------------------------------


def sidecar_path(doc) -> str:
    """Return the on-disk sidecar path for ``doc``.

    Saved docs: alongside the .FCStd. Unsaved docs: under the FreeCAD user
    data dir, keyed by ``doc.Name`` so re-opening the workbench picks it back up.
    """
    file_name = getattr(doc, "FileName", "") or ""
    if file_name:
        base, _ext = os.path.splitext(file_name)
        return base + ".cadagent.json"
    unsaved_dir = os.path.join(App.getUserAppDataDir(), "CADAgent", "unsaved")
    os.makedirs(unsaved_dir, exist_ok=True)
    return os.path.join(unsaved_dir, f"{doc.Name}.cadagent.json")


def load(doc) -> dict:
    path = sidecar_path(doc)
    if not os.path.exists(path):
        return _default()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default()
        return _upgrade(data)
    except (OSError, json.JSONDecodeError):
        return _default()


def save(doc, data: dict) -> str:
    path = sidecar_path(doc)
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".cadagent.", suffix=".json", dir=os.path.dirname(path) or "."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def update(doc, patch: dict) -> dict:
    data = load(doc)
    for k, v in patch.items():
        data[k] = v
    save(doc, data)
    return data


# ---------------------------------------------------------------------------
# parameters (unchanged from v1)
# ---------------------------------------------------------------------------


def set_parameter(doc, name: str, value: float, unit: str = "mm", note: str = "") -> dict:
    data = load(doc)
    params = data.setdefault("parameters", {})
    params[name] = {"value": float(value), "unit": unit or "mm", "note": note or ""}
    save(doc, data)
    return params[name]


def get_parameters(doc) -> dict:
    return load(doc).get("parameters", {})


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------


def _next_decision_id(data: dict) -> str:
    """Allocate a fresh ``d-NNN`` id that doesn't collide with existing ones."""
    used = {d.get("id") for d in data.get("decisions") or []}
    i = 1
    while True:
        candidate = f"d-{i:03d}"
        if candidate not in used:
            return candidate
        i += 1


def append_decision(doc, text: str) -> dict:
    """Legacy shim: append a free-text decision as a v2 record.

    Keeps v1 callers working. Prefer ``append_decision_record`` for new code
    so you get typed ``goal`` / ``constraints`` / ``rationale`` / ``depends_on``.
    """
    return append_decision_record(doc, rationale=text)


def append_decision_record(
    doc,
    *,
    goal: str = "",
    constraints: Iterable[str] | None = None,
    alternatives: Iterable[str] | None = None,
    choice: str = "",
    rationale: str = "",
    depends_on: Iterable[str] | None = None,
    milestone: str | None = None,
) -> dict:
    data = load(doc)
    entry: dict = {
        "id": _next_decision_id(data),
        "ts": _now(),
        "goal": goal,
        "constraints": list(constraints or []),
        "alternatives": list(alternatives or []),
        "choice": choice,
        "rationale": rationale,
        "depends_on": list(depends_on or []),
    }
    if milestone is not None:
        entry["milestone"] = milestone
    # Back-compat text mirror so context.py's legacy renderer still shows
    # something human-readable until Phase 2c replaces it.
    entry["text"] = rationale or choice or goal
    data.setdefault("decisions", []).append(entry)
    save(doc, data)
    return entry


def list_decisions(doc) -> list[dict]:
    return list(load(doc).get("decisions") or [])


def get_decision(doc, decision_id: str) -> dict | None:
    for d in load(doc).get("decisions") or []:
        if d.get("id") == decision_id:
            return d
    return None


def decision_closure(doc, seed_ids: Iterable[str]) -> list[dict]:
    """Return every decision reachable via ``depends_on`` edges from ``seed_ids``.

    Breadth-first, de-duplicated, ordered by how the records appear in the file
    (stable for the rendered context). Missing ids are silently dropped.
    """
    all_decisions = list_decisions(doc)
    by_id = {d.get("id"): d for d in all_decisions if d.get("id")}
    seen: set[str] = set()
    frontier: list[str] = [sid for sid in seed_ids if sid in by_id]
    while frontier:
        next_frontier: list[str] = []
        for sid in frontier:
            if sid in seen:
                continue
            seen.add(sid)
            d = by_id.get(sid)
            if not d:
                continue
            for dep in d.get("depends_on") or []:
                if dep not in seen and dep in by_id:
                    next_frontier.append(dep)
        frontier = next_frontier
    return [d for d in all_decisions if d.get("id") in seen]


# ---------------------------------------------------------------------------
# plan + milestones
# ---------------------------------------------------------------------------


def _empty_plan() -> dict:
    return {
        "id": "p-001",
        "created_ts": _now(),
        "status": "active",
        "milestones": [],
    }


def get_plan(doc) -> dict | None:
    return load(doc).get("plan")


def set_plan(doc, milestones: Iterable[dict], *, plan_id: str | None = None) -> dict:
    """Replace the plan entirely. New milestones start in ``pending`` state."""
    data = load(doc)
    plan = _empty_plan()
    if plan_id:
        plan["id"] = plan_id
    plan["milestones"] = [_upgrade_milestone(m, i) for i, m in enumerate(milestones or [])]
    data["plan"] = plan
    save(doc, data)
    return plan


def update_milestone(doc, milestone_id: str, **fields) -> dict | None:
    """Patch the named fields on one milestone. Unknown fields are ignored.

    Recognised fields: title, acceptance_criteria, tool_hints, status,
    session_id, started_ts, completed_ts, notes.
    """
    data = load(doc)
    plan = data.get("plan")
    if not plan:
        return None
    if "status" in fields and fields["status"] not in MILESTONE_STATUSES:
        raise ValueError(
            f"invalid milestone status {fields['status']!r} "
            f"(allowed: {MILESTONE_STATUSES})"
        )
    hit: dict | None = None
    for m in plan.get("milestones") or []:
        if m.get("id") == milestone_id:
            for k in ("title", "acceptance_criteria", "tool_hints", "status",
                     "session_id", "started_ts", "completed_ts", "notes"):
                if k in fields:
                    m[k] = fields[k]
            # Auto-timestamp transitions.
            if fields.get("status") == "active" and not m.get("started_ts"):
                m["started_ts"] = _now()
            if fields.get("status") in ("done", "failed") and not m.get("completed_ts"):
                m["completed_ts"] = _now()
            hit = m
            break
    if hit is None:
        return None
    # Bubble plan.status up when all milestones finish.
    all_terminal = all(
        m.get("status") in ("done", "failed") for m in plan.get("milestones") or []
    )
    if all_terminal and plan.get("milestones"):
        plan["status"] = "done"
    save(doc, data)
    return hit


def active_milestone(doc) -> dict | None:
    """Return the first ``active`` milestone, or the first ``pending`` one.

    Callers use this to drive the executor: ``pending`` milestones get picked
    up when the previous one finishes; ``active`` milestones get resumed.
    """
    plan = get_plan(doc)
    if not plan:
        return None
    milestones = plan.get("milestones") or []
    for m in milestones:
        if m.get("status") == "active":
            return m
    for m in milestones:
        if m.get("status") == "pending":
            return m
    return None


# ---------------------------------------------------------------------------
# misc writers
# ---------------------------------------------------------------------------


def write_note(doc, section: str, key: str, value) -> dict:
    data = load(doc)
    if section not in data or not isinstance(data[section], dict):
        data[section] = {}
    data[section][key] = value
    save(doc, data)
    return {section: {key: value}}
