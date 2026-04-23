# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sheet Metal workbench provider — relies on the SheetMetalWorkbench addon.

The Sheet Metal workbench is a community addon (not in core FreeCAD), so
its Python module name varies by install. We try the canonical
``SheetMetalCmd`` and ``SheetMetalBend`` paths and surface a clear error
if the user's install doesn't have the addon — they'll need to install it
via Addon Manager before these kinds will work.
"""

from __future__ import annotations

import FreeCAD as App

from .. import registry
from ..registry import required_str, positive_number, chain


def _import_sm():
    try:
        import SheetMetalCmd  # type: ignore
        import SheetMetalBend  # type: ignore
        import SheetMetalUnfolder  # type: ignore
        return SheetMetalCmd, SheetMetalBend, SheetMetalUnfolder
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "SheetMetalWorkbench addon not installed. Install via Addon "
            "Manager or fall back to cad_exec for sheet-metal operations."
        ) from exc


def _make_base(doc, params: dict):
    SMC, _, _ = _import_sm()
    sketch = doc.getObject(params["sketch"])
    if sketch is None:
        raise ValueError(f"sketch {params['sketch']!r} not found")
    thickness = float(params["thickness"])
    obj = SMC.SMBaseShape(sketch, thickness)  # API name from SheetMetalCmd
    doc.recompute()
    return obj


def _make_flange(doc, params: dict):
    _, SMB, _ = _import_sm()
    base = doc.getObject(params["base"])
    if base is None:
        raise ValueError(f"base {params['base']!r} not found")
    edges = list(params["edges"])  # list of "Feature.Edge1" strings
    length = float(params["length"])
    angle = float(params.get("angle", 90.0))
    obj = SMB.SMBendWall(base, edges, length, angle)
    doc.recompute()
    return obj


def _make_unfold(doc, params: dict):
    _, _, SMU = _import_sm()
    base = doc.getObject(params["base"])
    if base is None:
        raise ValueError(f"base {params['base']!r} not found")
    face = params.get("face", "Face1")
    k_factor = float(params.get("k_factor", 0.5))
    obj = SMU.SMUnfold(base, face, k_factor)
    doc.recompute()
    return obj


registry.register(
    verb="create", kind="sm.base",
    description="Sheet metal base from a closed sketch + thickness (mm).",
    params_schema={"sketch": "str", "thickness": "float"},
    execute=_make_base,
    preflight=chain(required_str("sketch"), positive_number("thickness")),
)

registry.register(
    verb="create", kind="sm.flange",
    description="Add a sheet-metal flange (bent wall) on edges of an existing base; length + angle.",
    params_schema={"base": "str", "edges": "list[str]", "length": "float", "angle": "float?"},
    execute=_make_flange,
    preflight=chain(required_str("base"), positive_number("length")),
)

registry.register(
    verb="create", kind="sm.unfold",
    description="Unfold a sheet-metal part to its flat pattern; pick the stationary face and k-factor.",
    params_schema={"base": "str", "face": "str?", "k_factor": "float?"},
    execute=_make_unfold,
    preflight=required_str("base"),
)
