# SPDX-License-Identifier: LGPL-2.1-or-later
"""TechDraw workbench provider — create drawing pages and views."""

from __future__ import annotations

import FreeCAD as App

from .. import registry
from ..registry import required_str, positive_number


def _make_page(doc, params: dict):
    import TechDraw  # type: ignore
    template = params.get("template", "A4_Landscape_ISO7200TD.svg")
    page = doc.addObject("TechDraw::DrawPage", params.get("label") or "Page")
    tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    # Template path — rely on FreeCAD's default template dir:
    tpl.Template = App.getResourceDir() + "Mod/TechDraw/Templates/" + template
    page.Template = tpl
    doc.recompute()
    return page


def _make_view(doc, params: dict):
    import TechDraw  # type: ignore
    page = doc.getObject(params["page"])
    source = doc.getObject(params["source"])
    if page is None or source is None:
        raise ValueError("page and source must exist")
    view = doc.addObject("TechDraw::DrawViewPart", params.get("label") or "View")
    view.Source = [source]
    direction = params.get("direction", "Front")
    view.Direction = {
        "Front": App.Vector(0, -1, 0), "Top": App.Vector(0, 0, 1),
        "Right": App.Vector(1, 0, 0),  "Iso": App.Vector(1, -1, 1).normalize(),
    }.get(direction, App.Vector(0, -1, 0))
    view.Scale = float(params.get("scale", 1.0))
    page.addView(view)
    doc.recompute()
    return view


def _make_dimension(doc, params: dict):
    import TechDraw  # type: ignore
    view = doc.getObject(params["view"])
    if view is None:
        raise ValueError("view must exist")
    dim = doc.addObject("TechDraw::DrawViewDimension", "Dimension")
    dim.References2D = [(view, r) for r in params["refs"]]
    dim.Type = params.get("type", "Distance")
    view.Page.addView(dim)  # attach dim to the page
    doc.recompute()
    return dim


registry.register(
    verb="create", kind="td.page",
    description="Create a TechDraw page (template is an SVG filename from FreeCAD's templates dir).",
    params_schema={"template": "str?", "label": "str?"},
    execute=_make_page,
)

registry.register(
    verb="create", kind="td.view",
    description="Add a drawing view of a source object to a page. direction ∈ Front/Top/Right/Iso.",
    params_schema={"page": "str", "source": "str", "direction": "str?", "scale": "float?", "label": "str?"},
    execute=_make_view,
    preflight=required_str("page", "source"),
)

registry.register(
    verb="create", kind="td.dimension",
    description="Add a dimension to a view; refs is a list of subnames (e.g. ['Edge1','Edge2']).",
    params_schema={"view": "str", "refs": "list[str]", "type": "str?"},
    execute=_make_dimension,
    preflight=required_str("view"),
)
