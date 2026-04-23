#!/usr/bin/env bash
# Run the v2 verb harness under FreeCADCmd.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FC_HOME="${CADAGENT_FC_HOME:-$HERE/.fc-home}"
mkdir -p "$FC_HOME/.local/share" "$FC_HOME/.config"

FC_BIN="$HERE/build/debug/bin/FreeCADCmd"
if [[ ! -x "$FC_BIN" ]]; then
    echo "FreeCADCmd not found at $FC_BIN — run 'pixi run build-debug' first." >&2
    exit 1
fi

# Prefer source tree so edits are picked up without a rebuild; fall back to
# the built copy if src isn't present (e.g. packaged install).
MOD_DIR="$HERE/src/Mod/CADAgent"
if [[ ! -d "$MOD_DIR" ]]; then
    MOD_DIR="$HERE/build/debug/Mod/CADAgent"
fi

exec env \
    HOME="$FC_HOME" \
    XDG_DATA_HOME="$FC_HOME/.local/share" \
    XDG_CONFIG_HOME="$FC_HOME/.config" \
    "$FC_BIN" -c "
import sys
sys.path.insert(0, '$MOD_DIR')
sys.path.insert(0, '$HERE/scripts')
import harness_v2
raise SystemExit(harness_v2.main())
"
