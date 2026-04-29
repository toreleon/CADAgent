# FreeCAD API landmines (learned from the spike, not obvious from the API)

- **Filleting raw ``Part::Feature`` solids — use ``Shape.makeFillet``,
  NOT ``PartDesign::Fillet``.** Three runs in a row burned the retry
  budget on
  ``fillet.Edges = [(feature, ["Edge1", ...])]`` errors. That syntax
  is for ``PartDesign::Fillet`` *inside a Body* — not for the raw
  ``Part::Feature`` flow this cookbook uses. The correct pattern:
  ```python
  edges = [e for e in solid.Shape.Edges if <selection criterion>]
  filleted = solid.Shape.makeFillet(R, edges)
  out = doc.addObject("Part::Feature", "filleted")
  out.Shape = filleted
  ```
  ``makeFillet`` takes ``(radius, list_of_TopoShape_edges)`` directly
  — no ``(feature, ["EdgeN"])`` tuples. If you ever find yourself
  setting an ``.Edges`` attribute on a fillet object, you are on the
  wrong path; switch to ``makeFillet``.
- **STEP / IGES export from FreeCADCmd uses ``Import``, not
  ``ImportGui``.** ``import ImportGui`` raises
  ``Cannot load Gui module in console application`` and burns a retry.
  The console-safe pattern:
  ```python
  import Import  # not ImportGui
  Import.export([obj], "/abs/path/to/out.step")
  ```
- ``doc.getObject("XY_Plane")`` returns ``None``. Origin planes live
  under the Body. Use:
  ```python
  xy = [f for f in body.Origin.OutList if f.Name.startswith("XY")][0]
  ```
- ``Sketcher::SketchObject.AttachmentSupport = (xy, [""])`` then
  ``sk.MapMode = "FlatFace"`` — you need both.
- ``sk.solve()`` returns 0 on a good solve, negative on conflict (−3 =
  over-constrained). It does NOT return DoF; ``sk.FullyConstrained``
  does (bool).
- ``PartDesign::Pad.Type = 1`` means "ThroughAll" — set ``Type`` OR
  ``Length``, not both semantics at once.
- Edge references are ``(feature, ["Edge1", "Edge2"])`` — strings, 1-based
  indices, all edges must belong to the same feature.
- ``pad.Shape.isValid()`` is the ground truth for "did it work." A
  recompute can "succeed" and still produce an invalid shape.

