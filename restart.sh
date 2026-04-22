#!/usr/bin/env bash
# Restart FreeCAD (debug build) with a redirected HOME so config/data writes
# land in the repo-local sandbox.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC_HOME="${REPO_ROOT}/.fc-home"
FC_BIN="${REPO_ROOT}/build/debug/bin/FreeCAD"

mkdir -p "${FC_HOME}/.local/share" "${FC_HOME}/.config"

pkill -f "${FC_BIN}" 2>/dev/null || true
sleep 1

exec env \
    HOME="${FC_HOME}" \
    XDG_DATA_HOME="${FC_HOME}/.local/share" \
    XDG_CONFIG_HOME="${FC_HOME}/.config" \
    "${FC_BIN}" "$@"
