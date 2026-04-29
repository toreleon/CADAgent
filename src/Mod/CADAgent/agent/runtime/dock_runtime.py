# SPDX-License-Identifier: LGPL-2.1-or-later
"""In-FreeCAD host for the chat agent.

The shared runtime in :mod:`agent.cli.runtime` builds the SDK options
(system prompt, MCP tools, hooks). This module wires it onto the FreeCAD
chat dock: the SDK runs on a dedicated worker asyncio loop while the QML
panel — and any FreeCAD doc mutations — stay on the Qt GUI thread.

The agent owns document lifecycle: it can list, create, open, switch,
and reload documents through the MCP tools in :mod:`agent.cli.dock_tools`
— think of it like a shell session that can ``cd`` between projects.
Geometry still happens via ``Bash → FreeCADCmd`` subprocesses (the CLI
agent's contract); we save the active doc before each turn and auto-reload
it after, so the GUI reflects whatever the subprocess wrote.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import threading
import traceback
from typing import Any

import FreeCAD as App

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .. import compaction as _compaction
from .. import gui_thread, hooks, sessions as _sessions, ui_bridge
from ..cli import dock_tools  # GUI doc-lifecycle MCP tools (registers via @cad_tool)
from ..host.doc_state import reload_active_doc_if_stale as _reload_active_doc_if_stale
from ..host.multimodal import multimodal_prompt as _multimodal_prompt
from ..host.panel_proxy import PanelProxy as _PanelProxy
from ..permissions import make_can_use_tool, clear_session_allowlist
from ..tools import short_name as _strip_prefix
from ..worker import client as worker_client
from . import context_builder as _context_builder
from . import options as cli_runtime  # name kept for back-compat with the old module variable

try:  # Wave-1 unit W1-A: workspace checkpointing. Optional at import so
    # the runtime still loads if the module is missing or broken.
    from .. import checkpoints as _checkpoints
except Exception:  # pragma: no cover - defensive
    _checkpoints = None


_MCP_PREFIX = "mcp__cad__"

# Auto-plan heuristic: treat a prompt as "complex" if it is long *and* hints at
# multi-object / multi-feature design work. Single-feature edits ("rename
# Pad001", "change thickness to 5mm") bypass plan mode to stay snappy.
_AUTO_PLAN_VERBS = (
    "design", "build", "model", "create a full", "refactor", "redesign",
    "restructure", "multi-part", "assembly", "several", "multiple",
)
_AUTO_PLAN_MIN_CHARS = 90


def _should_auto_plan(text: str) -> bool:
    if not text or len(text) < _AUTO_PLAN_MIN_CHARS:
        return False
    lower = text.lower()
    if not any(v in lower for v in _AUTO_PLAN_VERBS):
        return False
    # Crude multi-feature signal: commas, bullets, or the word "and" appearing
    # more than once usually means the user is describing multiple deliverables.
    return lower.count(",") + lower.count(" and ") + lower.count("\n- ") >= 2


# NOTE: _multimodal_prompt, _strip_prefix, _PanelProxy, and
# _reload_active_doc_if_stale moved to agent.host.* at Step 9. The
# aliases imported at the top of this module keep the old in-module names
# working for the call sites below; Step 11 inlines those call sites to
# use the host names directly.


def _snapshot_active_doc() -> dict:
    """Save the active doc if dirty and return a small summary.

    Thin wrapper preserving the legacy dict shape used by ``submit()``
    callers and by W2-D's WorkspaceChip. The actual snapshot lives in
    :mod:`agent.runtime.context_builder` so Step 16 can extend it with
    selection / view-state in one place.
    """
    return _context_builder.snapshot_active_doc().to_dict()


def _build_preamble(snap: dict) -> str:
    return _context_builder.build_preamble(snap)


class DockRuntime:
    """Chat-panel-facing wrapper around the CLI agent.

    Public API mirrors what :class:`agent.ui.qml_panel.QmlChatPanel`
    expects: ``submit(text)``, ``interrupt()``, ``start_new_session()``.
    """

    def __init__(self, panel):
        self.panel = panel
        self._proxy = _PanelProxy(panel)
        ui_bridge.set_proxy(self._proxy)
        self.client: ClaudeSDKClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._current_future: concurrent.futures.Future | None = None
        self._workspace_path: str | None = None
        self._resume_sid: str | None = None
        # One-turn permission_mode override set by auto-plan / slash commands.
        # Consumed (and cleared) by _ensure_client the next time it runs.
        self._mode_override: str | None = None
        # tool_use_ids we've consumed into richer surfaces (todos / plan_*);
        # their tool_result messages are suppressed so the generic "(tool
        # result)" fallback doesn't leak into the transcript.
        self._suppressed_tool_ids: set[str] = set()
        # tool_use_id -> plan_* short name, so we can parse the result of
        # plan_emit into milestoneUpsert events once it arrives.
        self._plan_tool_ids: dict[str, str] = {}
        # Monotonic turn counter for the current session. Reset on
        # ``start_new_session`` / ``resume_session``. Used by the W1-A
        # checkpoint store and tagged onto persisted user rows so rewind
        # (W1-B) can map a row back to its workspace snapshot.
        self._turn_index: int = 0
        # tool_use_id -> (tool_name, tool_input) so PostToolUse hooks can see
        # the original invocation alongside the SDK's tool_result content.
        self._pending_tool_calls: dict[str, tuple[str, Any]] = {}
        # Auto-compact state. ``_session_tokens`` accumulates ResultMessage
        # usage; ``_pending_auto_compact`` is set after a turn that crossed
        # the threshold and triggers a compact at the start of the next
        # ``submit``. ``_compacting`` guards against re-entry while a
        # compaction coroutine is in flight. ``_last_user_prompt`` is stashed
        # for the overflow-retry path. ``_overflow_retried`` is True after we
        # auto-retry once so a second overflow surfaces normally.
        self._session_tokens = _compaction.SessionTokens()
        self._pending_auto_compact: bool = False
        self._compacting: bool = False
        self._last_user_prompt: str | None = None
        self._last_user_attachments: list[str] | None = None
        self._overflow_retried: bool = False

    @property
    def last_turn_index(self) -> int:
        """Index of the most recently submitted turn (0-based)."""
        return self._turn_index

    def _set_workspace_path(self, path: str | None) -> None:
        """Update the tracked workspace path and notify subscribers on change."""
        new = path or None
        if new == self._workspace_path:
            return
        self._workspace_path = new
        try:
            self._proxy.activeDocChanged.emit(new or "")
        except Exception:
            pass

    def list_open_docs(self) -> list[dict]:
        """Return one entry per open FreeCAD document for the workspace chip.

        Each entry: ``{"name", "label", "path", "active"}``. ``label`` is the
        document's display label (preferred for UI); ``name`` is the internal
        identifier the agent's ``gui_set_active_document`` tool expects.
        """
        try:
            docs = list(App.listDocuments().values())
        except Exception:
            return []
        active = getattr(App, "ActiveDocument", None)
        active_name = getattr(active, "Name", None) if active is not None else None
        out: list[dict] = []
        for d in docs:
            name = getattr(d, "Name", "") or ""
            out.append({
                "name": name,
                "label": getattr(d, "Label", "") or name,
                "path": getattr(d, "FileName", "") or "",
                "active": name == active_name,
            })
        return out

    def set_active_document(self, label_or_name: str) -> bool:
        """Activate an already-open doc by ``Name`` (preferred) or ``Label``.

        Mirrors the agent's ``gui_set_active_document`` tool but is callable
        from the GUI thread without an LLM round-trip. Returns ``True`` if a
        match was found and activated.
        """
        target = (label_or_name or "").strip()
        if not target:
            return False
        try:
            docs = App.listDocuments()
        except Exception:
            return False
        match = docs.get(target)
        if match is None:
            for d in docs.values():
                if (getattr(d, "Label", "") or "") == target:
                    match = d
                    break
        if match is None:
            return False
        try:
            App.setActiveDocument(match.Name)
        except Exception:
            return False
        path = getattr(match, "FileName", "") or None
        self._set_workspace_path(path)
        return True

    # --- hooks ---------------------------------------------------------

    def _doc_dir(self) -> str | None:
        """Return the directory of the active workspace doc, if any.

        Used by the hooks engine to resolve project-scoped settings at
        ``<doc_dir>/.cadagent/settings.json``.
        """
        if not self._workspace_path:
            return None
        try:
            return os.path.dirname(self._workspace_path) or None
        except (TypeError, ValueError):
            return None

    def _run_hook(self, event_name: str, payload: dict) -> "hooks.HookResult | None":
        """Dispatch ``event_name`` and surface the result on ``hookEvent``.

        Wrapped in try/except: a misconfigured settings.json must never crash
        a turn. Returns the result so callers can react to ``decision == "block"``.
        """
        try:
            result = hooks.run(event_name, payload, doc_dir=self._doc_dir())
        except Exception:
            return None
        try:
            self._proxy.hookEvent.emit(
                event_name,
                payload,
                {
                    "decision": result.decision,
                    "message": result.message,
                    "output": result.output,
                },
            )
        except Exception:
            pass
        return result

    # --- worker thread -------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            try:
                loop.run_forever()
            finally:
                loop.close()

        self._thread = threading.Thread(
            target=_run, name="CADAgentAsyncio", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=5)
        assert self._loop is not None
        return self._loop

    # --- session -------------------------------------------------------

    async def _ensure_client(self) -> None:
        if self.client is not None:
            return
        # Pull LLM config from FreeCAD's parameter store first (set via the
        # "Configure LLM…" menu / dialog), with ANTHROPIC_* env vars as
        # fallback for headless / dev launches.
        params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/CADAgent")
        api_key = params.GetString("ApiKey", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = params.GetString("BaseURL", "") or os.environ.get("ANTHROPIC_BASE_URL", "")
        model = params.GetString("Model", "") or os.environ.get("ANTHROPIC_MODEL", "")
        mode = params.GetString("PermissionMode", "") or "default"
        if mode not in ("default", "acceptEdits", "plan", "bypassPermissions"):
            mode = "default"
        if self._mode_override:
            mode = self._mode_override
            self._mode_override = None
        if not api_key:
            raise RuntimeError(
                "No LLM API key configured. Use the CAD Agent menu → "
                "'Configure LLM…' to set the API key (and optional base URL "
                "for a LiteLLM proxy)."
            )
        os.environ["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            os.environ["ANTHROPIC_BASE_URL"] = base_url
        if model:
            os.environ["ANTHROPIC_MODEL"] = model
        # Tell the CLI runtime where the workspace .FCStd is so its MCP memory
        # tools (which key off the sidecar path) operate on the right doc.
        if self._workspace_path:
            os.environ["CADAGENT_DOC"] = self._workspace_path
        extra_opts: dict[str, Any] = {}
        if self._resume_sid:
            extra_opts["resume"] = self._resume_sid
        # Thinking toggle + effort come from the Configure LLM dialog. When
        # disabled we force ``thinking={"type":"disabled"}`` regardless of
        # any CADAGENT_THINKING env default; when enabled we honour the user's
        # effort choice and let build_options derive a sensible thinking
        # config (adaptive unless CADAGENT_THINKING provides a budget).
        thinking_enabled = bool(params.GetBool("ThinkingEnabled", False))
        effort = (params.GetString("ThinkingEffort", "") or "").strip().lower()
        if thinking_enabled:
            extra_opts["thinking"] = {"type": "adaptive"}
            if effort in ("low", "medium", "high", "max"):
                extra_opts["effort"] = effort
        else:
            extra_opts["thinking"] = {"type": "disabled"}
        options = cli_runtime.build_options(
            extra_tools=dock_tools.TOOL_FUNCS,
            extra_allowed_tool_names=dock_tools.allowed_tool_names("cad"),
            permission_mode=mode,
            can_use_tool=make_can_use_tool(
                self._proxy, mode, doc_dir_provider=self._doc_dir,
            ),
            **extra_opts,
        )
        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()

    async def _dispatch_turn(
        self, user_text: str, attachments: list[str] | None
    ) -> None:
        """Open a client (if needed), submit ``user_text``, and route replies."""
        await self._ensure_client()
        assert self.client is not None
        if attachments:
            await self.client.query(_multimodal_prompt(user_text, attachments))
        else:
            await self.client.query(user_text)
        async for msg in self.client.receive_response():
            self._route_message(msg)

    async def _ask(
        self, user_text: str, attachments: list[str] | None = None
    ) -> None:
        # Drain a queued auto-compact (set by the previous turn's ResultMessage)
        # before opening the next SDK client so the post-compact ``_resume_sid``
        # is what gets connected.
        if self._pending_auto_compact and not self._compacting:
            self._pending_auto_compact = False
            try:
                await self._run_compaction(reason="auto")
            except Exception:
                pass
        try:
            await self._dispatch_turn(user_text, attachments)
        except BaseException as exc:
            if (
                _compaction.is_context_overflow_error(exc)
                and not self._overflow_retried
                and self._last_user_prompt is not None
            ):
                self._overflow_retried = True
                try:
                    await self._run_compaction(reason="forced")
                except Exception:
                    pass
                try:
                    await self._dispatch_turn(
                        self._last_user_prompt, self._last_user_attachments
                    )
                except Exception as retry_exc:
                    self._proxy.error.emit(
                        f"{retry_exc}\n\n{traceback.format_exc(limit=3)}"
                    )
            elif isinstance(exc, Exception):
                self._proxy.error.emit(
                    f"{exc}\n\n{traceback.format_exc(limit=3)}"
                )
            else:
                raise
        finally:
            try:
                gui_thread.run_sync(_reload_active_doc_if_stale, timeout=30.0)
            except Exception:
                pass
            # Stop hook — fires once per turn boundary regardless of error
            # status. Any returned decision is informational; we don't block
            # turn-end teardown on it.
            try:
                self._run_hook("Stop", {})
            except Exception:
                pass
            # Drop per-turn bookkeeping so stale ids don't leak across turns
            # or across resumes.
            self._suppressed_tool_ids.clear()
            self._plan_tool_ids.clear()
            self._pending_tool_calls.clear()
            self._proxy.turnComplete.emit()

    def _route_message(self, msg) -> None:
        if isinstance(msg, StreamEvent):
            ev = msg.event or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                dtype = delta.get("type")
                if dtype == "text_delta":
                    text = delta.get("text") or ""
                    if text:
                        self._proxy.assistantText.emit(text)
                elif dtype == "thinking_delta":
                    text = delta.get("thinking") or ""
                    if text:
                        self._proxy.thinking.emit(text)
            return
        if isinstance(msg, AssistantMessage):
            self._proxy.streamState.emit("", False)
            for block in msg.content:
                if isinstance(block, TextBlock):
                    pass  # already streamed via deltas
                elif isinstance(block, ToolUseBlock):
                    self._handle_tool_use(block)
                elif isinstance(block, ThinkingBlock):
                    self._proxy.thinking.emit(block.thinking)
        elif isinstance(msg, UserMessage):
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        self._handle_tool_result(block)
        elif isinstance(msg, ResultMessage):
            sid = getattr(msg, "session_id", None)
            if sid:
                self._proxy.sessionChanged.emit(sid)
            self._proxy.resultMsg.emit(msg)
            self._record_usage(msg, sid)

    # --- tool routing helpers ------------------------------------------
    #
    # TodoWrite and plan_* tool calls are rendered as dedicated panel
    # surfaces (checklist / milestone rows) instead of generic tool rows.
    # We consume them here and record their tool_use_ids so the matching
    # ToolResultBlock is also suppressed.
    def _handle_tool_use(self, block: ToolUseBlock) -> None:
        tool_id = getattr(block, "id", "") or ""
        short = _strip_prefix(block.name)
        tool_input = block.input or {}

        # Stash so the matching tool_result can fire PostToolUse with both
        # input and output. PreToolUse already ran inside permissions.py.
        if tool_id:
            self._pending_tool_calls[tool_id] = (short, tool_input)

        if short == "TodoWrite":
            todos = tool_input.get("todos") if isinstance(tool_input, dict) else None
            self._proxy.todosUpdate.emit(list(todos or []))
            if tool_id:
                self._suppressed_tool_ids.add(tool_id)
            return

        if short == "exit_plan_mode":
            if tool_id:
                self._plan_tool_ids[tool_id] = short
                self._suppressed_tool_ids.add(tool_id)
            return

        if short.startswith("plan_"):
            if tool_id:
                self._plan_tool_ids[tool_id] = short
                self._suppressed_tool_ids.add(tool_id)
            if short in ("plan_milestone_activate",
                         "plan_milestone_done",
                         "plan_milestone_failed"):
                mid = tool_input.get("milestone_id") if isinstance(tool_input, dict) else None
                status = {
                    "plan_milestone_activate": "active",
                    "plan_milestone_done": "done",
                    "plan_milestone_failed": "failed",
                }[short]
                if mid:
                    self._proxy.milestoneUpsert.emit(str(mid), "", status, None, None)
            return

        self._proxy.toolUse.emit(tool_id, short, tool_input)

    def _handle_tool_result(self, block: ToolResultBlock) -> None:
        tool_id = getattr(block, "tool_use_id", "") or ""
        # PostToolUse — fire once per tool round-trip, before the panel-
        # routing branches. Decisions are informational at this stage; the
        # tool already ran. We swallow exceptions (handled in _run_hook).
        call = self._pending_tool_calls.pop(tool_id, None)
        if call is not None:
            tool_name, tool_input = call
            self._run_hook(
                "PostToolUse",
                {
                    "tool_name": tool_name,
                    "input": tool_input,
                    "output": block.content,
                },
            )
        plan_name = self._plan_tool_ids.pop(tool_id, None)
        if plan_name == "plan_emit":
            self._emit_plan_milestones(block)
            self._suppressed_tool_ids.discard(tool_id)
            return
        if plan_name == "exit_plan_mode":
            self._emit_plan_file_from_result(block)
            self._suppressed_tool_ids.discard(tool_id)
            # Flip the runtime out of plan mode for the *next* turn. We can't
            # mutate the live SDK options mid-turn, but clearing the override
            # and rebuilding the client picks up the user's configured mode.
            try:
                params = App.ParamGet(
                    "User parameter:BaseApp/Preferences/Mod/CADAgent"
                )
                user_mode = params.GetString("PermissionMode", "") or "default"
                if user_mode == "plan":
                    # If the user has "plan" wired as their default, bump to
                    # "default" for the rest of this session so the handoff
                    # actually takes effect.
                    params.SetString("PermissionMode", "default")
            except Exception:
                pass
            self._proxy.planExited.emit()
            return
        if tool_id in self._suppressed_tool_ids:
            self._suppressed_tool_ids.discard(tool_id)
            return
        self._proxy.toolResult.emit(
            tool_id,
            block.content,
            bool(getattr(block, "is_error", False) or False),
        )

    def _emit_plan_file_from_result(self, block: ToolResultBlock) -> None:
        """Parse ``exit_plan_mode``'s JSON result and surface the plan file."""
        content = block.content
        text = ""
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text") or ""
                    break
        elif isinstance(content, str):
            text = content
        if not text:
            return
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return
        path = (payload or {}).get("plan_file") or ""
        markdown = ""
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    markdown = f.read()
            except OSError:
                markdown = ""
        self._proxy.planFile.emit(str(path), markdown)

    def _emit_plan_milestones(self, block: ToolResultBlock) -> None:
        """Parse ``plan_emit``'s JSON result and fan out milestone rows."""
        content = block.content
        text = ""
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text") or ""
                    break
        elif isinstance(content, str):
            text = content
        if not text:
            return
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return
        plan = (payload or {}).get("plan") or {}
        milestones = plan.get("milestones") if isinstance(plan, dict) else None
        if not isinstance(milestones, list) or not milestones:
            return
        total = len(milestones)
        for i, m in enumerate(milestones):
            if not isinstance(m, dict):
                continue
            mid = m.get("id") or m.get("milestone_id")
            title = m.get("title") or ""
            status = m.get("status") or "pending"
            if not mid:
                continue
            self._proxy.milestoneUpsert.emit(
                str(mid), str(title), str(status), i + 1, total
            )

    # --- auto-compaction ------------------------------------------------

    def _model_name(self) -> str:
        """Return the configured model id (param store → env fallback)."""
        try:
            params = App.ParamGet(
                "User parameter:BaseApp/Preferences/Mod/CADAgent"
            )
            model = params.GetString("Model", "") or ""
        except Exception:
            model = ""
        return model or os.environ.get("ANTHROPIC_MODEL", "") or ""

    def _settings(self) -> dict:
        """Best-effort merge of user + project settings.json for compaction."""
        try:
            return hooks.load_settings(self._doc_dir())
        except Exception:
            return {}

    def _usage_to_dict(self, usage: Any) -> dict:
        """Coerce SDK usage (object or dict) into a flat int dict."""
        if usage is None:
            return {}
        out: dict[str, int] = {}
        for key in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            if isinstance(usage, dict):
                val = usage.get(key)
            else:
                val = getattr(usage, key, None)
            try:
                out[key] = int(val) if val is not None else 0
            except (TypeError, ValueError):
                out[key] = 0
        return out

    def _record_usage(self, msg, sid: str | None) -> None:
        """Accumulate tokens, persist to sessions.json, and arm auto-compact.

        Defensive: failures here must never break the turn boundary. Persistent
        token storage is best-effort; the in-memory ``_session_tokens`` is the
        source of truth for the threshold check.
        """
        usage = getattr(msg, "usage", None)
        try:
            self._session_tokens.accumulate(usage)
        except Exception:
            return
        usage_dict = self._usage_to_dict(usage)
        if sid:
            try:
                doc = self._active_doc_for_sessions()
                if doc is not None:
                    _sessions.update_tokens(doc, sid, usage_dict)
            except Exception:
                pass
        try:
            limit = _compaction.context_limit_for(
                self._model_name(), self._settings()
            )
            used = self._session_tokens.effective_context_used()
            self._proxy.contextUsage.emit(int(used), int(limit))
            if _compaction.should_auto_compact(used, limit, self._settings()):
                self._pending_auto_compact = True
        except Exception:
            pass

    def _active_doc_for_sessions(self):
        """Return the FreeCAD document used as the session-store key."""
        panel = self.panel
        doc = getattr(panel, "_bound_doc", None)
        if doc is None:
            doc = getattr(App, "ActiveDocument", None)
        return doc

    def _current_panel_sid(self) -> str | None:
        return (
            getattr(self.panel, "_current_session_id", None)
            or self._resume_sid
        )

    def _gather_rows_for_summary(self) -> list:
        """Snapshot the panel transcript for the summariser."""
        panel = self.panel
        getter = getattr(panel, "get_rows", None)
        if callable(getter):
            try:
                rows = getter()
                if isinstance(rows, list):
                    return list(rows)
            except Exception:
                pass
        try:
            model = getattr(panel, "_model", None) or getattr(panel, "model", None)
            if model is not None:
                rows = getattr(model, "_rows", None)
                if isinstance(rows, list):
                    return list(rows)
        except Exception:
            pass
        return []

    async def _run_compaction(self, reason: str) -> None:
        """Summarise the live transcript, fork the session, and reset tokens.

        Idempotent against re-entry — concurrent calls return early. Surfaces
        progress via ``compactingChanged`` and a final ``compactionEvent`` row
        on the panel.
        """
        if self._compacting:
            return
        self._compacting = True
        try:
            self._proxy.compactingChanged.emit(True)
        except Exception:
            pass
        try:
            rows = self._gather_rows_for_summary()
            tokens_before = self._session_tokens.effective_context_used()
            # TODO(Wave-3): pass real sdk_options so summarize_transcript can
            # spin up a one-shot query() for an LLM-authored summary.
            summary = _compaction.summarize_transcript(
                rows, self._model_name(), {}
            )
            sid = self._current_panel_sid()
            doc = self._active_doc_for_sessions()
            new_sid = sid or ""
            if doc is not None and sid:
                try:
                    new_sid = _compaction.compact_session(
                        doc, sid, rows, summary, fork=True
                    )
                except Exception:
                    new_sid = sid
            if new_sid:
                self._resume_sid = new_sid
            try:
                await self._aclose()
            except Exception:
                pass
            # Char→token rough heuristic so the post-compact UI doesn't read 0.
            self._session_tokens.reset(seed_size=max(0, len(summary) // 4))
            try:
                limit = _compaction.context_limit_for(
                    self._model_name(), self._settings()
                )
                used = self._session_tokens.effective_context_used()
                self._proxy.contextUsage.emit(int(used), int(limit))
                self._proxy.compactionEvent.emit({
                    "tokensBefore": int(tokens_before),
                    "tokensAfter": int(used),
                    "reason": reason,
                    "summary": summary,
                    "archivePath": "",
                })
            except Exception:
                pass
        finally:
            self._compacting = False
            try:
                self._proxy.compactingChanged.emit(False)
            except Exception:
                pass

    def request_compaction(self, reason: str = "manual") -> None:
        """Schedule ``_run_compaction`` on the worker loop (GUI-thread safe)."""
        if self._compacting:
            return
        loop = self._ensure_loop()
        try:
            asyncio.run_coroutine_threadsafe(
                self._run_compaction(reason), loop
            )
        except Exception:
            pass

    # --- entry points --------------------------------------------------

    def submit(
        self, user_text: str, attachments: list[str] | None = None
    ) -> None:
        if (
            self._current_future is not None
            and not self._current_future.done()
        ):
            self.panel.show_error("A previous turn is still running.")
            return
        try:
            snap = gui_thread.run_sync(_snapshot_active_doc, timeout=30.0)
        except Exception as exc:
            self.panel.show_error(f"Could not inspect active document: {exc}")
            return
        self._set_workspace_path(snap.get("path"))
        # UserPromptSubmit hook — a configured command can veto the turn
        # before any LLM round-trip. We surface the message via show_error
        # so the user sees why the prompt was dropped.
        ups = self._run_hook("UserPromptSubmit", {"prompt": user_text})
        if ups is not None and ups.decision == "block":
            self.panel.show_error(
                ups.message or "Prompt blocked by UserPromptSubmit hook"
            )
            return
        # Allocate this turn's index *before* dispatching, so the checkpoint
        # filename and the user-row meta agree even if SDK output races
        # ahead of the panel.
        turn_index = self._turn_index
        self._turn_index += 1
        self._checkpoint_turn(turn_index, self._workspace_path)
        self._tag_last_user_row(turn_index)
        # Auto-plan entry: if the user hasn't explicitly picked a mode and the
        # prompt looks complex, pin this turn to plan mode. The agent must
        # call ``exit_plan_mode`` to unlock execution.
        try:
            cur_mode = App.ParamGet(
                "User parameter:BaseApp/Preferences/Mod/CADAgent"
            ).GetString("PermissionMode", "") or "default"
        except Exception:
            cur_mode = "default"
        if cur_mode == "default" and _should_auto_plan(user_text):
            self._mode_override = "plan"
            # Rebuild the client so the next turn picks up the override.
            if self.client is not None and self._loop is not None:
                asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)
        wrapped = f"{_build_preamble(snap)}\n\n{user_text}"
        # Stash for the overflow-retry path: ``_ask`` resubmits this exactly
        # once if the SDK raises a context-overflow error mid-turn.
        self._last_user_prompt = wrapped
        self._last_user_attachments = list(attachments) if attachments else None
        self._overflow_retried = False
        loop = self._ensure_loop()
        self._current_future = asyncio.run_coroutine_threadsafe(
            self._ask(wrapped, attachments), loop
        )

    def _current_sid(self) -> str | None:
        """Best-effort session id for checkpoint keying.

        Prefers the panel's most recent ``ResultMessage`` sid; falls back to
        a queued ``_resume_sid`` so the very first turn after ``/resume``
        still keys against the right session.
        """
        sid = getattr(self.panel, "_current_session_id", None)
        return sid or self._resume_sid

    def _checkpoint_turn(self, turn_index: int, doc_path: str | None) -> None:
        """Save the active doc to the checkpoint store; never raise."""
        if _checkpoints is None or not doc_path:
            return
        sid = self._current_sid()
        if not sid:
            # Pre-session-id turn: nothing to key against yet.
            return
        try:
            _checkpoints.save(sid, turn_index, doc_path)
        except Exception as exc:
            try:
                App.Console.PrintWarning(
                    f"CAD Agent: checkpoint save failed for turn "
                    f"{turn_index}: {exc}\n"
                )
            except Exception:
                pass

    def _tag_last_user_row(self, turn_index: int) -> None:
        """Stamp ``turn_index`` onto the most recent user row's meta dict.

        The QML panel adds the user row synchronously before calling
        ``runtime.submit``, so the last user row in the model is the one we
        just received. Failure here is non-fatal — the checkpoint is keyed
        by ``turn_index`` regardless of UI state.
        """
        try:
            model = getattr(self.panel, "_model", None)
            if model is None:
                return
            rows = getattr(model, "_rows", None)
            if not rows:
                return
            for i in range(len(rows) - 1, -1, -1):
                if rows[i].get("kind") == "user":
                    meta = dict(rows[i].get("meta") or {})
                    meta["turn_index"] = turn_index
                    rows[i]["meta"] = meta
                    if hasattr(model, "_emit_changed"):
                        model._emit_changed(i)
                    return
        except Exception:
            pass

    def interrupt(self) -> None:
        if self._loop is None or self.client is None:
            return

        async def _interrupt():
            try:
                await self.client.interrupt()
            except Exception:
                pass

        asyncio.run_coroutine_threadsafe(_interrupt(), self._loop)

    def _turn_in_flight(self) -> bool:
        return (
            self._current_future is not None
            and not self._current_future.done()
        )

    def start_new_session(self) -> bool:
        if self._turn_in_flight():
            return False
        self._resume_sid = None
        self._turn_index = 0
        clear_session_allowlist()
        if self.client is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)
        return True

    def resume_session(self, session_id: str) -> bool:
        """Tear down the current client and arrange the next turn to resume ``session_id``."""
        if self._turn_in_flight():
            return False
        self._resume_sid = session_id or None
        # Resumed sessions continue numbering from "after the last persisted
        # turn"; we don't have that count here, so reset to 0 and let the
        # next turn start the new branch's count. W1-B will fix this up
        # when it re-keys to the resumed sid.
        self._turn_index = 0
        if self.client is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)
        return True

    def rebuild_for_mode(self) -> bool:
        """Drop the live client so the next turn re-reads ``PermissionMode``.

        The param is updated by ``QmlChatBridge.set_permission_mode``; we just
        need to ensure the SDK options are rebuilt. ``_resume_sid`` is
        preserved so a resumed session stays resumed across mode switches.
        """
        if self._turn_in_flight():
            return False
        if self.client is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)
        return True

    async def _aclose(self) -> None:
        if self.client is not None:
            try:
                await self.client.__aexit__(None, None, None)
            finally:
                self.client = None
        try:
            await worker_client.close_shared()
        except Exception:
            pass

    async def rewind_to(
        self,
        row_id: str,
        fork: bool,
        new_user_text: str | None = None,
    ) -> str:
        """Rewind the conversation to ``row_id``.

        Closes the live SDK client, truncates the persisted CADAgent rows
        and the SDK transcript JSONL, optionally restores the workspace
        ``.FCStd`` snapshot for the matching turn, and arms the next turn to
        resume the (possibly forked) session.

        Returns the (possibly new) sid. ``new_user_text`` is reserved for
        callers that compose a new prompt during rewind; the panel layer
        currently issues the new prompt itself after this method returns.

        Defensive: if any step fails (no rows persisted yet, missing SDK
        JSONL, no checkpoints module) we fall through and return the best
        sid we have.
        """
        del new_user_text  # reserved; see docstring.

        await self._aclose()

        panel = self.panel
        doc = (
            getattr(panel, "_bound_doc", None)
            or getattr(App, "ActiveDocument", None)
        )
        sid = getattr(panel, "_current_session_id", None) or self._resume_sid
        if not sid or doc is None:
            return sid or ""

        row_index = -1
        turn_index: int | None = None
        try:
            model = panel.model  # type: ignore[attr-defined]
            row_by_id = getattr(model, "_row_by_id", {}) or {}
            row_index = int(row_by_id.get(row_id, -1))
            if 0 <= row_index < len(model._rows):
                meta = (model._rows[row_index] or {}).get("meta") or {}
                ti = meta.get("turn_index")
                if isinstance(ti, int):
                    turn_index = ti
        except Exception:
            row_index = -1

        if row_index < 0:
            # Row id no longer in the model — refuse rather than wiping
            # the transcript on a stale click.
            return sid

        # Rewind/edit semantics: drop the targeted user row and everything
        # after it. The caller resubmits a fresh prompt (edit/fork) or the
        # user types a new one in the composer (plain rewind).
        keep_through = row_index - 1

        try:
            from .. import rewind as _rewind
            new_sid = _rewind.truncate_session(doc, sid, keep_through, fork)
        except Exception:
            new_sid = sid

        # Workspace restore is keyed by the *original* sid — that is where
        # the checkpoint was saved, even when forking into a new sid.
        if turn_index is not None:
            try:
                from .. import checkpoints as _checkpoints
                doc_path = getattr(doc, "FileName", "") or ""
                if doc_path and _checkpoints.restore(sid, turn_index, doc_path):
                    self._proxy.docReloadRequested.emit(doc_path)
            except Exception:
                pass

        self._resume_sid = new_sid
        # Re-key future checkpoints from the restore point.
        if isinstance(turn_index, int):
            self._turn_index = turn_index
        return new_sid

    def aclose(self) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)
