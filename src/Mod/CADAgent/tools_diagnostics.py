# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2026 FreeCAD Project Association <www.freecad.org>      *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful,            *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with FreeCAD; if not, write to the Free Software        *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

"""Read-only diagnostic tools — verification and vision feedback.

These never mutate the document, so permissions.py auto-approves them. They
give the agent eyes (render_view), structured self-check on sketches and
features (verify_*), and a lightweight topology summary (preview_topology).
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import traceback

import FreeCAD as App

try:
    import FreeCADGui as Gui
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False

from claude_agent_sdk import tool

import errors
from gui_thread import run_sync


def _ok(payload: dict) -> dict:
    out = {"ok": True}
    out.update(payload)
    return {"content": [{"type": "text", "text": json.dumps(out, default=str)}]}


def _resolve_doc(doc_name):
    if doc_name:
        if doc_name not in App.listDocuments():
            raise ValueError(f"No document named {doc_name!r}.")
        return App.getDocument(doc_name)
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError("No active document.")
    return doc


@tool(
    "render_view",
    (
        "Capture a PNG of the active 3D view and return it inline (base64). "
        "Use this after significant geometry changes to visually verify the "
        "result matches the user's intent. width/height in pixels (default "
        "400×300)."
    ),
    {
        "type": "object",
        "properties": {
            "doc": {"type": "string"},
            "width": {"type": "integer", "default": 400},
            "height": {"type": "integer", "default": 300},
        },
    },
)
async def render_view(args):
    def work():
        if not _HAS_GUI:
            return errors.fail("internal_error", message="No GUI available.")
        w = int(args.get("width") or 400)
        h = int(args.get("height") or 300)
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None or not hasattr(view, "saveImage"):
            return errors.fail("internal_error", message="No active 3D view.")
        if hasattr(view, "fitAll"):
            try:
                view.fitAll()
            except Exception:
                pass
        fd, path = tempfile.mkstemp(suffix=".png", prefix="cadagent_view_")
        os.close(fd)
        try:
            view.saveImage(path, w, h, "Transparent")
            with open(path, "rb") as f:
                data = f.read()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        b64 = base64.b64encode(data).decode("ascii")
        return {
            "content": [
                {"type": "image", "data": b64, "mimeType": "image/png"},
                {"type": "text", "text": json.dumps({"ok": True, "width": w, "height": h})},
            ]
        }
    try:
        result = run_sync(work)
        if isinstance(result, dict) and "content" in result and "is_error" not in result:
            return result
        return result  # error payload
    except Exception as exc:
        return errors.fail("internal_error", message=str(exc),
                           traceback=traceback.format_exc())


@tool(
    "verify_sketch",
    "Return DOF, malformed and conflicting constraint ids for a sketch.",
    {"sketch": str, "doc": str},
)
async def verify_sketch(args):
    def work():
        doc = _resolve_doc(args.get("doc"))
        sk = doc.getObject(args["sketch"])
        if sk is None:
            return errors.fail("internal_error", message=f"No object {args['sketch']!r}.")
        try:
            sk.solve()
        except Exception:
            pass
        return _ok({
            "sketch": sk.Name,
            "dof": int(getattr(sk, "DoF", -1)),
            "malformed": list(getattr(sk, "MalformedConstraints", []) or []),
            "conflicting": list(getattr(sk, "ConflictingConstraints", []) or []),
            "redundant": list(getattr(sk, "RedundantConstraints", []) or []),
        })
    try:
        return run_sync(work)
    except Exception as exc:
        return errors.fail("internal_error", message=str(exc))


@tool(
    "verify_feature",
    "Return is_valid_solid, bbox, volume, and recompute errors for a feature.",
    {"feature": str, "doc": str},
)
async def verify_feature(args):
    def work():
        doc = _resolve_doc(args.get("doc"))
        feat = doc.getObject(args["feature"])
        if feat is None:
            return errors.fail("internal_error", message=f"No object {args['feature']!r}.")
        shape = getattr(feat, "Shape", None)
        info = {"feature": feat.Name, "type": feat.TypeId}
        if shape is not None:
            bb = shape.BoundBox
            info.update({
                "bbox": {
                    "xmin": bb.XMin, "xmax": bb.XMax,
                    "ymin": bb.YMin, "ymax": bb.YMax,
                    "zmin": bb.ZMin, "zmax": bb.ZMax,
                    "length": bb.XLength, "width": bb.YLength, "height": bb.ZLength,
                },
                "volume": float(shape.Volume),
                "is_valid_solid": bool(shape.isValid()),
                "face_count": len(shape.Faces),
                "edge_count": len(shape.Edges),
            })
        return _ok(info)
    try:
        return run_sync(work)
    except Exception as exc:
        return errors.fail("internal_error", message=str(exc))


@tool(
    "preview_topology",
    (
        "Return a compact topology summary for a feature: face/edge counts, "
        "per-face surface type and normal, per-edge length. Useful when "
        "picking refs for fillet/chamfer/hole without a UI selection."
    ),
    {"feature": str, "doc": str, "max_items": int},
)
async def preview_topology(args):
    def work():
        doc = _resolve_doc(args.get("doc"))
        feat = doc.getObject(args["feature"])
        if feat is None:
            return errors.fail("internal_error", message=f"No object {args['feature']!r}.")
        shape = getattr(feat, "Shape", None)
        if shape is None:
            return _ok({"feature": feat.Name, "faces": [], "edges": []})
        limit = int(args.get("max_items") or 40)
        faces = []
        for idx, face in enumerate(shape.Faces[:limit], start=1):
            surf = face.Surface
            entry = {
                "ref": f"{feat.Name}.Face{idx}",
                "surface": surf.__class__.__name__,
                "area": float(face.Area),
            }
            try:
                n = face.normalAt(0, 0)
                entry["normal"] = [round(n.x, 4), round(n.y, 4), round(n.z, 4)]
            except Exception:
                pass
            faces.append(entry)
        edges = []
        for idx, edge in enumerate(shape.Edges[:limit], start=1):
            edges.append({
                "ref": f"{feat.Name}.Edge{idx}",
                "length": float(edge.Length),
            })
        return _ok({"feature": feat.Name, "faces": faces, "edges": edges})
    try:
        return run_sync(work)
    except Exception as exc:
        return errors.fail("internal_error", message=str(exc))


TOOL_FUNCS = [render_view, verify_sketch, verify_feature, preview_topology]
TOOL_NAMES = ["render_view", "verify_sketch", "verify_feature", "preview_topology"]


def allowed_tool_names() -> list[str]:
    return [f"mcp__cad__{n}" for n in TOOL_NAMES]
