"""Generate the .FCStd fixtures consumed by the CADAgent test harness.

Run via FreeCADCmd (standalone or as a pytest session fixture)::

    FreeCADCmd -c "exec(open('.../tests/cadagent/fixtures/make_fixtures.py').read())"

Idempotent: existing files are left alone unless ``CADAGENT_REGEN_FIXTURES=1``.

Fixtures produced:

- ``empty.FCStd``              — saved-but-empty doc; no Body, no geometry.
- ``one_body_one_sketch.FCStd`` — PartDesign Body with one unconstrained sketch;
                                   useful for "agent must constrain before padding" tests.
- ``pad_on_rect.FCStd``         — Body with a 50x30 rectangular sketch padded 5 mm.
                                   Plate geometry used as the base for corner-holes tests.
"""

from __future__ import annotations

import os
import sys

import FreeCAD as App
import Sketcher  # noqa: F401  # activates Sketcher module
import Part  # noqa: F401

# When loaded via ``FreeCADCmd -c "exec(open(...).read())"``, __file__ is not
# defined. Fall back to an env var the harness sets; if neither is available,
# default to the fixtures dir relative to the repo.
HERE = (
    os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals()
    else os.environ.get("CADAGENT_FIXTURES_DIR")
    or os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "tests", "cadagent", "fixtures")
)


def _save(doc, name: str) -> str:
    path = os.path.join(HERE, f"{name}.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    return path


def _skip(name: str) -> bool:
    path = os.path.join(HERE, f"{name}.FCStd")
    if not os.path.exists(path):
        return False
    if os.environ.get("CADAGENT_REGEN_FIXTURES"):
        return False
    return True


def make_empty() -> str | None:
    if _skip("empty"):
        return None
    doc = App.newDocument("empty")
    doc.recompute()
    return _save(doc, "empty")


def make_one_body_one_sketch() -> str | None:
    if _skip("one_body_one_sketch"):
        return None
    doc = App.newDocument("one_body_one_sketch")
    body = doc.addObject("PartDesign::Body", "Body")
    sketch = doc.addObject("Sketcher::SketchObject", "Sketch")
    xy_plane = next(o for o in body.Origin.OutList if "XY_Plane" in (o.Name, o.Label))
    sketch.AttachmentSupport = (xy_plane, [""])
    sketch.MapMode = "FlatFace"
    body.addObject(sketch)
    # Unconstrained triangle — three edges, no dimensional constraints.
    from FreeCAD import Vector
    sketch.addGeometry(Part.LineSegment(Vector(0, 0, 0), Vector(20, 0, 0)), False)
    sketch.addGeometry(Part.LineSegment(Vector(20, 0, 0), Vector(10, 15, 0)), False)
    sketch.addGeometry(Part.LineSegment(Vector(10, 15, 0), Vector(0, 0, 0)), False)
    doc.recompute()
    return _save(doc, "one_body_one_sketch")


def make_pad_on_rect() -> str | None:
    if _skip("pad_on_rect"):
        return None
    doc = App.newDocument("pad_on_rect")
    body = doc.addObject("PartDesign::Body", "Body")
    sketch = doc.addObject("Sketcher::SketchObject", "Sketch")
    xy_plane = next(o for o in body.Origin.OutList if "XY_Plane" in (o.Name, o.Label))
    sketch.AttachmentSupport = (xy_plane, [""])
    sketch.MapMode = "FlatFace"
    body.addObject(sketch)
    from FreeCAD import Vector
    # 50 x 30 rectangle centred at origin
    p = [Vector(-25, -15, 0), Vector(25, -15, 0), Vector(25, 15, 0), Vector(-25, 15, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]), False)
    doc.recompute()

    pad = doc.addObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Length = 5.0
    body.addObject(pad)
    doc.recompute()
    return _save(doc, "pad_on_rect")


def main() -> int:
    made = []
    for fn in (make_empty, make_one_body_one_sketch, make_pad_on_rect):
        try:
            path = fn()
            if path:
                made.append(path)
        except Exception as exc:
            sys.stderr.write(f"[fixtures] {fn.__name__} failed: {exc}\n")
            return 1
    for p in made:
        sys.stdout.write(f"[fixtures] wrote {p}\n")
    if not made:
        sys.stdout.write("[fixtures] all fixtures already present\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
