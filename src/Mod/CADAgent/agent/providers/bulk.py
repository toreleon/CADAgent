# SPDX-License-Identifier: LGPL-2.1-or-later
"""Bulk-native registrations for the remaining v1 tool bodies.

Every kind here is registered with ``_v1_adapter.port(...)``: a native
kind whose execute awaits the existing v1 handler and reshapes the legacy
MCP body into the uniform envelope. No behaviour change vs. the removed
``v1_passthrough.py``; the file is gone and so is the ``passthrough``
dispatch branch. Kinds that need per-handler work (pad/pocket, body,
datum.set, fillet, chamfer, sketch suite) live in their own native
provider files, not here.
"""

from __future__ import annotations

from typing import Any

from ..tools import doc as _doc
from ..tools import selection as _sel
from ..tools import geometry as _geom
from ..tools import diagnostics as _diag
from ..tools import memory as _mem
from ..tools import planning as _plan
from ..tools.macros import plate as _macro_plate
from ..tools.macros import holes as _macro_holes

from ._v1_adapter import port


# ---- inspect (read-only) ---------------------------------------------------

port(verb="inspect", kind="document.list", v1_tool=_doc.list_documents,
     description="List all open FreeCAD documents and the active doc.",
     params_schema={}, read_only=True, example={})
port(verb="inspect", kind="document.active", v1_tool=_doc.get_active_document,
     description="Active doc name + summary of objects (name, type, bbox, volume).",
     params_schema={}, read_only=True, example={})
port(verb="inspect", kind="object.list", v1_tool=_geom.list_objects,
     description="List all objects in a document with type / bbox / volume / visibility.",
     params_schema={"doc": "str?"}, read_only=True, example={})
port(verb="inspect", kind="object.get", v1_tool=_geom.get_object,
     description="Full property dump and bounding-box summary for one object.",
     params_schema={"name": "str", "doc": "str?"}, read_only=True,
     example={"name": "Body"})
port(verb="inspect", kind="selection.get", v1_tool=_sel.get_selection,
     description="Names of objects currently selected in the GUI.",
     params_schema={}, read_only=True, example={})
port(verb="inspect", kind="parameters.get", v1_tool=_mem.get_parameters,
     description="Named parameters from the project memory sidecar.",
     params_schema={"doc": "str?"}, read_only=True, example={})
port(verb="inspect", kind="topology.preview", v1_tool=_diag.preview_topology,
     description="Compact per-face / per-edge topology of a feature (no UI selection needed).",
     params_schema={"feature": "str", "doc": "str?", "max_items": "int?"},
     read_only=True, example={"feature": "Pad"})


# ---- verify (read-only + document.recompute) -------------------------------

port(verb="verify", kind="sketcher.sketch", v1_tool=_diag.verify_sketch,
     description="Return a sketch's DoF and lists of malformed/conflicting constraints.",
     params_schema={"sketch": "str", "doc": "str?"},
     read_only=True, example={"sketch": "Sketch"})
port(verb="verify", kind="partdesign.feature", v1_tool=_diag.verify_feature,
     description="Check solid validity, bbox, volume, face/edge counts of a feature.",
     params_schema={"feature": "str", "doc": "str?"},
     read_only=True, example={"feature": "Pad"})
port(verb="verify", kind="document.recompute", v1_tool=_doc.recompute_and_fit,
     description="Recompute a document and fit the 3D view to all objects.",
     params_schema={"doc": "str?"}, example={})


# ---- render ----------------------------------------------------------------

port(verb="render", kind="view.png", v1_tool=_diag.render_view,
     description="Capture a PNG of the active 3D view (base64-inline).",
     params_schema={"doc": "str?", "width": "int?", "height": "int?"},
     read_only=True, example={})


# ---- create (primitives + macros) ------------------------------------------

port(verb="create", kind="document", v1_tool=_doc.create_document,
     description="Create a new FreeCAD document and make it active.",
     params_schema={"name": "str"},
     example={"name": "Bracket"})
port(verb="create", kind="part.box", v1_tool=_geom.make_box,
     description="Parametric Part::Box (length, width, height in mm).",
     params_schema={"length": "float", "width": "float", "height": "float",
                     "name": "str?", "doc": "str?"},
     example={"length": 20, "width": 10, "height": 5})
port(verb="create", kind="part.cylinder", v1_tool=_geom.make_cylinder,
     description="Parametric Part::Cylinder (radius, height in mm).",
     params_schema={"radius": "float", "height": "float",
                     "name": "str?", "doc": "str?"},
     example={"radius": 3, "height": 8})
port(verb="create", kind="part.sphere", v1_tool=_geom.make_sphere,
     description="Parametric Part::Sphere (radius in mm).",
     params_schema={"radius": "float", "name": "str?", "doc": "str?"},
     example={"radius": 5})
port(verb="create", kind="part.cone", v1_tool=_geom.make_cone,
     description="Parametric Part::Cone (radius1, radius2, height in mm).",
     params_schema={"radius1": "float", "radius2": "float", "height": "float",
                     "name": "str?", "doc": "str?"},
     example={"radius1": 5, "radius2": 2, "height": 10})
port(verb="create", kind="part.boolean", v1_tool=_geom.boolean_op,
     description="Parametric boolean (op='fuse'|'cut'|'common') between two existing objects.",
     params_schema={"op": "str", "base": "str", "tool_name": "str",
                     "name": "str?", "doc": "str?"},
     example={"op": "fuse", "base": "Box", "tool_name": "Cyl"})

# Macros — still available as kinds until we cut them over to prompt recipes.
port(verb="create", kind="macro.parametric_box", v1_tool=_macro_plate.make_parametric_box,
     description="Macro: Body + Sketch(rectangle) + Pad in one undo step. Optional Parameters binding.",
     params_schema={"length": "float", "width": "float", "height": "float",
                     "label": "str?", "parametric": "bool?", "doc": "str?"},
     example={"length": 30, "width": 15, "height": 4})
port(verb="create", kind="macro.parametric_cylinder", v1_tool=_macro_plate.make_parametric_cylinder,
     description="Macro: Body + Sketch(circle) + Pad cylinder. Optional Parameters binding.",
     params_schema={"radius": "float", "height": "float",
                     "label": "str?", "parametric": "bool?", "doc": "str?"},
     example={"radius": 5, "height": 20})
port(verb="create", kind="macro.parametric_plate", v1_tool=_macro_plate.make_parametric_plate,
     description="Macro: rectangular plate with optional corner radius and Parameters binding.",
     params_schema={"length": "float", "width": "float", "thickness": "float",
                     "corner_radius": "float?", "label": "str?",
                     "parametric": "bool?", "doc": "str?"},
     example={"length": 50, "width": 30, "thickness": 4})
port(verb="create", kind="macro.corner_holes", v1_tool=_macro_holes.add_corner_holes,
     description="Macro: pattern N clearance holes at the corners of a feature's top face.",
     params_schema={"feature": "str", "diameter": "float", "inset": "float",
                     "depth": "float?", "pattern": "int?", "doc": "str?"},
     example={"feature": "Pad", "diameter": 4.0, "inset": 3.0, "pattern": 4})


# ---- modify ----------------------------------------------------------------

port(verb="modify", kind="placement.set", v1_tool=_sel.set_placement,
     description="Set position [x,y,z] mm and/or rotation (axis, angle deg) on an object.",
     params_schema={"name": "str", "position": "list[float]?",
                     "rotation_axis": "list[float]?", "rotation_angle": "float?",
                     "doc": "str?"},
     example={"name": "Body", "position": [10, 0, 0]})
port(verb="modify", kind="parameter.set", v1_tool=_mem.set_parameter,
     description="Write a parameter to the sidecar AND the Parameters spreadsheet.",
     params_schema={"name": "str", "value": "float", "unit": "str?",
                     "note": "str?", "doc": "str?"},
     example={"name": "Thickness", "value": 4.0, "unit": "mm"})


# ---- delete ----------------------------------------------------------------

port(verb="delete", kind="object", v1_tool=_sel.delete_object,
     description="Remove an object from the document.",
     params_schema={"name": "str", "doc": "str?"},
     example={"name": "Box"})


# ---- io --------------------------------------------------------------------

port(verb="io", kind="step.export", v1_tool=_doc.export_step,
     description="Export named objects to a STEP file.",
     params_schema={"names": "list[str]", "path": "str", "doc": "str?"},
     example={"names": ["Body"], "path": "/tmp/out.step"})


# ---- memory ----------------------------------------------------------------

port(verb="memory", kind="read", v1_tool=_mem.read_project_memory,
     description="Return the full project-memory sidecar.",
     params_schema={"doc": "str?"}, read_only=True, example={})
port(verb="memory", kind="note.write", v1_tool=_mem.write_project_memory_note,
     description="Write an arbitrary key=value into a top-level sidecar section.",
     params_schema={"section": "str", "key": "str", "value": "any", "doc": "str?"},
     example={"section": "notes", "key": "todo", "value": "review bracket"})
port(verb="memory", kind="decision.record", v1_tool=_plan.record_decision,
     description="Write a typed decision record (goal, constraints, alternatives, …).",
     params_schema={"goal": "str?", "constraints": "list[str]?",
                     "alternatives": "list[str]?", "choice": "str?",
                     "rationale": "str?", "depends_on": "list[str]?",
                     "milestone": "str?", "doc": "str?"},
     example={"goal": "M6 clearance", "choice": "6.5 mm"})
port(verb="memory", kind="decision.list", v1_tool=_plan.list_decisions,
     description="List all typed decision records for the active document.",
     params_schema={"doc": "str?"}, read_only=True, example={})


# ---- plan ------------------------------------------------------------------

port(verb="plan", kind="emit", v1_tool=_plan.emit_plan,
     description="Submit a milestone plan (planner only). Replaces any existing plan.",
     params_schema={"milestones": "list[dict]", "plan_id": "str?", "doc": "str?"},
     example={"milestones": [{"id": "m1", "title": "…", "acceptance": "…"}]})
port(verb="plan", kind="active.get", v1_tool=_plan.get_active_milestone,
     description="Return the current (active or next pending) milestone, or null.",
     params_schema={"doc": "str?"}, read_only=True, example={})
port(verb="plan", kind="milestone.activate", v1_tool=_plan.mark_milestone_active,
     description="Transition a milestone to 'active' (executor).",
     params_schema={"milestone_id": "str", "notes": "str?",
                     "session_id": "str?", "doc": "str?"},
     example={"milestone_id": "m1"})
port(verb="plan", kind="milestone.done", v1_tool=_plan.mark_milestone_done,
     description="Mark a milestone 'done' (acceptance + verify_* satisfied).",
     params_schema={"milestone_id": "str", "notes": "str?",
                     "session_id": "str?", "doc": "str?"},
     example={"milestone_id": "m1"})
port(verb="plan", kind="milestone.failed", v1_tool=_plan.mark_milestone_failed,
     description="Mark a milestone 'failed'; hands back to the planner.",
     params_schema={"milestone_id": "str", "notes": "str?",
                     "session_id": "str?", "doc": "str?"},
     example={"milestone_id": "m1"})


# ---- exec ------------------------------------------------------------------

port(verb="exec", kind="python.exec", v1_tool=_doc.run_python,
     description="Execute arbitrary FreeCAD Python in a transaction. Last resort.",
     params_schema={"code": "str", "label": "str", "doc": "str?"},
     example={"code": "App.ActiveDocument.addObject('Part::Box','B')", "label": "demo"})
