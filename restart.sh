#!/usr/bin/env bash
# Restart FreeCAD (debug build) with a redirected HOME so config/data writes
# land in the repo-local sandbox.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_HOME="${REPO_ROOT}/.fc-home"
FC_BIN="${REPO_ROOT}/build/debug/bin/FreeCAD"

mkdir -p "${FC_HOME}/.local/share" "${FC_HOME}/.config"

# Keep the build tree in sync with src/ before launching so we never run
# against a stale copy of the CADAgent Python module.
PIXI_BIN="$(command -v pixi || echo /home/tore/.pixi/bin/pixi)"
BUILD_DIR="${REPO_ROOT}/build/debug"

# Reconfigure if the build tree is missing or stale. `ninja: error ...
# loading 'CMakeFiles/rules.ninja'` means the generator was interrupted
# or the dir was partially wiped — only a fresh configure recovers it.
needs_configure=0
if [[ ! -f "${BUILD_DIR}/build.ninja" && ! -f "${BUILD_DIR}/Makefile" ]]; then
    needs_configure=1
elif [[ -f "${BUILD_DIR}/build.ninja" && ! -f "${BUILD_DIR}/CMakeFiles/rules.ninja" ]]; then
    needs_configure=1
fi

if [[ -x "${PIXI_BIN}" ]]; then
    if [[ "${needs_configure}" -eq 1 ]]; then
        # Pin both Python and Python3 to the pixi env python. CMake's
        # FindPython{,3} otherwise picks the highest system version on
        # PATH (e.g. /usr/bin/python3.12), which lacks pivy (breaks
        # SetupCoin3D) and mismatches Shiboken6's build-time 3.11 ABI.
        # The configure-debug task only accepts one {{ extra_args }} token,
        # which isn't enough to pin both Python and Python3. Invoke cmake
        # directly inside the pixi env (matches the preset + the task's
        # CFLAG-clearing env overrides) so we can pass multiple -D flags.
        PY="${REPO_ROOT}/.pixi/envs/default/bin/python"
        "${PIXI_BIN}" run --manifest-path "${REPO_ROOT}/pixi.toml" -- \
            env CFLAGS= CXXFLAGS= DEBUG_CFLAGS= DEBUG_CXXFLAGS= \
            cmake --preset conda-linux-debug \
                "-DPython3_EXECUTABLE=${PY}" \
                "-DPython_EXECUTABLE=${PY}"
    fi
    "${PIXI_BIN}" run build-debug
else
    if [[ "${needs_configure}" -eq 1 ]]; then
        echo "restart.sh: build dir is missing/stale and pixi is unavailable; cannot auto-configure." >&2
        exit 1
    fi
    cmake --build "${BUILD_DIR}"
fi

pkill -f "${FC_BIN}" 2>/dev/null || true
sleep 1

exec env \
    HOME="${FC_HOME}" \
    XDG_DATA_HOME="${FC_HOME}/.local/share" \
    XDG_CONFIG_HOME="${FC_HOME}/.config" \
    "${FC_BIN}" "$@"
