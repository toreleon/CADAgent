# SPDX-License-Identifier: LGPL-2.1-or-later
"""v1 → v2 passthrough providers.

This single file maps every existing v1 tool onto the new verb surface as a
passthrough kind. The v1 implementations under ``agent/tools/`` are reused
verbatim — Phase 1 of the migration is purely about the public interface
(10 verbs + many kinds) without rewriting any operation bodies.

Once Phase 3+ provider modules ship native v2 implementations for new
workbenches (Assembly, Draft, Mesh, …), they'll register kinds with
``passthrough=False`` and use the registry's preflight/postflight/transaction
machinery directly. v1 kinds stay here until v1 is deleted in Phase 4 cutover.
"""

from __future__ import annotations

from ..tools import doc as _doc
from ..tools import selection as _sel
from ..tools import geometry as _geom
from ..tools import diagnostics as _diag
from ..tools import memory as _mem
from ..tools import planning as _plan
from ..tools.partdesign import body as _pd_body
from ..tools.partdesign import sketch as _pd_sketch
from ..tools.partdesign import pad_pocket as _pd_pp
from ..tools.partdesign import dress_ups as _pd_du
from ..tools.macros import plate as _macro_plate
from ..tools.macros import holes as _macro_holes

from ._helpers import passthrough


# ---- inspect (read-only introspection) -------------------------------------

passthrough(
    verb="inspect", kind="document.list", v1_tool=_doc.list_documents,
    description="List all open FreeCAD documents and the active doc.",
    params_schema={}, read_only=True,
)
passthrough(
    verb="inspect", kind="document.active", v1_tool=_doc.get_active_document,
    description="Active doc name + summary of objects (name, type, bbox, volume).",
    params_schema={}, read_only=True,
)
passthrough(
    verb="inspect", kind="object.list", v1_tool=_geom.list_objects,
    description="List all objects in a document with type / bbox / volume / visibility.",
    params_schema={"doc": "str?"}, read_only=True,
)
passthrough(
    verb="inspect", kind="object.get", v1_tool=_geom.get_object,
    description="Full property dump and bounding-box summary for one object.",
    params_schema={"name": "str", "doc": "str?"}, read_only=True,
)
passthrough(
    verb="inspect", kind="selection.get", v1_tool=_sel.get_selection,
    description="Names of objects currently selected in the GUI.",
    params_schema={}, read_only=True,
)
passthrough(
    verb="inspect", kind="parameters.get", v1_tool=_mem.get_parameters,
    description="Named parameters from the project memory sidecar.",
    params_schema={"doc": "str?"}, read_only=True,
)
passthrough(
    verb="inspect", kind="topology.preview", v1_tool=_diag.preview_topology,
    description="Compact per-face / per-edge topology of a feature (no UI selection needed).",
    params_schema={"feature": "str", "doc": "str?", "max_items": "int?"}, read_only=True,
)


# ---- verify (read-only verification) ---------------------------------------

passthrough(
    verb="verify", kind="sketcher.sketch", v1_tool=_diag.verify_sketch,
    description="Return a sketch's DoF and lists of malformed/conflicting constraints.",
    params_schema={"sketch": "str", "doc": "str?"}, read_only=True,
)
passthrough(
    verb="verify", kind="partdesign.feature", v1_tool=_diag.verify_feature,
    description="Check solid validity, bbox, volume, face/edge counts of a feature.",
    params_schema={"feature": "str", "doc": "str?"}, read_only=True,
)
passthrough(
    verb="verify", kind="sketcher.close", v1_tool=_pd_sketch.close_sketch,
    description="Solve a sketch and report final DoF + bad constraint ids.",
    params_schema={"sketch": "str", "doc": "str?"},
)
passthrough(
    verb="verify", kind="document.recompute", v1_tool=_doc.recompute_and_fit,
    description="Recompute a document and fit the 3D view to all objects.",
    params_schema={"doc": "str?"},
)


# ---- render ----------------------------------------------------------------

passthrough(
    verb="render", kind="view.png", v1_tool=_diag.render_view,
    description="Capture a PNG of the active 3D view (base64-inline).",
    params_schema={"doc": "str?", "width": "int?", "height": "int?"}, read_only=True,
)


# ---- create (parametric features and primitives) ---------------------------

passthrough(
    verb="create", kind="document", v1_tool=_doc.create_document,
    description="Create a new FreeCAD document and make it active.",
    params_schema={"name": "str"},
)
passthrough(
    verb="create", kind="part.box", v1_tool=_geom.make_box,
    description="Parametric Part::Box (length, width, height in mm).",
    params_schema={"length": "float", "width": "float", "height": "float", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="part.cylinder", v1_tool=_geom.make_cylinder,
    description="Parametric Part::Cylinder (radius, height in mm).",
    params_schema={"radius": "float", "height": "float", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="part.sphere", v1_tool=_geom.make_sphere,
    description="Parametric Part::Sphere (radius in mm).",
    params_schema={"radius": "float", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="part.cone", v1_tool=_geom.make_cone,
    description="Parametric Part::Cone (radius1, radius2, height in mm).",
    params_schema={"radius1": "float", "radius2": "float", "height": "float", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="partdesign.body", v1_tool=_pd_body.create_body,
    description="Create a new PartDesign::Body (and optionally make it active).",
    params_schema={"label": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="partdesign.sketch", v1_tool=_pd_sketch.create_sketch,
    description="Create a blank Sketcher sketch on a plane (XY/XZ/YZ or Feature.FaceN).",
    params_schema={"plane": "str", "body": "str?", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="partdesign.sketch_from_profile", v1_tool=_pd_sketch.sketch_from_profile,
    description="Create a fully-constrained sketch (DoF=0) from a structured profile.",
    params_schema={"plane": "str", "profile": "dict", "body": "str?", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="partdesign.pad", v1_tool=_pd_pp.pad,
    description="Extrude a sketch into a PartDesign::Pad.",
    params_schema={"sketch": "str", "length": "float", "type_": "str?", "midplane": "bool?", "reversed": "bool?", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="partdesign.pocket", v1_tool=_pd_pp.pocket,
    description="Subtract a sketch extrusion (PartDesign::Pocket).",
    params_schema={"sketch": "str", "length": "float?", "through_all": "bool?", "reversed": "bool?", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="partdesign.fillet", v1_tool=_pd_du.fillet,
    description="Add a PartDesign::Fillet on edges (Feature.EdgeN refs).",
    params_schema={"edges": "list[str]", "radius": "float", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="partdesign.chamfer", v1_tool=_pd_du.chamfer,
    description="Add a PartDesign::Chamfer on edges.",
    params_schema={"edges": "list[str]", "size": "float", "name": "str?", "doc": "str?"},
)
passthrough(
    verb="create", kind="part.boolean", v1_tool=_geom.boolean_op,
    description="Parametric boolean (op='fuse'|'cut'|'common') between two existing objects.",
    params_schema={"op": "str", "base": "str", "tool_name": "str", "name": "str?", "doc": "str?"},
)
# Tier-A macros remain available as kinds during the migration. After Phase 2
# they become Skills (markdown patterns the model loads on demand) and these
# entries are removed in Phase 4 cutover.
passthrough(
    verb="create", kind="macro.parametric_box", v1_tool=_macro_plate.make_parametric_box,
    description="Macro: Body + Sketch(rectangle) + Pad in one undo step. Optional Parameters binding.",
    params_schema={"length": "float", "width": "float", "height": "float", "label": "str?", "parametric": "bool?", "doc": "str?"},
)
passthrough(
    verb="create", kind="macro.parametric_cylinder", v1_tool=_macro_plate.make_parametric_cylinder,
    description="Macro: Body + Sketch(circle) + Pad cylinder. Optional Parameters binding.",
    params_schema={"radius": "float", "height": "float", "label": "str?", "parametric": "bool?", "doc": "str?"},
)
passthrough(
    verb="create", kind="macro.parametric_plate", v1_tool=_macro_plate.make_parametric_plate,
    description="Macro: rectangular plate with optional corner radius and Parameters binding.",
    params_schema={"length": "float", "width": "float", "thickness": "float", "corner_radius": "float?", "label": "str?", "parametric": "bool?", "doc": "str?"},
)
passthrough(
    verb="create", kind="macro.corner_holes", v1_tool=_macro_holes.add_corner_holes,
    description="Macro: pattern N clearance holes at the corners of a feature's top face.",
    params_schema={"feature": "str", "diameter": "float", "inset": "float", "depth": "float?", "pattern": "int?", "doc": "str?"},
)


# ---- modify (edit existing geometry / properties) --------------------------

passthrough(
    verb="modify", kind="placement.set", v1_tool=_sel.set_placement,
    description="Set position [x,y,z] mm and/or rotation (axis, angle deg) on an object.",
    params_schema={"name": "str", "position": "list[float]?", "rotation_axis": "list[float]?", "rotation_angle": "float?", "doc": "str?"},
)
passthrough(
    verb="modify", kind="datum.set", v1_tool=_pd_body.set_datum,
    description="Set a feature property to a value or expression (e.g., 'Parameters.Thickness').",
    params_schema={"feature": "str", "property_": "str", "value_or_expr": "any", "doc": "str?"},
)
passthrough(
    verb="modify", kind="parameter.set", v1_tool=_mem.set_parameter,
    description="Write a parameter to the sidecar AND the Parameters spreadsheet.",
    params_schema={"name": "str", "value": "float", "unit": "str?", "note": "str?", "doc": "str?"},
)
passthrough(
    verb="modify", kind="sketcher.geometry.add", v1_tool=_pd_sketch.add_sketch_geometry,
    description="Add geometry (line, circle, arc, rectangle, polyline) to a sketch.",
    params_schema={"sketch": "str", "kind": "str", "params": "dict", "construction": "bool?", "doc": "str?"},
)
passthrough(
    verb="modify", kind="sketcher.constraint.add", v1_tool=_pd_sketch.add_sketch_constraint,
    description="Add a sketch constraint (Coincident, Distance, Radius, Parallel, Tangent, …).",
    params_schema={"sketch": "str", "kind": "str", "refs": "list[int]", "value": "float?", "doc": "str?"},
)


# ---- delete -----------------------------------------------------------------

passthrough(
    verb="delete", kind="object", v1_tool=_sel.delete_object,
    description="Remove an object from the document.",
    params_schema={"name": "str", "doc": "str?"},
)


# ---- io ---------------------------------------------------------------------

passthrough(
    verb="io", kind="step.export", v1_tool=_doc.export_step,
    description="Export named objects to a STEP file.",
    params_schema={"names": "list[str]", "path": "str", "doc": "str?"},
)


# ---- memory -----------------------------------------------------------------

passthrough(
    verb="memory", kind="read", v1_tool=_mem.read_project_memory,
    description="Return the full project-memory sidecar.",
    params_schema={"doc": "str?"}, read_only=True,
)
passthrough(
    verb="memory", kind="note.write", v1_tool=_mem.write_project_memory_note,
    description="Write an arbitrary key=value into a top-level sidecar section.",
    params_schema={"section": "str", "key": "str", "value": "any", "doc": "str?"},
)
passthrough(
    verb="memory", kind="decision.record", v1_tool=_plan.record_decision,
    description="Write a typed decision record (goal, constraints, alternatives, …).",
    params_schema={"goal": "str?", "constraints": "list[str]?", "alternatives": "list[str]?", "choice": "str?", "rationale": "str?", "depends_on": "list[str]?", "milestone": "str?", "doc": "str?"},
)
passthrough(
    verb="memory", kind="decision.list", v1_tool=_plan.list_decisions,
    description="List all typed decision records for the active document.",
    params_schema={"doc": "str?"}, read_only=True,
)


# ---- plan -------------------------------------------------------------------

passthrough(
    verb="plan", kind="emit", v1_tool=_plan.emit_plan,
    description="Submit a milestone plan (planner only). Replaces any existing plan.",
    params_schema={"milestones": "list[dict]", "plan_id": "str?", "doc": "str?"},
)
passthrough(
    verb="plan", kind="active.get", v1_tool=_plan.get_active_milestone,
    description="Return the current (active or next pending) milestone, or null.",
    params_schema={"doc": "str?"}, read_only=True,
)
passthrough(
    verb="plan", kind="milestone.activate", v1_tool=_plan.mark_milestone_active,
    description="Transition a milestone to 'active' (executor).",
    params_schema={"milestone_id": "str", "notes": "str?", "session_id": "str?", "doc": "str?"},
)
passthrough(
    verb="plan", kind="milestone.done", v1_tool=_plan.mark_milestone_done,
    description="Mark a milestone 'done' (acceptance + verify_* satisfied).",
    params_schema={"milestone_id": "str", "notes": "str?", "session_id": "str?", "doc": "str?"},
)
passthrough(
    verb="plan", kind="milestone.failed", v1_tool=_plan.mark_milestone_failed,
    description="Mark a milestone 'failed'; hands back to the planner.",
    params_schema={"milestone_id": "str", "notes": "str?", "session_id": "str?", "doc": "str?"},
)


# ---- exec (escape hatch) ---------------------------------------------------

passthrough(
    verb="exec", kind="python.exec", v1_tool=_doc.run_python,
    description="Execute arbitrary FreeCAD Python in a transaction. Last resort.",
    params_schema={"code": "str", "label": "str", "doc": "str?"},
)
