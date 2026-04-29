## Obround slot, axis along Z, cut-through

```python
def make_obround_z(center_x, center_y, width, length, height):
    # Solid that, when subtracted from a body, leaves an obround through-cut.
    # width = slot width (= 2 * end-cap radius)
    # length = TOTAL slot span end-to-end
    # height = how tall the cutter is (>= part height + slack on both ends)
    half_sep = (length - width) / 2.0  # end-cap centers offset from slot center
    r = width / 2.0
    z0 = -height / 2.0  # cutter spans -h/2..+h/2 around z=0; translate later if needed
    # Two end-cap cylinders + connecting rectangular prism (oriented along X).
    cyl_a = Part.makeCylinder(r, height, FreeCAD.Vector(-half_sep, 0, z0))
    cyl_b = Part.makeCylinder(r, height, FreeCAD.Vector( half_sep, 0, z0))
    rect  = Part.makeBox(2 * half_sep, width, height,
                         FreeCAD.Vector(-half_sep, -r, z0))
    cutter = cyl_a.fuse(cyl_b).fuse(rect)
    cutter.translate(FreeCAD.Vector(center_x, center_y, 0))
    return cutter

# For a slot whose long axis is along Y instead of X, build it along X first
# then rotate by 90° about Z BEFORE translating to (center_x, center_y).
slot = make_obround_z(0, 0, width=8, length=20, height=200)
slot.Placement.Rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)
slot.Placement.Base = FreeCAD.Vector(center_x, center_y, 0)
```

The verifier finds these as ``slots width=8 length=20``. Watch the
length convention — the verifier matches the **total** span, not the
end-cap separation.

