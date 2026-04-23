# SPDX-License-Identifier: LGPL-2.1-or-later
"""Mesh workbench provider — convert solids to meshes and clean them up.

These wrap FreeCAD's ``Mesh`` and ``MeshPart`` modules. Anything beyond
the registered kinds (segmentation, advanced repair, harmonic mapping)
falls back to ``cad_exec``.
"""

from __future__ import annotations

import FreeCAD as App

from .. import registry
from ..registry import required_str, positive_number, chain


def _from_shape(doc, params: dict):
    import Mesh, MeshPart  # type: ignore
    src = doc.getObject(params["source"])
    if src is None or not hasattr(src, "Shape"):
        raise ValueError(f"source {params['source']!r} has no Shape")
    linear_def = float(params.get("linear_deflection", 0.1))
    angular_def = float(params.get("angular_deflection", 0.5))
    mesh = MeshPart.meshFromShape(
        Shape=src.Shape, LinearDeflection=linear_def, AngularDeflection=angular_def,
    )
    obj = doc.addObject("Mesh::Feature", f"{src.Name}_Mesh")
    obj.Mesh = mesh
    doc.recompute()
    return obj


def _decimate(doc, params: dict):
    obj = doc.getObject(params["target"])
    if obj is None or not hasattr(obj, "Mesh"):
        raise ValueError(f"target {params['target']!r} is not a mesh")
    reduction = float(params.get("reduction", 0.5))  # 0..1, fraction of triangles to remove
    obj.Mesh.decimate(reduction)
    doc.recompute()
    return obj


def _smooth(doc, params: dict):
    obj = doc.getObject(params["target"])
    if obj is None or not hasattr(obj, "Mesh"):
        raise ValueError(f"target {params['target']!r} is not a mesh")
    iterations = int(params.get("iterations", 1))
    obj.Mesh.smooth(iterations)
    doc.recompute()
    return obj


def _fill_holes(doc, params: dict):
    obj = doc.getObject(params["target"])
    if obj is None or not hasattr(obj, "Mesh"):
        raise ValueError(f"target {params['target']!r} is not a mesh")
    max_size = float(params.get("max_hole_size", 1e6))
    obj.Mesh.fillupHoles(max_size)
    doc.recompute()
    return obj


def _boolean(doc, params: dict):
    import Mesh  # type: ignore
    op = params["op"].lower()
    a = doc.getObject(params["base"])
    b = doc.getObject(params["tool"])
    if a is None or b is None:
        raise ValueError("base and tool must both be mesh objects")
    fns = {"union": "unite", "difference": "difference", "intersection": "intersect"}
    if op not in fns:
        raise ValueError("op must be one of union, difference, intersection")
    out = getattr(a.Mesh, fns[op])(b.Mesh)
    obj = doc.addObject("Mesh::Feature", f"{op.capitalize()}")
    obj.Mesh = out
    doc.recompute()
    return obj


registry.register(
    verb="create", kind="mesh.from_shape",
    description="Convert a Part/Body shape to a mesh (linear + angular deflection in mm/rad).",
    params_schema={"source": "str", "linear_deflection": "float?", "angular_deflection": "float?"},
    execute=_from_shape, preflight=required_str("source"),
)

registry.register(
    verb="modify", kind="mesh.decimate",
    description="Decimate a mesh by removing a fraction (0..1) of triangles.",
    params_schema={"target": "str", "reduction": "float?"},
    execute=_decimate, preflight=required_str("target"),
)

registry.register(
    verb="modify", kind="mesh.smooth",
    description="Laplacian-smooth a mesh in place for N iterations.",
    params_schema={"target": "str", "iterations": "int?"},
    execute=_smooth, preflight=required_str("target"),
)

registry.register(
    verb="modify", kind="mesh.fill_holes",
    description="Fill holes in a mesh up to max_hole_size (longest edge in mm).",
    params_schema={"target": "str", "max_hole_size": "float?"},
    execute=_fill_holes, preflight=required_str("target"),
)

registry.register(
    verb="create", kind="mesh.boolean",
    description="Mesh boolean: op='union'|'difference'|'intersection' between base and tool meshes.",
    params_schema={"op": "str", "base": "str", "tool": "str"},
    execute=_boolean, preflight=required_str("op", "base", "tool"),
)
