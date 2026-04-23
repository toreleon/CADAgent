# SPDX-License-Identifier: LGPL-2.1-or-later
"""Assembly workbench provider — native v2 kinds.

FreeCAD 1.x ships Assembly as a built-in workbench (``Assembly`` +
``UtilsAssembly`` Python modules). Previously CADAgent had no Assembly
tools at all — the Assembler subagent returned ``None``. This provider
ships the first-class kinds the ``assembly-bottom-up`` skill references.

The API here is intentionally minimal: create an assembly container,
reference a part, ground it, add one of five joint types. Anything more
exotic (gear couplings, cam joints, sub-assemblies) falls back to
``cad_exec(kind=python.exec)`` until it's worth a dedicated kind.
"""

from __future__ import annotations

from typing import Any

import FreeCAD as App

from .. import registry
from ..registry import required_str, positive_number, chain


def _import_assembly():
    """Lazy-import the Assembly module; raise a helpful error if absent."""
    try:
        import Assembly  # type: ignore
        import UtilsAssembly  # type: ignore
        return Assembly, UtilsAssembly
    except ImportError as exc:  # pragma: no cover — environment-dependent
        raise RuntimeError(
            "FreeCAD Assembly workbench not available in this build. "
            "Re-build with Assembly enabled, or fall back to cad_exec."
        ) from exc


def _create_assembly(doc, params: dict) -> Any:
    Assembly, _ = _import_assembly()
    label = params.get("label") or "Assembly"
    asm = Assembly.makeAssembly(doc, label)
    doc.recompute()
    return asm


def _add_part_ref(doc, params: dict) -> Any:
    _, UtilsAssembly = _import_assembly()
    asm = doc.getObject(params["assembly"])
    if asm is None:
        raise ValueError(f"Assembly {params['assembly']!r} not found")
    source = doc.getObject(params["source"])
    if source is None:
        raise ValueError(f"Source part {params['source']!r} not found")
    ref = UtilsAssembly.createAssemblyLink(asm, source)
    doc.recompute()
    return ref


def _ground_part(doc, params: dict) -> Any:
    _, UtilsAssembly = _import_assembly()
    asm = doc.getObject(params["assembly"])
    part_ref = doc.getObject(params["part_ref"])
    if asm is None or part_ref is None:
        raise ValueError("assembly and part_ref must both exist")
    # Assembly grounds parts via a GroundedJoint object. API: UtilsAssembly.createGroundedJoint
    joint = UtilsAssembly.createGroundedJoint(asm, part_ref)
    doc.recompute()
    return joint


_JOINT_KINDS = {
    "fixed": "Fixed",
    "revolute": "Revolute",
    "slider": "Slider",
    "ball": "Ball",
    "distance": "Distance",
}


def _make_joint_factory(joint_name: str):
    """Return an execute() that creates a joint of the given assembly joint type."""
    def _execute(doc, params: dict) -> Any:
        _, UtilsAssembly = _import_assembly()
        asm = doc.getObject(params["assembly"])
        if asm is None:
            raise ValueError(f"Assembly {params['assembly']!r} not found")
        # Each joint needs two references: (part_ref_a, element_a, part_ref_b, element_b).
        # Element strings are subnames like "Face1" / "Edge2" / "Vertex3".
        ref_a = doc.getObject(params["part_a"])
        ref_b = doc.getObject(params["part_b"])
        if ref_a is None or ref_b is None:
            raise ValueError("part_a and part_b must both exist in the assembly")
        elem_a = params.get("element_a", "")
        elem_b = params.get("element_b", "")
        # UtilsAssembly exposes createJoint(assembly, type_name, part_a, elem_a, part_b, elem_b)
        joint = UtilsAssembly.createJoint(
            asm, joint_name, ref_a, elem_a, ref_b, elem_b
        )
        # Distance joints need a value.
        if joint_name == "Distance" and "distance" in params:
            joint.Distance = float(params["distance"])
        doc.recompute()
        return joint
    return _execute


# ---- registrations ---------------------------------------------------------

registry.register(
    verb="create", kind="assembly.assembly",
    description="Create a new Assembly container (FreeCAD 1.x Assembly workbench).",
    params_schema={"label": "str?"},
    execute=_create_assembly,
)

registry.register(
    verb="create", kind="assembly.part_ref",
    description="Reference an existing Body/Part into an Assembly (placement-bound link, not a clone).",
    params_schema={"assembly": "str", "source": "str"},
    execute=_add_part_ref,
    preflight=required_str("assembly", "source"),
)

registry.register(
    verb="modify", kind="assembly.ground",
    description="Ground a part reference in an assembly (anchor for the solver).",
    params_schema={"assembly": "str", "part_ref": "str"},
    execute=_ground_part,
    preflight=required_str("assembly", "part_ref"),
)

for _slug, _type in _JOINT_KINDS.items():
    registry.register(
        verb="create",
        kind=f"assembly.joint.{_slug}",
        description=(
            f"Create an Assembly {_type} joint between two part references. "
            f"Elements are subname strings like 'Face1' / 'Edge2' / 'Vertex3'. "
            + ("Requires 'distance' param (mm)." if _slug == "distance" else "")
        ),
        params_schema={
            "assembly": "str",
            "part_a": "str",
            "part_b": "str",
            "element_a": "str?",
            "element_b": "str?",
            **({"distance": "float"} if _slug == "distance" else {}),
        },
        execute=_make_joint_factory(_type),
        preflight=chain(
            required_str("assembly", "part_a", "part_b"),
            *( [positive_number("distance")] if _slug == "distance" else [] ),
        ),
    )
