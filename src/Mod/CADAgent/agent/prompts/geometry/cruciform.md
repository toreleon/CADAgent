## Cruciform footprint sized to envelope Ø D, arms width W, tip cap R

```python
def make_cruciform_footprint(D, W, R):
    # 2D-ish prismatic footprint solid (extrude later).
    # D = envelope diameter (arm tip cylinder OD touches this)
    # W = arm width
    # R = arm-tip half-disk radius (= W/2 for a clean obround tip)
    cap_center_r = D/2.0 - R   # so cap arc reaches D/2 exactly
    arm_h = 2 * cap_center_r   # full bar length tip-to-tip on the cap centers
    # +X arm: bar from x=-cap_center_r to x=+cap_center_r, width W centered on Y
    bar_x = Part.makeBox(arm_h + 2*R, W, 1,
                         FreeCAD.Vector(-cap_center_r - R, -W/2, 0))
    bar_y = Part.makeBox(W, arm_h + 2*R, 1,
                         FreeCAD.Vector(-W/2, -cap_center_r - R, 0))
    cross = bar_x.fuse(bar_y)
    return cross  # extrude this in Z; intersect with the dome separately
```

Setting ``cap_center_r = D/2 - R`` is what keeps the envelope at exactly D
(the tip cap arc reaches r = cap_center_r + R = D/2). If you center caps
at r = D/2 directly, the arc bulges out and the envelope ends up D + 2R.

