# Error recipes

- ``Application unexpectedly terminated`` (no other output): almost
  always a syntax/import error inside a ``-c`` invocation. Switch to the
  script-file pattern.
- ``FreeCADCmd`` exits 0 but you see ``Exception while processing
  file: ... [<msg>]`` on stderr: your script didn't use the try/except
  wrapper. Add it; re-run.
- ``<OSError>: File '...' does not exist``: a previous step didn't save.
  Check its ``RESULT`` line and the filesystem.
- ``sk.solve() < 0``: over-constrained. Remove the most recent
  constraint and re-solve. Don't add another to "cancel it out."
- ``not sk.FullyConstrained``: under-constrained. Add the fewest
  constraints needed (coincident > horizontal/vertical > distance >
  radius). DoF=0 is required before padding.
- ``pad.Shape.isValid() == False``: inspect the sketch — usually an
  open profile, self-intersection, or a zero-length edge. Fix upstream.

