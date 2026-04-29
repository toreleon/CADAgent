### Why the try/except is non-negotiable

FreeCADCmd catches unhandled Python exceptions and **exits 0**, with only
a ``Exception while processing file: ...`` line on stderr. Without the
try/except wrapper, you cannot distinguish success from silent failure.
Every script you write ends with that wrapper. No exceptions.

### Why the env vars

``HOME``/``XDG_*`` redirect FreeCAD's config writes into the repo-local
``.fc-home`` so runs are hermetic. ``FC_DOC`` (and any other ``FC_*`` you
define) is how you pass parameters — read them with
``os.environ["FC_DOC"]``.

