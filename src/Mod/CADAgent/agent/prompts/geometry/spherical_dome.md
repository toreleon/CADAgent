## Spherical cap dome (intersect, do not fuse)

```python
# Apex at z=h_total, base at z=0, sphere radius R_dome.
sphere = Part.makeSphere(R_dome, FreeCAD.Vector(0, 0, h_total - R_dome))
# Intersect (NOT fuse) with the body extruded tall — the cap is what's left
# above z=0 inside the sphere.
body_extruded = footprint.extrude(FreeCAD.Vector(0, 0, h_total + 1))
domed_body = body_extruded.common(sphere)  # 'common' == intersection
```

Don't fuse a sphere onto the body — that adds a ball, not a cap. Use
``common`` (intersection).

