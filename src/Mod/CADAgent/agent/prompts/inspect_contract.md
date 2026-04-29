# Inspecting geometry — use the ``inspect`` MCP tool, not Bash

Verification is a structured query against a live, in-memory FreeCAD,
not a fresh FreeCADCmd subprocess. ``inspect(doc, query)`` returns JSON
in well under 100ms — call it freely.

Examples:
- ``inspect(doc, "bbox")`` — confirm the part envelope.
- ``inspect(doc, "solids")`` — every solid with ``{isValid, isClosed, n_faces, volume}``.
- ``inspect(doc, "face_types")`` — the surface census. ``Sphere=0`` after
  a step that was supposed to add a dome means a boolean silently
  degenerated. ``Torus=N`` is your fillet count.
- ``inspect(doc, "spheres radius=250")`` — find the dome face explicitly.
- ``inspect(doc, "slots width=8 length=20")`` — count obround through-cuts.
- ``inspect(doc, "holes diameter=15 axis=z")`` — count cylindrical
  through-holes (note: a slot's two end-caps each look like a hole of
  diameter=width — cross-check counts with ``slots`` if you've cut both).

## The auto-probe (you'll see this without asking)

After every ``Bash`` tool call that mutates the .FCStd, the runtime
appends one ``[auto-probe] {...}`` line to the next tool result.
The probe contains ``bbox``, ``face_types``, and ``solids`` in one shot.

**React to it.** If a step was supposed to add a dome and the probe
shows ``Sphere: 0``, you have a problem — diagnose before continuing.
If ``solids[].isValid`` is false, fix the underlying boolean (don't
just save and pretend). The auto-probe is your floor; richer questions
go through ``inspect(...)``.

