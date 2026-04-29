## Two-view drawing → 3D part — flange + boss stack-up

Engineering drawings nearly always show **a top view (the outer
silhouette + cuts) and a side / sectional view (the Z stack-up).**
A flat plate built from the top view alone is wrong whenever the side
view shows more than one Z-level. **Read both views before you pad.**

The recipe — apply this whenever the side view shows steps, a boss, a
flange, a counterbore, or any non-uniform thickness:

1. **Decompose the side view into a Z stack.** Each horizontal segment
   in the section view is a Z-band with its own footprint. Typical
   stacks: ``[flange] + [boss]``, ``[flange] + [hub] + [pilot]``,
   ``[base] + [recess pocket]``. Read the dimensions on the section
   view, not just the top view.
2. **Per band, identify its footprint.** The flange usually inherits
   the outer top-view profile. The boss is a smaller concentric (or
   offset) footprint whose plan view is somewhere on the top view —
   often a circle or rounded square *inside* the flange outline.
3. **Build each band as its own ``Part::Feature``** named after its
   role (``flange``, ``boss``, ``recess_cutter``), padded only as tall
   as that band, translated to the correct Z. Then ``fuse`` the
   positive bands and ``cut`` the negative ones.
4. **Holes go LAST**, after the fused stack — so a through-hole in
   the boss also passes through the flange.

```python
# Two-band example: a 3.94×3.94×0.58 in flange with a Ø2.00 in boss
# rising 2.00 in above it (matches the tube-holder section view).
import Part, FreeCAD
mm = 25.4
W = 3.94 * mm; T_flange = 0.58 * mm
D_boss = 2.00 * mm; H_boss = 2.00 * mm
R_corner = 0.50 * mm  # 4× corner fillets

# Band 1 — flange: rounded-square plate from z=0 to z=T_flange.
flange_profile = Part.makePlane(W, W, FreeCAD.Vector(-W/2, -W/2, 0))
flange = flange_profile.extrude(FreeCAD.Vector(0, 0, T_flange))
# (corner fillets applied after fuse — fillet operates on edges of the
# final solid, not the profile, to avoid filleting hidden interior edges.)

# Band 2 — boss: cylinder concentric with the plate, sitting ON the flange.
boss = Part.makeCylinder(D_boss/2, H_boss, FreeCAD.Vector(0, 0, T_flange))

# Positive stack: union the two bands.
body = flange.fuse(boss)

# Corner fillets — only the 4 vertical edges of the flange.
flange_corners = [e for e in body.Edges
                  if abs(e.Length - T_flange) < 1e-3
                  and abs(abs(e.firstVertex().Point.x) - W/2) < 1e-3
                  and abs(abs(e.firstVertex().Point.y) - W/2) < 1e-3]
body = body.makeFillet(R_corner, flange_corners)

# Holes (negative bands) — through-cuts go AFTER the positive stack so
# they pierce both flange and boss when the geometry calls for it.
center_hole = Part.makeCylinder(1.83/2*mm, T_flange + H_boss + 1,
                                FreeCAD.Vector(0, 0, -0.5))
body = body.cut(center_hole)
```

The two failure modes this prevents:

- **Single-extrusion bug.** If you skip step 1 you get a flat plate at
  the flange thickness; the boss height in the side view is silently
  ignored. Cheap to detect: ``inspect(doc, "bbox")`` shows
  ``Z = T_flange`` instead of ``T_flange + H_boss``.
- **Filleting too early.** Running ``makeFillet`` on the flange before
  fusing the boss rounds the *top* edge where the boss will sit, and
  the boss-flange intersection comes out scarred. Always fuse first,
  fillet last.

Pair this with a per-band ``memory_parameter_set(verify=...)``:
``T_flange=14.732 verify="bbox of flange"`` and
``H_boss=50.8 verify="bbox of boss"`` — the auto-probe will catch a
missing band before final inspect.

