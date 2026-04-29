
# Slot geometry convention

When building **obround slots** (width × length where the ends are
half-circles of diameter = width), use this convention so the verifier
matches:

- ``width`` = slot width = 2 × end-cap radius
- ``length`` = **total** slot span end-to-end (the bounding extent along
  the slot's long axis), **not** the center-to-center separation
- The two end-cap centers are therefore separated by ``length - width``

Example: an obround slot 8 mm wide × 25 mm long has end-cap centers
17 mm apart. The verifier query ``slots width=8 length=25`` will find it.
If you place end-caps 25 mm apart you've actually built a 33 mm slot;
the verifier will return ``count=0`` because the geometry doesn't match
the requested length.

