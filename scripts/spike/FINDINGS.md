# Phase 1 spike — FreeCADCmd subprocess contract

Run: `bash scripts/spike/freecadcmd_spike.sh`

## Go/no-go: **GO**, with two constraints that shape the Phase 2 design.

## Measurements (macOS, Darwin arm64, debug build)

| Operation | Time |
|---|---|
| Cold start (`import FreeCAD`) | 0.27s median (first run 0.88s — OS cache warm-up) |
| Create Body + Sketch (DoF=0) + Pad + save .FCStd + export STEP | **1.76s** |
| Reopen .FCStd + inspect | **1.05s** |

A typical mutation cycle therefore costs ~1–2s wall-clock. The old in-process
verb surface was ~ms. For the agent this means: expect a ~10× slowdown on
turns with many small operations; batch work per subprocess where possible.

## Round-trip works

Create → save .FCStd → exit → new subprocess → `FreeCAD.open()` → inspect:
bbox and volume match exactly (10 × 10 × 5 mm, volume 500 mm³).
`PartDesign::Body` + `Sketcher::SketchObject` + `PartDesign::Pad` survive
the file boundary. STEP export (6789 bytes) succeeds in the same subprocess.

## CONSTRAINT 1: script files + env vars, never `-c`, never argv

`FreeCADCmd -c "..."` is a footgun:
- Shell quoting of multi-line scripts is fragile.
- A Python syntax error inside `-c` **crashes the process with SIGBUS** (exit 138)
  rather than a clean error.
- Long scripts intermittently produce "Application unexpectedly terminated"
  before any stdout reaches the shell.

Running `FreeCADCmd /path/to/script.py` is robust: syntax errors and runtime
exceptions are caught and reported on stderr. Extra argv are interpreted as
additional files to open, **not** as `sys.argv` — so script parameters must
travel via environment variables.

Agent-visible implication: the `fcrun` wrapper writes the agent's Python to a
temp file, sets `FC_*` env vars for parameters, and invokes
`FreeCADCmd <tmpfile>`. The agent never touches `-c` directly.

## CONSTRAINT 2: FreeCADCmd swallows exceptions — exit 0 on failure

An unhandled exception in the script file produces:

```
stderr: Exception while processing file: /path/to/script.py [spike_test_error]
exit:   0
```

A syntax error produces:

```
stderr: Exception while processing file: /path/to/script.py
        [("'(' was never closed", ('.../syntax.py', 1, 13, ...))]
exit:   0
```

Explicit `sys.exit(N)` propagates correctly (tested with `sys.exit(7)` → exit 7).

Agent-visible implication: `fcrun` must either (a) wrap every script in a
harness that catches `Exception`, prints a structured JSON error line, and
calls `sys.exit(1)`, or (b) parse stderr for the `Exception while processing
file:` sentinel. Option (a) is cleaner and keeps the "success → exit 0,
failure → exit N + JSON" contract the shell expects.

## Subtler finding: operations that *would* crash under `-c` recover under script files

The over-constrained-sketch case (Q3d) that crashed the process with
"Application unexpectedly terminated" when run via `-c` returns cleanly as
`{"solve": -3, "msg": []}` when run from a script file. Likely related to
how `-c` drives the parser. Another reason to commit to the script-file path.

## What this means for the migration plan

- **Phase 2 (fcrun + snippet library) is on.** The plan's direction holds, and
  the "snippets over raw Python" bet is reinforced — the more we let the agent
  reuse known-good scripts, the less it gets burned by the two constraints
  above.
- **`fcrun` contract** (to build in Phase 2):
  - Input: path to a user Python file + env vars for parameters.
  - Wraps the user code in a try/except that catches `BaseException`, prints
    a JSON diagnostic on failure, and exits non-zero.
  - Sets `HOME`/`XDG_*` to the hermetic `.fc-home` tree from CLAUDE.md.
  - Forwards stdout (RESULT lines) to the caller.
- **No render path.** Confirmed: `FreeCADCmd` has no GUI / no offscreen view
  rendering. `cad_render` has no direct replacement. Either drop it (agent
  can tell user to open the .FCStd in GUI FreeCAD to inspect) or spawn a
  headless `FreeCAD` (GUI) with an X/offscreen context — out of scope for now.

## Artifacts

- `scripts/spike/freecadcmd_spike.sh` — reproducible timing + behaviour probe.
- `.fc-home/spike/pd.FCStd`, `.fc-home/spike/pd.step` — output of the
  round-trip test (9 KB / 7 KB respectively).
