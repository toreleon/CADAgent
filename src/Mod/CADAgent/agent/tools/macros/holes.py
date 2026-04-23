# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corner-hole pattern macro — pockets at each corner of a feature's top face."""

from __future__ import annotations

import traceback

import FreeCAD as App

from claude_agent_sdk import tool

from ... import errors, memory as project_memory
from ...gui_thread import run_sync
from .._shared import ok, resolve_doc, summarise_result
from ..partdesign._pd_shared import body_of


@tool(
    "add_corner_holes",
    (
        "Add clearance holes at the corners of a feature's top face. "
        "`feature` is the name of an existing Pad/Plate. `diameter` and "
        "`inset` in mm. `depth` defaults to through-all; otherwise extrude "
        "the hole sketch by that length. `pattern` is 4 (four corners)."
    ),
    {
        "type": "object",
        "properties": {
            "feature": {"type": "string"},
            "diameter": {"type": "number"},
            "inset": {"type": "number"},
            "depth": {"type": "number"},
            "pattern": {"type": "integer", "default": 4},
            "doc": {"type": "string"},
        },
        "required": ["feature", "diameter", "inset"],
    },
)
async def add_corner_holes(args):
    def _do():
        doc = resolve_doc(args.get("doc"))
        feat = doc.getObject(args["feature"])
        if feat is None:
            raise ValueError(f"No feature named {args['feature']!r}.")
        diameter = float(args["diameter"])
        inset = float(args["inset"])
        depth = args.get("depth")
        body = body_of(feat)
        if body is None:
            raise ValueError(f"{feat.Name} is not inside a PartDesign::Body.")

        def work():
            doc.openTransaction(f"CADAgent: add_corner_holes {feat.Name}")
            try:
                shape = feat.Shape
                bb = shape.BoundBox
                # Identify the top face (max Z planar face).
                top_face_idx = None
                for idx, face in enumerate(shape.Faces, start=1):
                    if face.Surface.__class__.__name__ != "Plane":
                        continue
                    if abs(face.CenterOfMass.z - bb.ZMax) < 1e-6:
                        top_face_idx = idx
                        break
                if top_face_idx is None:
                    raise ValueError("Could not find a planar top face on the feature.")

                sk = body.newObject("Sketcher::SketchObject", f"{feat.Name}_HoleSketch")
                if "AttachmentSupport" in sk.PropertiesList:
                    sk.AttachmentSupport = (feat, [f"Face{top_face_idx}"])
                else:
                    sk.Support = (feat, [f"Face{top_face_idx}"])
                sk.MapMode = "FlatFace"

                import Part
                r = diameter / 2
                # Hole centres offset by `inset` from each corner of the face's bbox.
                face = shape.Faces[top_face_idx - 1]
                fbb = face.BoundBox
                centres = [
                    (fbb.XMin + inset, fbb.YMin + inset),
                    (fbb.XMax - inset, fbb.YMin + inset),
                    (fbb.XMax - inset, fbb.YMax - inset),
                    (fbb.XMin + inset, fbb.YMax - inset),
                ][: int(args.get("pattern") or 4)]
                for cx, cy in centres:
                    sk.addGeometry(
                        Part.Circle(App.Vector(cx, cy, 0), App.Vector(0, 0, 1), r),
                        False,
                    )
                doc.recompute()

                pocket = body.newObject("PartDesign::Pocket", f"{feat.Name}_Holes")
                pocket.Profile = sk
                if depth is None:
                    pocket.Type = "ThroughAll"
                else:
                    pocket.Type = "Length"
                    pocket.Length = float(depth)
                doc.recompute()

                summary = summarise_result(doc, [sk.Name, pocket.Name])
                summary["body"] = body.Name
                summary["feature"] = feat.Name
                summary["holes"] = len(centres)
                if not summary.get("is_valid_solid"):
                    doc.abortTransaction()
                    return {"__error__": errors.fail("invalid_solid", feature=pocket.Name, **summary)}
                doc.commitTransaction()
                project_memory.append_decision(
                    doc,
                    f"add_corner_holes on {feat.Name}: ⌀{diameter} × {len(centres)} @ inset {inset}"
                )
                return summary
            except Exception:
                doc.abortTransaction()
                raise

        return work()

    try:
        result = run_sync(_do)
        if isinstance(result, dict) and "__error__" in result:
            return result["__error__"]
        return ok(result)
    except Exception as exc:
        return errors.fail(errors.classify_exception(exc), message=str(exc),
                           traceback=traceback.format_exc())


TOOL_FUNCS = [add_corner_holes]
TOOL_NAMES = ["add_corner_holes"]

