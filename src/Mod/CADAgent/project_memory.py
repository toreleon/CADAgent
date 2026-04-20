# SPDX-License-Identifier: LGPL-2.1-or-later
"""Per-document project memory stored as a JSON sidecar next to the .FCStd.

Captures design intent, named parameters, and decisions that outlive a single
agent turn. The sidecar is inlined into the per-turn context snapshot so the
agent sees it every message.

Schema::

    {
        "schema_version": 1,
        "design_intent": "",
        "parameters": {"Thickness": {"value": 10.0, "unit": "mm", "note": ""}},
        "decisions": [{"ts": "2026-04-20T10:00:00", "text": "..."}],
        "naming": {}
    }
"""

import datetime
import json
import os
import tempfile

import FreeCAD as App


SCHEMA_VERSION = 1


def _default() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "design_intent": "",
        "parameters": {},
        "decisions": [],
        "naming": {},
    }


def sidecar_path(doc) -> str:
    """Return the on-disk sidecar path for `doc`.

    Saved docs: alongside the .FCStd. Unsaved docs: under the FreeCAD user
    data dir, keyed by doc.Name so re-opening the workbench picks it back up.
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
        # Merge with defaults so callers can rely on keys existing.
        merged = _default()
        merged.update(data)
        merged.setdefault("parameters", {})
        merged.setdefault("decisions", [])
        merged.setdefault("naming", {})
        return merged
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


def set_parameter(doc, name: str, value: float, unit: str = "mm", note: str = "") -> dict:
    data = load(doc)
    params = data.setdefault("parameters", {})
    params[name] = {"value": float(value), "unit": unit or "mm", "note": note or ""}
    save(doc, data)
    return params[name]


def get_parameters(doc) -> dict:
    return load(doc).get("parameters", {})


def append_decision(doc, text: str) -> dict:
    data = load(doc)
    entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "text": text}
    data.setdefault("decisions", []).append(entry)
    save(doc, data)
    return entry


def write_note(doc, section: str, key: str, value) -> dict:
    data = load(doc)
    if section not in data or not isinstance(data[section], dict):
        data[section] = {}
    data[section][key] = value
    save(doc, data)
    return {section: {key: value}}
