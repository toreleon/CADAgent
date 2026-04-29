# Validity is non-negotiable

Every mutating script must end with ``assert shape.isValid(), "..."``
on the produced ``Part::Feature``. The auto-probe also reports
``invalid=[name, ...]`` in its summary line; if it ever shows your
final feature in that list, the boolean sequence produced a malformed
solid and you must fix it. Saving an invalid Cruciform is failure even
if the bbox and counts look right — invalid solids cannot be exported,
meshed, or inspected reliably.

