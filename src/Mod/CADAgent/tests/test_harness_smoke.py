"""Smoke tests proving the headless harness loads agent backend modules and
exercises real persistence logic against the fake FreeCAD."""
from __future__ import annotations


def test_fake_freecad_installed(fc, tmp_path):
    import FreeCAD as App  # type: ignore[import-not-found]

    assert App.getUserAppDataDir() == str(tmp_path)
    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/CADAgent")
    params.SetString("Model", "gpt-5-mini")
    assert params.GetString("Model") == "gpt-5-mini"


def test_fake_doc_lifecycle(fc, tmp_path):
    import FreeCAD as App  # type: ignore[import-not-found]

    doc = App.newDocument("Untitled")
    assert App.ActiveDocument is doc
    assert doc.Name in App.listDocuments()
    App.closeDocument(doc.Name)
    assert App.ActiveDocument is None


def test_sessions_roundtrip(fake_doc):
    """Real `agent.sessions` against the fake FreeCAD: save/load rows."""
    from agent import sessions

    sid = "abc-123"
    rows = [
        {"kind": "user", "text": "make a cube", "meta": {}, "rowId": "r0"},
        {"kind": "assistant", "text": "ok", "meta": {}, "rowId": "r1"},
    ]
    sessions.save_rows(fake_doc, sid, rows)
    loaded = sessions.load_rows(fake_doc, sid)
    assert loaded == rows


def test_sessions_index_record_and_list(fake_doc):
    from agent import sessions

    sid = "xyz-789"
    sessions.record_turn(fake_doc, sid, "first prompt")
    sessions.record_turn(fake_doc, sid, "first prompt")  # idempotent on same sid
    listed = sessions.list_sessions(fake_doc)
    assert any(entry.get("id") == sid for entry in listed)
    entry = sessions.find(fake_doc, sid)
    assert entry is not None
    assert entry.get("turn_count", 0) >= 1


def test_permissions_module_imports():
    """The permissions module pulls real `claude_agent_sdk` types."""
    from agent import permissions

    assert hasattr(permissions, "make_can_use_tool")


def test_fake_sdk_client_basic(fake_sdk_client):
    import asyncio

    from claude_agent_sdk import AssistantMessage, TextBlock

    from tests.fakes.sdk_client import make_result

    script = [
        [TextBlock(text="hello")],
        make_result(num_turns=1),
    ]
    client = fake_sdk_client(script)

    async def drive():
        async with client as c:
            await c.query("hi")
            collected = [m async for m in c.receive_response()]
        return collected

    msgs = asyncio.run(drive())
    assert isinstance(msgs[0], AssistantMessage)
    assert msgs[0].content[0].text == "hello"
    assert client.queries == ["hi"]
    assert client.entered and client.closed


def test_sdk_exposes_session_management():
    """Verifies the pinned SDK has the symbols Wave 1 will rely on."""
    import claude_agent_sdk as sdk

    for sym in (
        "fork_session",
        "delete_session",
        "get_session_messages",
        "list_sessions",
        "rename_session",
        "PreToolUseHookInput",
        "PostToolUseHookInput",
        "StopHookInput",
        "UserPromptSubmitHookInput",
        "HookCallback",
        "HookMatcher",
    ):
        assert hasattr(sdk, sym), f"SDK missing {sym}"
