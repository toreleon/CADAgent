#!/usr/bin/env bash
# Phase 1 spike — answer three questions about the FreeCADCmd subprocess
# contract before committing to Option A (Bash + FreeCADCmd).
#
# Run from repo root:  bash scripts/spike/freecadcmd_spike.sh

set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

FC="$ROOT/build/debug/bin/FreeCADCmd"
[[ -x "$FC" ]] || { echo "ERROR: $FC not built"; exit 2; }

HOME_DIR="$ROOT/.fc-home"
mkdir -p "$HOME_DIR/.local/share" "$HOME_DIR/.config" "$HOME_DIR/spike"
SCRATCH="$HOME_DIR/spike"

export HOME="$HOME_DIR"
export XDG_DATA_HOME="$HOME_DIR/.local/share"
export XDG_CONFIG_HOME="$HOME_DIR/.config"
run_fc() {
    "$FC" "$@"
}

hr() { printf '\n=== %s ===\n' "$1"; }

# ---------------------------------------------------------------------------
# Q1 — startup cost (5 cold starts, inline -c for minimum overhead)
# ---------------------------------------------------------------------------
hr "Q1: cold-start cost"
for i in 1 2 3 4 5; do
    s=$(python3 -c 'import time; print(time.monotonic())')
    run_fc -c "import FreeCAD" >/dev/null 2>&1
    e=$(python3 -c 'import time; print(time.monotonic())')
    python3 -c "print(f'  run {$i}: {$e - $s:.3f}s')"
done

# ---------------------------------------------------------------------------
# Q2 — document round-trip via script files + env-var params.
#
# NB: ``FreeCADCmd -c '...'`` is unreliable: shell quoting of larger scripts
# triggers SIGBUS on syntax errors, and multi-line scripts can die before any
# stdout flush. Write the script to a file and invoke ``FreeCADCmd script.py``
# with env-var parameters. Extra argv are treated as additional files to open,
# NOT as ``sys.argv`` — env is the only reliable channel.
# ---------------------------------------------------------------------------
hr "Q2a: create body+sketch+pad, save FCStd + STEP"
cat > "$SCRATCH/mk.py" <<'PY'
import FreeCAD, Part, Sketcher, Import, os, json
doc = FreeCAD.newDocument('T')
body = doc.addObject('PartDesign::Body', 'Body')
xy = [f for f in body.Origin.OutList if f.Name.startswith('XY')][0]
sk = body.newObject('Sketcher::SketchObject', 'Sketch')
sk.AttachmentSupport = (xy, [''])
sk.MapMode = 'FlatFace'
doc.recompute()
for a,b in [((0,0,0),(10,0,0)),((10,0,0),(10,10,0)),((10,10,0),(0,10,0)),((0,10,0),(0,0,0))]:
    sk.addGeometry(Part.LineSegment(FreeCAD.Vector(*a), FreeCAD.Vector(*b)), False)
for c in [Sketcher.Constraint('Coincident',0,2,1,1),Sketcher.Constraint('Coincident',1,2,2,1),
          Sketcher.Constraint('Coincident',2,2,3,1),Sketcher.Constraint('Coincident',3,2,0,1),
          Sketcher.Constraint('Horizontal',0),Sketcher.Constraint('Horizontal',2),
          Sketcher.Constraint('Vertical',1),Sketcher.Constraint('Vertical',3),
          Sketcher.Constraint('DistanceX',0,1,0,2,10.0),Sketcher.Constraint('DistanceY',1,1,1,2,10.0),
          Sketcher.Constraint('DistanceX',-1,1,0,1,0.0),Sketcher.Constraint('DistanceY',-1,1,0,1,0.0)]:
    sk.addConstraint(c)
doc.recompute()
pad = body.newObject('PartDesign::Pad','Pad')
pad.Profile = sk; pad.Length = 5.0
doc.recompute()
doc.saveAs(os.environ['FC_DOC'])
Import.export([pad], os.environ['FC_STEP'])
print('RESULT:' + json.dumps({'valid':pad.Shape.isValid(),'vol':pad.Shape.Volume}))
PY
s=$(python3 -c 'import time; print(time.monotonic())')
FC_DOC="$SCRATCH/pd.FCStd" FC_STEP="$SCRATCH/pd.step" run_fc "$SCRATCH/mk.py" 2>&1 \
    | grep -E "^(RESULT|Traceback|<class|<Exception)" | head -3
e=$(python3 -c 'import time; print(time.monotonic())')
python3 -c "print(f'  elapsed: {$e - $s:.3f}s')"
ls -la "$SCRATCH/pd.FCStd" "$SCRATCH/pd.step" 2>&1 | awk '{print "  ",$9,$5,"bytes"}'

hr "Q2b: reopen in a fresh subprocess, verify geometry"
cat > "$SCRATCH/reopen.py" <<'PY'
import FreeCAD, os, json
doc = FreeCAD.open(os.environ['FC_DOC'])
pad = doc.getObject('Pad')
print('RESULT:' + json.dumps({
    'objects': [o.Name for o in doc.Objects],
    'valid': pad.Shape.isValid(),
    'bbox': [pad.Shape.BoundBox.XLength, pad.Shape.BoundBox.YLength, pad.Shape.BoundBox.ZLength],
}))
PY
s=$(python3 -c 'import time; print(time.monotonic())')
FC_DOC="$SCRATCH/pd.FCStd" run_fc "$SCRATCH/reopen.py" 2>&1 \
    | grep -E "^(RESULT|Traceback|<class)" | head -3
e=$(python3 -c 'import time; print(time.monotonic())')
python3 -c "print(f'  elapsed: {$e - $s:.3f}s')"

# ---------------------------------------------------------------------------
# Q3 — error reporting
# ---------------------------------------------------------------------------
hr "Q3a: unhandled Python exception → exit code + stderr"
cat > "$SCRATCH/boom.py" <<'PY'
import FreeCAD
raise ValueError('spike_test_error')
PY
run_fc "$SCRATCH/boom.py" > /tmp/out.txt 2> /tmp/err.txt
echo "  exit: $?"
echo "  stderr:"; head -6 /tmp/err.txt | sed 's/^/    /'

hr "Q3b: sys.exit(7) propagates"
cat > "$SCRATCH/exit7.py" <<'PY'
import sys; sys.exit(7)
PY
run_fc "$SCRATCH/exit7.py" >/dev/null 2>&1
echo "  exit: $?"

hr "Q3c: syntax error in script file → clean exit, traceback on stderr"
cat > "$SCRATCH/syntax.py" <<'PY'
this is not (valid python
PY
run_fc "$SCRATCH/syntax.py" > /tmp/out.txt 2> /tmp/err.txt
echo "  exit: $?"
echo "  stderr:"; head -4 /tmp/err.txt | sed 's/^/    /'

hr "Q3d: over-constrained sketch → Python-level error?"
cat > "$SCRATCH/overcon.py" <<'PY'
import FreeCAD, Part, Sketcher, json
doc = FreeCAD.newDocument('O')
sk = doc.addObject('Sketcher::SketchObject','S')
sk.addGeometry(Part.LineSegment(FreeCAD.Vector(0,0,0), FreeCAD.Vector(10,0,0)), False)
sk.addConstraint(Sketcher.Constraint('DistanceX', 0,1, 0,2, 10.0))
try:
    sk.addConstraint(Sketcher.Constraint('DistanceX', 0,1, 0,2, 20.0))
    doc.recompute()
    print('RESULT:' + json.dumps({'solve': sk.solve(), 'msg': sk.MalformedConstraints if hasattr(sk,'MalformedConstraints') else None}))
except Exception as e:
    print('RESULT_ERR:' + repr(e))
PY
run_fc "$SCRATCH/overcon.py" 2>&1 | grep -E "^(RESULT|Traceback|<class)" | head -3

hr "DONE"
echo "Scratch: $SCRATCH"
