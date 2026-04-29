<a href="#"><img src="/src/Gui/Icons/freecad.svg" height="100px" width="100px"></a>

# CADAgent

### AI-powered 3D parametric modeling — your CAD copilot, built on FreeCAD

CADAgent is a project forked from [FreeCAD](https://www.freecad.org). It keeps everything you love about FreeCAD and adds an AI assistant directly inside the app: a chat panel that opens automatically at launch (think GitHub Copilot, but for CAD).

> **Status:** early development. Things move fast and may break. Feedback and contributions are very welcome.

---

## For everyone — what is CADAgent?

CADAgent is a 3D modeling app you can talk to.

- **You describe what you want** — *“make a 20×10×5 mm plate with four 3 mm mounting holes”* — and the assistant builds it inside FreeCAD.
- **The chat panel is always there.** When you start CADAgent, the assistant dock opens automatically next to your model, just like a code editor’s AI sidebar.
- **You stay in control.** CADAgent uses real FreeCAD operations under the hood, so the model you get is a normal `.FCStd` file. You can edit it by hand, tweak parameters, or hand it off to a colleague who has plain FreeCAD.
- **It runs on your machine.** Your model files stay local. You bring your own AI provider (an API key or a local proxy) — see *Configuring the AI backend* below.

If you have never used FreeCAD before, CADAgent is a great way to start: ask the assistant for shapes, then learn the underlying tools as you go.

## For developers — what’s inside?

CADAgent is the FreeCAD 1.2.x source tree plus:

- A new workbench/module: [src/Mod/CADAgent/](src/Mod/CADAgent/) — the in‑app chat dock, agent runtime, sessions store, and rewind/compaction logic.
- A `pixi`-managed build environment ([pixi.toml](pixi.toml)) that pins the toolchain so `configure-debug` / `build-debug` work out of the box.
- The Anthropic Claude Agent SDK as the default agent backbone, routed through any OpenAI/Anthropic‑compatible endpoint via [LiteLLM](https://github.com/BerriAI/litellm).

Everything else — the geometry kernel (OpenCASCADE), Coin3D viewer, Python API, Qt UI, Sketcher, Part Design, Assembly, TechDraw, FEM, BIM, CAM, etc. — is inherited from upstream FreeCAD and stays fully usable.

---

## Installing

There are no precompiled CADAgent binaries yet. Build from source — see *Building from source* below.

If you only want classic FreeCAD without the agent, grab a release from the [upstream project](https://github.com/FreeCAD/FreeCAD/releases/latest).

## Building from source

CADAgent uses [`pixi`](https://pixi.sh) to provide a hermetic toolchain.

```bash
# 1. Clone with submodules
git clone --recursive <this repo's url> CADAgent
cd CADAgent

# 2. Install the pixi environment (one time)
pixi install

# 3. Configure and build the debug tree
pixi run configure-debug
pixi run build-debug
```

If `pixi` is not on your `PATH`, call it directly: `~/.pixi/bin/pixi run build-debug`.

A full build can take a while and produces thousands of targets. Warnings in third‑party code are normal.

### Running

```bash
# GUI app — the CADAgent chat dock opens automatically
build/debug/bin/FreeCAD

# Headless CLI
build/debug/bin/FreeCADCmd -c "import FreeCAD; print(FreeCAD.Version())"
```

In sandboxed environments where `$HOME` is not writable, redirect FreeCAD’s config dir:

```bash
env HOME=$PWD/.fc-home \
    XDG_DATA_HOME=$PWD/.fc-home/.local/share \
    XDG_CONFIG_HOME=$PWD/.fc-home/.config \
    build/debug/bin/FreeCAD
```

## Configuring the AI backend

CADAgent talks to any Anthropic‑compatible endpoint. The repo is pre‑wired for a local [LiteLLM](https://github.com/BerriAI/litellm) proxy:

```bash
export ANTHROPIC_BASE_URL=http://localhost:4141/
export ANTHROPIC_API_KEY=dummy
export ANTHROPIC_MODEL=gpt-5-mini
```

Replace those values with your own provider/key/model if you don’t want to run a proxy. The same variables are picked up by the in‑app chat dock.

## Tests

```bash
pixi run test-debug
# or a single suite:
ctest --test-dir build/debug -R Sketcher_tests_run
```

CADAgent‑specific tests live in [src/Mod/CADAgent/tests/](src/Mod/CADAgent/tests/) and run under `pytest` inside the pixi env.

---

## Repository layout

| Path | What lives there |
| --- | --- |
| [src/App/](src/App/) | Core application (geometry, document, properties) — from FreeCAD |
| [src/Gui/](src/Gui/) | Qt + Coin3D GUI — from FreeCAD |
| [src/Mod/](src/Mod/) | Workbenches: Part, PartDesign, Sketcher, Assembly, FEM, …  |
| [src/Mod/CADAgent/](src/Mod/CADAgent/) | **New** — chat dock, agent runtime, sessions, rewind/compaction |
| [pixi.toml](pixi.toml) / [CMakePresets.json](CMakePresets.json) | Build tooling |
| [tests/](tests/) | Upstream FreeCAD test suites |

## Relationship to FreeCAD

CADAgent is a **fork**, not a replacement. We track FreeCAD upstream and aim to:

- Keep file format and Python API compatibility — `.FCStd` files round‑trip with stock FreeCAD.
- Upstream non‑agent fixes back to FreeCAD whenever it makes sense.
- Keep the agent code self‑contained in `src/Mod/CADAgent/` so it’s easy to reason about and easy to disable.

Huge thanks to the FreeCAD community — none of this exists without their decades of work on a serious open‑source CAD kernel.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR. In short:

- Keep changes minimal and focused on one problem.
- Make sure the build and relevant tests pass.
- Raw, unreviewed AI output is **not** acceptable as a contribution — review and defend every change you submit, even (especially) the ones an assistant helped you write.

## Reporting issues

Open a ticket on this repository’s issue tracker. Please include:

- OS and how you built CADAgent (pixi version, compiler).
- Output of `Help → About FreeCAD → Copy to clipboard` from inside the GUI.
- Steps to reproduce, an example `.FCStd` if relevant, and — for agent issues — the prompt you used and the chat transcript.

## License

CADAgent inherits FreeCAD’s license. See [LICENSE](LICENSE). The CADAgent‑specific code under [src/Mod/CADAgent/](src/Mod/CADAgent/) is released under the same terms unless noted otherwise in a given file.

## Privacy & security

The agent only sends to your AI provider what you type into the chat (plus the tool calls it makes against your local FreeCAD process). No telemetry is added on top of upstream FreeCAD. See [PRIVACY_POLICY.md](PRIVACY_POLICY.md) and [SECURITY.md](SECURITY.md) for details.
