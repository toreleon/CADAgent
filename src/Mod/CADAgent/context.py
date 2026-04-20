# SPDX-License-Identifier: LGPL-2.1-or-later
"""Builds the per-turn FreeCAD context snapshot prepended to each user message.

The snapshot gives the agent session awareness (doc, workbench, selection,
feature tree, project memory) without requiring an extra round-trip for read
tools on every turn.
"""

import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

import project_memory
from gui_thread import run_sync


PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/CADAgent"
DEFAULT_MAX_CHARS = 4000


def _active_body(doc):
    if not _HAS_GUI:
        return None
    try:
        import PartDesignGui  # type: ignore
        body = PartDesignGui.getActiveBody(False)
        if body is not None and body.Document is doc:
            return body
    except Exception:
        pass
    # Fallback: first PartDesign::Body in the document.
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Body":
            return obj
    return None


def _feature_tree_lines(doc, limit: int = 60) -> list[str]:
    lines: list[str] = []
    count = 0
    for obj in doc.Objects:
        if count >= limit:
            lines.append(f"  … (+{len(doc.Objects) - limit} more)")
            break
        info = f"- {obj.Name} ({obj.TypeId})"
        # Surface a few load-bearing props compactly.
        extras = []
        for prop in ("Length", "Length2", "Radius", "Radius1", "Radius2", "Width", "Height", "Angle"):
            if prop in obj.PropertiesList:
                try:
                    extras.append(f"{prop}={getattr(obj, prop)}")
                except Exception:
                    pass
        if extras:
            info += " " + " ".join(extras[:4])
        lines.append(info)
        count += 1
    return lines


def _selection_lines() -> list[str]:
    if not _HAS_GUI:
        return []
    try:
        sel = Gui.Selection.getSelectionEx()
    except Exception:
        return []
    out: list[str] = []
    for s in sel:
        subs = list(getattr(s, "SubElementNames", ()) or ())
        obj = s.Object
        ref = obj.Name
        if not subs:
            out.append(f"- {ref} (TypeId={obj.TypeId})")
            continue
        for sub in subs:
            line = f"- {ref}.{sub}"
            # Surface face normal / surface type when trivially derivable —
            # this lets the agent choose sensible defaults for create_sketch
            # plane='Feature.FaceN' without an extra get_object turn.
            try:
                shape = obj.Shape.getElement(sub) if hasattr(obj, "Shape") else None
                if shape is not None:
                    if sub.startswith("Face"):
                        surf = shape.Surface
                        kind = surf.__class__.__name__
                        line += f" (Face, {kind}"
                        try:
                            normal = shape.normalAt(0, 0)
                            line += f", normal=[{normal.x:.2f},{normal.y:.2f},{normal.z:.2f}]"
                        except Exception:
                            pass
                        line += ")"
                    elif sub.startswith("Edge"):
                        line += f" (Edge, len={shape.Length:.2f})"
            except Exception:
                pass
            out.append(line)
    return out


def _parameters_lines(doc) -> list[str]:
    """Dump the Parameters spreadsheet rows (name, value, alias)."""
    sheet = doc.getObject("Parameters")
    if sheet is None:
        return []
    out: list[str] = []
    for row in range(1, 200):
        try:
            name = sheet.getContents(f"A{row}")
            val = sheet.getContents(f"B{row}")
            alias = sheet.getAlias(f"B{row}")
        except Exception:
            break
        if not name and not val:
            break
        line = f"- {alias or name} = {val}"
        out.append(line)
    return out


def _view_info() -> str | None:
    if not _HAS_GUI:
        return None
    try:
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            return None
        cam = None
        if hasattr(view, "getCameraType"):
            cam = view.getCameraType()
        return f"- Camera: {cam or 'unknown'}"
    except Exception:
        return None


def _in_progress_sketch_lines(doc) -> list[str]:
    """If the user is mid-sketch, surface its DOF + malformed/conflicting."""
    if not _HAS_GUI:
        return []
    try:
        active = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
    except Exception:
        active = None
    if active is None:
        return []
    try:
        obj = active.Object
    except Exception:
        return []
    if not obj or "Sketcher::SketchObject" not in getattr(obj, "TypeId", ""):
        return []
    dof = getattr(obj, "DoF", None)
    malformed = list(getattr(obj, "MalformedConstraints", []) or [])
    conflicting = list(getattr(obj, "ConflictingConstraints", []) or [])
    return [
        f"- Sketch: {obj.Name}",
        f"- DOF: {dof}",
        f"- Malformed: {malformed or '(none)'}",
        f"- Conflicting: {conflicting or '(none)'}",
    ]


def _last_operation_line() -> str | None:
    """Show the previous tool call's closed-loop summary, if any."""
    try:
        import tools
        summary = tools.get_last_result_summary()
    except Exception:
        return None
    if not summary:
        return None
    tool_name = summary.get("tool") or "?"
    if summary.get("ok"):
        created = summary.get("created")
        warn = summary.get("warnings") or []
        tail = f" → {created}" if created else ""
        if warn:
            tail += f" (warnings: {warn})"
        return f"- {tool_name}: ok{tail}"
    return f"- {tool_name}: FAILED ({summary.get('error')})"


def _active_workbench_name() -> str:
    if not _HAS_GUI:
        return "(no GUI)"
    try:
        wb = Gui.activeWorkbench()
        return getattr(wb, "name", lambda: wb.__class__.__name__)()
    except Exception:
        return "(unknown)"


def _units_scheme() -> str:
    try:
        schema = App.Units.getSchema()
        return f"schema={schema}"
    except Exception:
        return "mm (assumed)"


def _global_memory_text() -> str:
    candidates = []
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        candidates.append(os.path.join(env, "memory", "MEMORY.md"))
    candidates.append(
        os.path.expanduser(
            "~/.claude/projects/-home-code-CADAgent/memory/MEMORY.md"
        )
    )
    candidates.append(os.path.expanduser("~/.claude/cadagent/MEMORY.md"))
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except OSError:
                continue
    return ""


def _build_snapshot_sync() -> str:
    parts: list[str] = []

    doc = App.ActiveDocument
    if doc is None:
        parts.append("## Active doc\n(none — no FreeCAD document is open)")
    else:
        modified = bool(getattr(doc, "Modified", False))
        parts.append(
            "## Active doc\n"
            f"- Name: {doc.Name}\n"
            f"- Label: {doc.Label}\n"
            f"- FileName: {getattr(doc, 'FileName', '') or '(unsaved)'}\n"
            f"- Modified: {modified}\n"
            f"- Units: {_units_scheme()}"
        )

    parts.append(f"## Workbench\n- {_active_workbench_name()}")

    if doc is not None:
        body = _active_body(doc)
        if body is not None:
            parts.append(f"## Active Body\n- {body.Name} (label={body.Label!r})")
        else:
            parts.append("## Active Body\n- (none — no PartDesign::Body active)")

        tree = _feature_tree_lines(doc)
        if tree:
            parts.append("## Feature tree\n" + "\n".join(tree))
        else:
            parts.append("## Feature tree\n(empty document)")

    sel_lines = _selection_lines()
    if sel_lines:
        parts.append("## Selection\n" + "\n".join(sel_lines))
    else:
        parts.append("## Selection\n(nothing selected)")

    if doc is not None:
        param_lines = _parameters_lines(doc)
        if param_lines:
            parts.append("## Parameters\n" + "\n".join(param_lines))

        sketch_lines = _in_progress_sketch_lines(doc)
        if sketch_lines:
            parts.append("## In-progress sketch\n" + "\n".join(sketch_lines))

    view_line = _view_info()
    if view_line:
        parts.append("## View\n" + view_line)

    last_op = _last_operation_line()
    if last_op:
        parts.append("## Last operation\n" + last_op)

    if doc is not None:
        try:
            mem = project_memory.load(doc)
            intent = (mem.get("design_intent") or "").strip()
            params = mem.get("parameters") or {}
            decisions = mem.get("decisions") or []
            lines = []
            if intent:
                lines.append(f"- Intent: {intent}")
            if params:
                lines.append("- Parameters:")
                for name, spec in sorted(params.items()):
                    v = spec.get("value")
                    u = spec.get("unit", "")
                    note = spec.get("note", "")
                    suffix = f" — {note}" if note else ""
                    lines.append(f"  - {name} = {v} {u}{suffix}")
            if decisions:
                lines.append(f"- Decisions ({len(decisions)} total, last 3):")
                for d in decisions[-3:]:
                    lines.append(f"  - [{d.get('ts','')}] {d.get('text','')}")
            if lines:
                parts.append("## Project memory\n" + "\n".join(lines))
        except Exception as exc:
            parts.append(f"## Project memory\n(error loading: {exc})")

    mem_md = _global_memory_text()
    if mem_md:
        parts.append("## User memory\n" + mem_md)

    return "\n\n".join(parts)


def _max_chars() -> int:
    try:
        params = App.ParamGet(PARAM_PATH)
        n = params.GetInt("ContextSnapshotMaxChars", 0)
        return n if n > 0 else DEFAULT_MAX_CHARS
    except Exception:
        return DEFAULT_MAX_CHARS


def _enabled() -> bool:
    try:
        params = App.ParamGet(PARAM_PATH)
        return bool(params.GetBool("ContextSnapshotEnabled", True))
    except Exception:
        return True


def build_context_snapshot() -> str:
    """Build the snapshot on the Qt GUI thread. Safe to call from any thread."""
    if not _enabled():
        return ""
    try:
        text = run_sync(_build_snapshot_sync, timeout=5.0)
    except Exception as exc:
        return f"## Context\n(snapshot unavailable: {exc})"
    cap = _max_chars()
    if len(text) > cap:
        text = text[:cap] + f"\n… (truncated at {cap} chars)"
    return text


def wrap_user_message(user_text: str) -> str:
    snap = build_context_snapshot()
    if not snap:
        return user_text
    return f"<context>\n{snap}\n</context>\n\n<user>\n{user_text}\n</user>"
