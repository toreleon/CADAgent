# SPDX-License-Identifier: LGPL-2.1-or-later
"""Import / export kinds for the cad_io verb beyond the v1 STEP-export shim.

Native FreeCAD I/O modules: ``Import`` (STEP/IGES/BREP), ``Mesh`` (STL/OBJ
mesh), ``importDXF``. Each kind here lazy-imports the handler module so a
build that strips one of them only loses that kind, not the whole verb.
"""

from __future__ import annotations

from pathlib import Path

import FreeCAD as App

from .. import registry
from ..registry import required_str


def _import_step(doc, params: dict):
    import Import
    Import.insert(params["path"], doc.Name)
    doc.recompute()
    return [o.Name for o in doc.Objects[-1:]]  # last-added object as a hint


def _export_step(doc, params: dict):
    import Import
    targets = [doc.getObject(n) for n in params["names"]]
    targets = [t for t in targets if t is not None]
    Import.export(targets, params["path"])
    return [t.Name for t in targets]


def _import_iges(doc, params: dict):
    import Import
    Import.insert(params["path"], doc.Name)
    doc.recompute()
    return []


def _export_iges(doc, params: dict):
    import Import
    targets = [doc.getObject(n) for n in params["names"] if doc.getObject(n)]
    Import.export(targets, params["path"])
    return [t.Name for t in targets]


def _import_brep(doc, params: dict):
    import Part
    shape = Part.Shape()
    shape.read(params["path"])
    obj = doc.addObject("Part::Feature", Path(params["path"]).stem)
    obj.Shape = shape
    doc.recompute()
    return obj


def _export_brep(doc, params: dict):
    import Part
    targets = [doc.getObject(n) for n in params["names"] if doc.getObject(n)]
    if not targets:
        raise ValueError("No matching objects to export")
    compound = Part.makeCompound([t.Shape for t in targets])
    compound.exportBrep(params["path"])
    return [t.Name for t in targets]


def _import_stl(doc, params: dict):
    import Mesh
    name = Path(params["path"]).stem
    mesh = Mesh.Mesh()
    mesh.read(params["path"])
    obj = doc.addObject("Mesh::Feature", name)
    obj.Mesh = mesh
    doc.recompute()
    return obj


def _export_stl(doc, params: dict):
    import Mesh
    targets = [doc.getObject(n) for n in params["names"] if doc.getObject(n)]
    if not targets:
        raise ValueError("No matching objects to export")
    Mesh.export(targets, params["path"])
    return [t.Name for t in targets]


def _import_obj(doc, params: dict):
    import Mesh
    Mesh.insert(params["path"], doc.Name)
    doc.recompute()
    return []


def _export_obj(doc, params: dict):
    import Mesh
    targets = [doc.getObject(n) for n in params["names"] if doc.getObject(n)]
    Mesh.export(targets, params["path"])
    return [t.Name for t in targets]


def _import_dxf(doc, params: dict):
    import importDXF  # type: ignore
    importDXF.insert(params["path"], doc.Name)
    doc.recompute()
    return []


def _export_dxf(doc, params: dict):
    import importDXF  # type: ignore
    targets = [doc.getObject(n) for n in params["names"] if doc.getObject(n)]
    importDXF.export(targets, params["path"])
    return [t.Name for t in targets]


# ---- registrations ---------------------------------------------------------

_FORMATS = [
    ("step",  "STEP",  _import_step,  _export_step),
    ("iges",  "IGES",  _import_iges,  _export_iges),
    ("brep",  "BREP",  _import_brep,  _export_brep),
    ("stl",   "STL mesh", _import_stl, _export_stl),
    ("obj",   "OBJ mesh", _import_obj, _export_obj),
    ("dxf",   "DXF",   _import_dxf,  _export_dxf),
]


for _slug, _label, _imp, _exp in _FORMATS:
    # Skip step.export — already registered by v1_passthrough as the v1 wrapper.
    if _slug != "step":
        registry.register(
            verb="io", kind=f"{_slug}.export",
            description=f"Export named objects to a {_label} file at 'path'.",
            params_schema={"names": "list[str]", "path": "str", "doc": "str?"},
            execute=_exp,
            preflight=required_str("path"),
        )
    registry.register(
        verb="io", kind=f"{_slug}.import",
        description=f"Import a {_label} file from 'path' into the active document.",
        params_schema={"path": "str", "doc": "str?"},
        execute=_imp,
        preflight=required_str("path"),
    )
