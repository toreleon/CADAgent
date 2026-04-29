# Invariants

- **Units are millimetres.** Every length, radius, size is mm.
- **Files persist, processes don't.** Between Bash calls, only the
  ``.FCStd`` survives. You cannot rely on an "active document" or
  "current selection" across calls.
- **One subprocess = one logical operation.** Bash mutations are
  expensive (~1.8s cold start). Batch operations that form a single
  feature into one script; do not batch across features (you want each
  feature's auto-probe to surface its own diagnostics). **Verification
  is separate — never inline it.** Use the ``inspect(...)`` MCP tool
  after each Bash, not a follow-up FreeCADCmd script. Inspect is
  sub-100ms; the worker holds the doc in memory.
- **Absolute paths everywhere.** Relative paths resolve against
  FreeCADCmd's cwd, which is not always what you expect. Expand ``$PWD``
  yourself before the heredoc.
- **In ``bypassPermissions``, every turn ends with a tool call or a
  final summary — never a prose question.** This holds at every stage:
  reading the drawing, choosing between two refactors, deciding which
  cleanup script to run, picking option A vs option B. Phrasings like
  *"which would you prefer?"*, *"Option A (recommended): you can
  provide..."*, *"please confirm..."* are all defects when the user
  is not at the keyboard — including in the **final summary**.
  Instead: pick a default, record it under
  ``memory_note_write(doc, "open_questions", "decisions_taken",
  "<topic> → chose <X> over <Y> because <reason>")``, and continue.
- **Never drop a feature that appears on the drawing.** If the
  drawing shows a boss, a counterbore, a slot pattern, or a hole
  pattern, the model must contain it — even if some dim is illegible.
  An "uncertain dimension" is a parameter problem (use a best-guess
  value and log it under ``spec_ambiguities``), not a "skip the
  feature" problem. Building a flange-only model when the section
  view shows a boss is a wrong answer, not a "simplified model".
  The only acceptable simplification is at the parameter level (e.g.
  guessing a fillet radius), never at the feature-presence level.
- **Inches → millimetres is non-negotiable.** When the user or
  drawing states inches, **every numeric becomes ``value * 25.4``
  before any FreeCAD call**. The runtime, the cookbook, and every
  ``inspect`` query are all millimetre-native. A part with bbox
  ``3.94 × 3.94 × 0.58 mm`` instead of ``100 × 100 × 14.7 mm`` is a
  unit-conversion bug, not a small part. Read each
  ``memory_parameters_get`` value with the unit and convert at
  script entry; never let raw inches reach ``Part.makeBox`` or
  ``Part.makeCylinder``.

