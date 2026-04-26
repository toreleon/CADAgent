# CADAgent headless test harness

Run from the repo root:

```bash
pixi run test-cadagent           # all CADAgent tests
pixi run test-cadagent -- -k foo # filter
```

Or directly with the env's python:

```bash
.pixi/envs/default/bin/python -m pytest src/Mod/CADAgent/tests/ -v
```

## What the harness provides

- **`tests/fakes/freecad.py`** — in-memory `FreeCAD` module installed into
  `sys.modules` before any `agent.*` import. Implements `App.getUserAppDataDir`,
  `App.ParamGet`, document lifecycle (`new/open/close/setActive/listDocuments`,
  `ActiveDocument`), and `App.Console`. The real FreeCAD binary is **not**
  needed; tests run anywhere Python + the pixi env exist.
- **`tests/fakes/sdk_client.py`** — `FakeSDKClient`, a scriptable async drop-in
  for `claude_agent_sdk.ClaudeSDKClient`. Reuses the **real** SDK message and
  block dataclasses (`AssistantMessage`, `TextBlock`, `ToolUseBlock`,
  `ResultMessage`, …) so `isinstance` assertions work normally — only the
  network is faked. `make_result(...)` builds terminal `ResultMessage` rows.
- **`tests/conftest.py`** — installs the fake `FreeCAD` at collection time and
  exposes fixtures:
  - `fc` — fresh fake `FreeCAD` namespace, `getUserAppDataDir` redirected to
    `tmp_path`. Use this whenever a test mutates documents or params.
  - `fake_doc` — a saved `FakeDocument` at `<tmp>/test.FCStd`. Use for any
    `agent.sessions.*` test that needs a doc.
  - `fake_sdk_client` — the `FakeSDKClient` class itself (factory).

## Patterns

### Sessions / persistence

```python
def test_my_thing(fake_doc):
    from agent import sessions
    sessions.save_rows(fake_doc, "sid", [{"kind": "user", "text": "hi"}])
    assert sessions.load_rows(fake_doc, "sid")[0]["text"] == "hi"
```

### Driving the runtime against a fake LLM

```python
def test_runtime_turn(fake_doc, fake_sdk_client, monkeypatch):
    from claude_agent_sdk import TextBlock
    from tests.fakes.sdk_client import make_result

    fake = fake_sdk_client([
        [TextBlock(text="ok")],
        make_result(num_turns=1, session_id="s1"),
    ])
    # Patch the constructor inside dock_runtime so _ensure_client returns `fake`:
    monkeypatch.setattr(
        "agent.cli.dock_runtime.ClaudeSDKClient", lambda **kw: fake
    )
    # ... then drive runtime.submit() and assert on fake.queries / model rows
```

### Hooks / permissions

`agent.permissions.make_can_use_tool(...)` is a pure async callable taking
`(tool_name, tool_input, context)` and returning `PermissionResultAllow|Deny`.
Test it directly — no UI needed.

## What's *not* covered

- **Qt / QML rendering.** `MessagesModel` and `ChatBridge` inherit from
  `QObject`/`QAbstractListModel`; instantiating them needs a `QApplication`.
  Backend logic is testable; UI delegate behavior is not. Run FreeCAD manually
  to verify QML.
- **The real FreeCADCmd binary.** If you need real geometry, shell out to
  `build/debug/bin/FreeCADCmd -c "<script>"` from a test marked `@pytest.mark.slow`.

## For Wave-1 / Wave-2 workers

Each unit should add `tests/test_<unit>.py` next to `test_harness_smoke.py` and
exercise its backend logic against these fixtures. Workers must run
`pixi run test-cadagent` and report the result; the suite is fast (<1s today).
