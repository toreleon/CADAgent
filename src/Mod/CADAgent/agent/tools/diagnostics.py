# SPDX-License-Identifier: LGPL-2.1-or-later
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
from mcp.types import ToolAnnotations

_READ_ONLY = ToolAnnotations(readOnlyHint=True)

from .. import errors
from ..gui_thread import run_sync
from ._shared import ok, resolve_doc


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
    annotations=_READ_ONLY,
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
    annotations=_READ_ONLY,
)
async def verify_sketch(args):
    def work():
        doc = resolve_doc(args.get("doc"))
        sk = doc.getObject(args["sketch"])
        if sk is None:
            return errors.fail("internal_error", message=f"No object {args['sketch']!r}.")
        try:
            sk.solve()
        except Exception:
            pass
        return ok({
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
    annotations=_READ_ONLY,
)
async def verify_feature(args):
    def work():
        doc = resolve_doc(args.get("doc"))
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
        return ok(info)
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
    annotations=_READ_ONLY,
)
async def preview_topology(args):
    def work():
        doc = resolve_doc(args.get("doc"))
        feat = doc.getObject(args["feature"])
        if feat is None:
            return errors.fail("internal_error", message=f"No object {args['feature']!r}.")
        shape = getattr(feat, "Shape", None)
        if shape is None:
            return ok({"feature": feat.Name, "faces": [], "edges": []})
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
        return ok({"feature": feat.Name, "faces": faces, "edges": edges})
    try:
        return run_sync(work)
    except Exception as exc:
        return errors.fail("internal_error", message=str(exc))


TOOL_FUNCS = [render_view, verify_sketch, verify_feature, preview_topology]
TOOL_NAMES = ["render_view", "verify_sketch", "verify_feature", "preview_topology"]


