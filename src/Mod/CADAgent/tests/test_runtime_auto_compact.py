# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless tests for Wave-2 auto-compaction wiring on ``DockRuntime``.

We bypass ``DockRuntime.__init__`` (it constructs a real ``_PanelProxy`` that
needs a Qt panel with every signal slot bound) and stand up the minimum field
set the runtime methods touch. Compaction primitives (``compact_session``,
``summarize_transcript``) and the ``sessions`` token writer are stubbed so the
tests stay focused on the runtime's decision logic.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types
from dataclasses import dataclass

import pytest

from agent import compaction as _compaction
from agent.cli import dock_runtime as _dr


# --- shared harness --------------------------------------------------------


class _Sig:
    """Fire-and-record stand-in for a Qt signal."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def emit(self, *args) -> None:
        self.calls.append(args)

    def connect(self, *_args, **_kwargs) -> None:  # parity with Qt API
        pass


class _Proxy:
    """Drop-in for ``_PanelProxy`` — every signal the runtime touches."""

    def __init__(self) -> None:
        for name in (
            "assistantText", "thinking", "toolUse", "toolResult", "resultMsg",
            "turnComplete", "error", "permissionRequest", "askUserQuestion",
            "sessionChanged", "milestoneUpsert", "verificationResult",
            "decisionRecorded", "compactionEvent", "subagentSpan",
            "permissionModeChanged", "streamState", "todosUpdate", "planFile",
            "planExited", "editApprovalRequest", "hookEvent", "activeDocChanged",
            "docReloadRequested", "contextUsage", "compactingChanged",
        ):
            setattr(self, name, _Sig())


class _Model:
    def __init__(self) -> None:
        self._rows: list[dict] = []


class _Panel:
    def __init__(self) -> None:
        self._model = _Model()
        self._current_session_id = "sid-orig"
        self._bound_doc = None


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


def _make_runtime(monkeypatch) -> _dr.DockRuntime:
    """Construct a ``DockRuntime`` skeleton with only the fields we exercise."""
    rt = _dr.DockRuntime.__new__(_dr.DockRuntime)
    rt.panel = _Panel()
    rt._proxy = _Proxy()
    rt.client = None
    rt._loop = None
    rt._thread = None
    rt._ready = threading.Event()
    rt._current_future = None
    rt._workspace_path = None
    rt._resume_sid = None
    rt._mode_override = None
    rt._suppressed_tool_ids = set()
    rt._plan_tool_ids = {}
    rt._turn_index = 0
    rt._pending_tool_calls = {}
    rt._session_tokens = _compaction.SessionTokens()
    rt._pending_auto_compact = False
    rt._compacting = False
    rt._last_user_prompt = None
    rt._last_user_attachments = None
    rt._overflow_retried = False
    # Force a known model + empty settings so the threshold maths is stable.
    monkeypatch.setattr(rt, "_model_name", lambda: "gpt-5-mini", raising=False)
    monkeypatch.setattr(rt, "_settings", lambda: {}, raising=False)
    return rt


def _patch_session_writer(monkeypatch):
    calls: list[tuple] = []

    def _update(doc, sid, usage):
        calls.append(("update_tokens", doc, sid, dict(usage or {})))

    monkeypatch.setattr(_dr._sessions, "update_tokens", _update)
    return calls


# --- 1. ResultMessage with ≥95% usage arms _pending_auto_compact ----------


def test_result_message_arms_pending_auto_compact(monkeypatch):
    rt = _make_runtime(monkeypatch)
    _patch_session_writer(monkeypatch)

    # gpt-5-mini → 400_000 token limit. 95% = 380_000.
    msg = types.SimpleNamespace(
        session_id="sid-orig",
        usage=_Usage(input_tokens=380_001, output_tokens=0),
    )
    rt._record_usage(msg, msg.session_id)

    assert rt._pending_auto_compact is True
    # contextUsage was emitted with (used, limit).
    assert rt._proxy.contextUsage.calls
    used, limit = rt._proxy.contextUsage.calls[-1]
    assert used == 380_001
    assert limit == 400_000


def test_result_message_below_threshold_does_not_arm(monkeypatch):
    rt = _make_runtime(monkeypatch)
    _patch_session_writer(monkeypatch)

    msg = types.SimpleNamespace(
        session_id="sid-orig",
        usage=_Usage(input_tokens=1_000, output_tokens=500),
    )
    rt._record_usage(msg, msg.session_id)

    assert rt._pending_auto_compact is False


# --- 2. Next _ask() flushes the pending flag exactly once -----------------


def test_ask_drains_pending_auto_compact_and_clears_flag(monkeypatch):
    rt = _make_runtime(monkeypatch)

    runs: list[str] = []

    async def _stub_run(reason: str):
        runs.append(reason)

    monkeypatch.setattr(rt, "_run_compaction", _stub_run, raising=False)

    # _ensure_client raises so we exit before the SDK loop without needing a
    # real client; the early-flush block must already have fired by then.
    async def _boom():
        raise RuntimeError("no-client")

    monkeypatch.setattr(rt, "_ensure_client", _boom, raising=False)
    # Suppress turn-end side effects unrelated to the assertion.
    monkeypatch.setattr(_dr.gui_thread, "run_sync", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_run_hook", lambda *a, **k: None, raising=False)

    rt._pending_auto_compact = True
    rt._last_user_prompt = "hello"

    asyncio.new_event_loop().run_until_complete(rt._ask("hello"))

    assert runs == ["auto"]
    assert rt._pending_auto_compact is False


# --- 3. Overflow exception triggers forced compaction + one retry ---------


def test_overflow_during_turn_triggers_forced_retry(monkeypatch):
    rt = _make_runtime(monkeypatch)

    runs: list[str] = []

    async def _stub_run(reason: str):
        runs.append(reason)

    monkeypatch.setattr(rt, "_run_compaction", _stub_run, raising=False)

    attempts: list[str] = []

    async def _ensure():
        attempts.append("ensure")
        # Provide a tiny fake client just for ``query`` / ``receive_response``.
        rt.client = _FakeClient(should_raise=(len(attempts) == 1))

    monkeypatch.setattr(rt, "_ensure_client", _ensure, raising=False)
    monkeypatch.setattr(_dr.gui_thread, "run_sync", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_run_hook", lambda *a, **k: None, raising=False)

    rt._last_user_prompt = "the prompt"

    asyncio.new_event_loop().run_until_complete(rt._ask("the prompt"))

    assert runs == ["forced"]
    # One initial ensure_client + one retry ensure_client.
    assert attempts == ["ensure", "ensure"]
    # The second client received the same prompt (single retry).
    assert rt.client.queries[-1] == "the prompt"
    assert rt._overflow_retried is True


def test_second_overflow_surfaces_normally(monkeypatch):
    rt = _make_runtime(monkeypatch)

    async def _stub_run(reason: str):
        return None

    monkeypatch.setattr(rt, "_run_compaction", _stub_run, raising=False)

    async def _ensure():
        rt.client = _FakeClient(should_raise=True)

    monkeypatch.setattr(rt, "_ensure_client", _ensure, raising=False)
    monkeypatch.setattr(_dr.gui_thread, "run_sync", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_run_hook", lambda *a, **k: None, raising=False)

    rt._last_user_prompt = "p"

    asyncio.new_event_loop().run_until_complete(rt._ask("p"))

    # Both attempts raised overflow; the second one was reported via error.
    assert rt._proxy.error.calls, "second overflow should be surfaced"


class _FakeClient:
    """Async stand-in for ClaudeSDKClient for the overflow path."""

    def __init__(self, should_raise: bool) -> None:
        self._should_raise = should_raise
        self.queries: list[str] = []

    async def query(self, prompt) -> None:
        self.queries.append(prompt)

    async def receive_response(self):
        if self._should_raise:
            raise RuntimeError("prompt is too long for the context length")
        if False:
            yield  # make this an async generator
        return


# --- 4. request_compaction schedules _run_compaction on the worker loop ---


def test_request_compaction_schedules_run_compaction(monkeypatch):
    rt = _make_runtime(monkeypatch)

    seen: list[str] = []

    async def _stub_run(reason: str):
        seen.append(reason)

    monkeypatch.setattr(rt, "_run_compaction", _stub_run, raising=False)

    # Stand up the runtime's worker loop using its real _ensure_loop.
    loop = rt._ensure_loop()
    try:
        rt.request_compaction("manual")
        # Drain by scheduling a no-op and waiting for it.
        fut = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop)
        fut.result(timeout=2)
        # The scheduled coroutine may not have completed yet; loop again.
        fut = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop)
        fut.result(timeout=2)
    finally:
        loop.call_soon_threadsafe(loop.stop)

    assert seen == ["manual"]


# --- 5. _run_compaction wires through compact_session + emits event -------


def test_run_compaction_calls_compact_session_and_emits(monkeypatch):
    rt = _make_runtime(monkeypatch)
    rt.panel._bound_doc = object()
    rt._session_tokens.accumulate(_Usage(input_tokens=100_000, output_tokens=0))

    captured: dict = {}

    def _fake_compact(doc, sid, rows, summary, fork=True):
        captured["sid"] = sid
        captured["fork"] = fork
        captured["summary"] = summary
        return "sid-new"

    def _fake_summarize(rows, model, opts):
        return "<compaction-summary>\nsummary-body\n</compaction-summary>"

    monkeypatch.setattr(_compaction, "compact_session", _fake_compact)
    monkeypatch.setattr(_compaction, "summarize_transcript", _fake_summarize)

    async def _noop_close():
        rt.client = None

    monkeypatch.setattr(rt, "_aclose", _noop_close, raising=False)

    asyncio.new_event_loop().run_until_complete(rt._run_compaction("auto"))

    assert captured["sid"] == "sid-orig"
    assert captured["fork"] is True
    assert rt._resume_sid == "sid-new"
    # Token accumulator was reset (seeded by summary length).
    assert rt._session_tokens.effective_context_used() < 100_000
    # compactingChanged fired True then False.
    flags = [c[0] for c in rt._proxy.compactingChanged.calls]
    assert flags == [True, False]
    # compactionEvent payload includes reason + before/after.
    assert rt._proxy.compactionEvent.calls
    payload = rt._proxy.compactionEvent.calls[-1][0]
    assert payload["reason"] == "auto"
    assert payload["tokensBefore"] == 100_000
