# CLAUDE.md

This repository is the FreeCAD codebase. Use this file as the practical working guide for Claude Code in this repo.

## Repo overview

- Main project: FreeCAD 1.2.x development tree
- Build system: CMake
- Dependency/tool environment: `pixi`
- Primary languages: C++, Python, Qt
- Important submodules:
  - `src/3rdParty/GSL`
  - `src/3rdParty/OndselSolver`
  - `src/Mod/AddonManager`
  - `tests/lib`

## First-time setup

Initialize submodules before configuring:

```bash
git submodule update --init --recursive
```

If `pixi` is not on `PATH`, use the installed binary directly:

```bash
/home/tore/.pixi/bin/pixi --version
```

## Build commands

Preferred debug configure/build flow:

```bash
pixi run configure-debug
pixi run build-debug
```

If `pixi` is not on `PATH`:

```bash
/home/tore/.pixi/bin/pixi run configure-debug
/home/tore/.pixi/bin/pixi run build-debug
```

Important:

- The repo uses the `conda-linux-debug` preset through `pixi`.
- Do not mix a manual `cmake -S . -B build/debug` configure with the `pixi` preset in the same build directory; the generator can conflict (`Unix Makefiles` vs `Ninja`).
- If that happens, remove the generated build directory and reconfigure:

```bash
cmake -E rm -rf build/debug
pixi run configure-debug
```

## Run commands

Built binaries:

- GUI app: `build/debug/bin/FreeCAD`
- CLI app: `build/debug/bin/FreeCADCmd`

In this environment, FreeCAD may fail if it tries to write config/data under a non-writable home. Use redirected `HOME` and `XDG_*` paths:

```bash
env HOME=/home/code/CADAgent/.fc-home \
  XDG_DATA_HOME=/home/code/CADAgent/.fc-home/.local/share \
  XDG_CONFIG_HOME=/home/code/CADAgent/.fc-home/.config \
  build/debug/bin/FreeCAD
```

CLI example:

```bash
env HOME=/home/code/CADAgent/.fc-home \
  XDG_DATA_HOME=/home/code/CADAgent/.fc-home/.local/share \
  XDG_CONFIG_HOME=/home/code/CADAgent/.fc-home/.config \
  build/debug/bin/FreeCADCmd -c "import FreeCAD; print(FreeCAD.Version())"
```

Create those directories if needed:

```bash
mkdir -p /home/code/CADAgent/.fc-home/.local/share /home/code/CADAgent/.fc-home/.config
```

## Test commands

Run the configured test suite:

```bash
pixi run test-debug
```

Or directly:

```bash
ctest --test-dir build/debug
```

Run a single CTest target by name:

```bash
ctest --test-dir build/debug -R Sketcher_tests_run
```

## Useful paths

- Top-level CMake config: `CMakeLists.txt`
- CMake presets: `CMakePresets.json`
- Pixi env/tasks: `pixi.toml`
- Core app code: `src/App`
- GUI code: `src/Gui`
- Workbenches/modules: `src/Mod`
- Tests: `tests`

## Editing guidance

- Follow existing patterns in the touched subsystem; FreeCAD is large and style varies slightly by area.
- Prefer targeted fixes over broad refactors.
- Avoid introducing new dependencies unless absolutely necessary.
- Be careful with Python API changes; external addons may depend on them.
- If changing UI behavior, note that screenshots are typically expected in a PR.

## Contribution constraints from repo docs

Based on `CONTRIBUTING.md`:

- Changes should be minimal and solve one concrete problem.
- PRs must compile cleanly and pass relevant tests.
- Raw AI output is explicitly not acceptable; any change must be reviewed, validated, and defensible.

## Notes from this environment

- `DISPLAY` and Wayland may both be present, so GUI launch is possible.
- The debug build emits a number of warnings in third-party and module code; warnings alone do not imply a broken build.
- A successful build in this repo can take a long time and may produce thousands of targets, including translations and test binaries.
