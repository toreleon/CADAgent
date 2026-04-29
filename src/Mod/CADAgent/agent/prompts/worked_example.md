# Worked example — body + rectangular sketch + pad + STEP export

```python
import FreeCAD, Part, Sketcher, Import, os, json, sys, traceback
try:
    W, H, D = 10.0, 10.0, 5.0
    out = os.environ["FC_DOC"]

    doc = FreeCAD.newDocument("Part")
    body = doc.addObject("PartDesign::Body", "Body")
    xy = [f for f in body.Origin.OutList if f.Name.startswith("XY")][0]

    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = (xy, [""])
    sk.MapMode = "FlatFace"
    doc.recompute()

    # Four corners of a rectangle at the origin.
    for a, b in [((0,0,0),(W,0,0)),((W,0,0),(W,H,0)),
                 ((W,H,0),(0,H,0)),((0,H,0),(0,0,0))]:
        sk.addGeometry(Part.LineSegment(FreeCAD.Vector(*a), FreeCAD.Vector(*b)), False)
    for i in range(4):  # corner coincidences
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", 1))
    sk.addConstraint(Sketcher.Constraint("Vertical", 3))
    sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, W))
    sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, H))
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, 0.0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, 0.0))
    doc.recompute()
    assert sk.solve() == 0 and sk.FullyConstrained, f"sketch solve={sk.solve()}"

    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sk
    pad.Length = D
    doc.recompute()
    assert pad.Shape.isValid(), "pad shape invalid"

    doc.saveAs(out)
    if os.environ.get("FC_STEP"):
        Import.export([pad], os.environ["FC_STEP"])
    print("RESULT:" + json.dumps({
        "ok": True, "doc": out, "pad": pad.Name,
        "volume": pad.Shape.Volume,
        "bbox": [pad.Shape.BoundBox.XLength, pad.Shape.BoundBox.YLength, pad.Shape.BoundBox.ZLength],
    }))
except BaseException as e:
    sys.stderr.write("ERROR:" + json.dumps({
        "type": type(e).__name__, "message": str(e),
        "traceback": traceback.format_exc(limit=8),
    }) + "\n")
    sys.exit(1)
```

Typical timings from the spike: cold start ~0.3s, this whole script ~1.8s.

