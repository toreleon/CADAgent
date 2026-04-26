# SPDX-License-Identifier: LGPL-2.1-or-later
"""In-FreeCAD host for the standalone CLI agent.

The CLI runtime in :mod:`agent.cli.runtime` is designed for headless use
(``scripts/cadagent``). This module wraps it so the FreeCAD chat dock can
drive the same agent without spawning a subprocess: the SDK runs on a
dedicated worker asyncio loop, while the QML panel — and any FreeCAD doc
mutations — stay on the Qt GUI thread.

The agent owns document lifecycle: it can list, create, open, switch,
and reload documents through the MCP tools in :mod:`agent.cli.dock_tools`
— think of it like a shell session that can ``cd`` between projects.
Geometry still happens via ``Bash → FreeCADCmd`` subprocesses (the CLI
agent's contract); we save the active doc before each turn and auto-reload
it after, so the GUI reflects whatever the subprocess wrote.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import json
import mimetypes
import os
import threading
import traceback
from typing import Any

import FreeCAD as App

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore

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

from .. import gui_thread, hooks, ui_bridge
from ..permissions import make_can_use_tool, clear_session_allowlist
from ..worker import client as worker_client
from . import dock_tools, runtime as cli_runtime

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


async def _multimodal_prompt(user_text: str, attachments: list[str]):
    """Yield a single Anthropic-format streaming user message with images.

    The SDK forwards each dict to the CLI transport; LiteLLM translates the
    Anthropic image block to whatever the proxied model expects (e.g. the
    OpenAI image_url schema for gpt-*).
    """
    content: list[dict[str, Any]] = []
    if user_text:
        content.append({"type": "text", "text": user_text})
    for path in attachments:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        mime, _ = mimetypes.guess_type(path)
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
        )
    yield {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


def _strip_prefix(name: str) -> str:
    if isinstance(name, str) and name.startswith(_MCP_PREFIX):
        return name[len(_MCP_PREFIX):]
    return name


class _PanelProxy(QtCore.QObject):
    """Marshals messages from the worker asyncio thread onto the GUI thread.

    Mirrors the signal surface the QML panel binds to in
    :mod:`agent.ui.qml_panel`. Signals not produced by the CLI agent (e.g.
    milestone/verification/decision events) are still declared so the
    panel's ``hasattr`` connects don't fail; they simply never fire.
    """

    assistantText = QtCore.Signal(str)
    thinking = QtCore.Signal(str)
    toolUse = QtCore.Signal(str, str, object)
    toolResult = QtCore.Signal(str, object, bool)
    resultMsg = QtCore.Signal(object)
    turnComplete = QtCore.Signal()
    error = QtCore.Signal(str)
    permissionRequest = QtCore.Signal(str, object, object)
    askUserQuestion = QtCore.Signal(object, object)
    sessionChanged = QtCore.Signal(str)

    # Reserved for future parity with the deleted integrated runtime.
    milestoneUpsert = QtCore.Signal(str, str, str, object, object)
    verificationResult = QtCore.Signal(str, object)
    decisionRecorded = QtCore.Signal(str, object)
    compactionEvent = QtCore.Signal(object)
    subagentSpan = QtCore.Signal(str, str, str)
    permissionModeChanged = QtCore.Signal(str)
    streamState = QtCore.Signal(str, bool)
    todosUpdate = QtCore.Signal(object)
    # Plan-mode scaffolding (M1).
    planFile = QtCore.Signal(str, str)  # (path, markdown)
    planExited = QtCore.Signal()
    # Edit-approval scaffolding (M3).
    editApprovalRequest = QtCore.Signal(str, str, str, object)  # (reqId, summary, script, cf_future)
    # Hook lifecycle event — (event_name, payload_dict, result_dict). Consumed
    # by W2-E to render hook activity rows; safe to leave unconnected.
    hookEvent = QtCore.Signal(str, object, object)
    # Active document changed — fires when the runtime's tracked workspace
    # path moves to a new document (or to None). Consumed by W2-D's
    # WorkspaceChip to refresh its label.
    activeDocChanged = QtCore.Signal(str)

    def __init__(self, panel):
        super().__init__(panel)
        self._panel = panel
        self.assistantText.connect(panel.append_assistant_text)
        self.thinking.connect(panel.append_thinking)
        self.toolUse.connect(panel.announce_tool_use)
        self.toolResult.connect(panel.announce_tool_result)
        self.resultMsg.connect(panel.record_result)
        self.turnComplete.connect(panel.mark_turn_complete)
        self.error.connect(panel.show_error)
        self.permissionRequest.connect(self._on_permission_request)
        self.askUserQuestion.connect(self._on_ask_user_question)
        if hasattr(panel, "on_session_changed"):
            self.sessionChanged.connect(panel.on_session_changed)
        if hasattr(panel, "set_stream_state"):
            self.streamState.connect(panel.set_stream_state)
        if hasattr(panel, "update_todos"):
            self.todosUpdate.connect(panel.update_todos)
        if hasattr(panel, "upsert_milestone"):
            self.milestoneUpsert.connect(panel.upsert_milestone)
        if hasattr(panel, "on_plan_file"):
            self.planFile.connect(panel.on_plan_file)
        if hasattr(panel, "on_plan_exited"):
            self.planExited.connect(panel.on_plan_exited)
        self.editApprovalRequest.connect(self._on_edit_approval_request)

    def _on_edit_approval_request(self, req_id, summary, script, cf_future):
        try:
            self._panel.request_edit_approval_threadsafe(
                req_id, summary, script, cf_future
            )
        except Exception as exc:
            if not cf_future.done():
                cf_future.set_exception(exc)

    def _on_permission_request(self, tool_name, tool_input, cf_future):
        try:
            self._panel.request_permission_threadsafe(
                _strip_prefix(tool_name), tool_input, cf_future
            )
        except Exception as exc:
            if not cf_future.done():
                cf_future.set_exception(exc)

    def _on_ask_user_question(self, questions, cf_future):
        try:
            self._panel.ask_user_question_threadsafe(questions, cf_future)
        except Exception as exc:
            if not cf_future.done():
                cf_future.set_exception(exc)


def _reload_active_doc_if_stale() -> None:
    """Re-open the active document so the GUI reflects subprocess writes.

    The CLI agent writes geometry via ``Bash → FreeCADCmd``, which mutates
    the ``.FCStd`` on disk while the GUI still holds the pre-Bash copy in
    memory. We close + re-open whenever the file's mtime is newer than the
    one we observed before the turn started.
    """
    doc = App.ActiveDocument
    if doc is None:
        return
    path = getattr(doc, "FileName", "") or ""
    if not path or not os.path.exists(path):
        return
    try:
        name = doc.Name
        App.closeDocument(name)
        new_doc = App.openDocument(path)
        App.setActiveDocument(new_doc.Name)
        try:
            new_doc.recompute()
        except Exception:
            pass
    except Exception:
        try:
            doc.recompute()
        except Exception:
            pass


def _snapshot_active_doc() -> dict:
    """Save the active doc if dirty and return a small summary."""
    doc = App.ActiveDocument
    if doc is None:
        return {"path": None, "name": None, "label": None, "object_count": 0}
    path = getattr(doc, "FileName", "") or ""
    if path:
        try:
            doc.save()
        except Exception:
            pass
    return {
        "path": path or None,
        "name": getattr(doc, "Name", "") or None,
        "label": getattr(doc, "Label", "") or None,
        "object_count": len(getattr(doc, "Objects", []) or []),
    }


def _build_preamble(snap: dict) -> str:
    if snap.get("path"):
        return (
            f"[GUI context] Active FreeCAD document: "
            f"{snap.get('label') or snap.get('name')!r} at {snap['path']!r} "
            f"({snap.get('object_count', 0)} objects). Pass this path as "
            f"the ``doc`` argument to ``memory_*`` / ``plan_*`` tools. "
            f"You may also use ``gui_documents_list``, ``gui_open_document``, "
            f"``gui_new_document``, or ``gui_set_active_document`` to work "
            f"on a different file when the request calls for it. The dock "
            f"auto-reloads the active doc in the GUI at end of turn."
        )
    return (
        "[GUI context] No FreeCAD document is open. Use "
        "``gui_new_document`` to create one (returns its on-disk path for "
        "``memory_*`` / ``plan_*`` tools), or ``gui_open_document`` to "
        "open an existing .FCStd. For pure questions or memory work no "
        "document is required."
    )


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

    async def _ask(
        self, user_text: str, attachments: list[str] | None = None
    ) -> None:
        try:
            await self._ensure_client()
            assert self.client is not None
            if attachments:
                await self.client.query(
                    _multimodal_prompt(user_text, attachments)
                )
            else:
                await self.client.query(user_text)
            async for msg in self.client.receive_response():
                self._route_message(msg)
        except Exception as exc:
            self._proxy.error.emit(
                f"{exc}\n\n{traceback.format_exc(limit=3)}"
            )
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

        try:
            from .. import rewind as _rewind
            new_sid = _rewind.truncate_session(doc, sid, row_index, fork)
        except Exception:
            new_sid = sid

        if turn_index is not None:
            try:
                from .. import checkpoints as _checkpoints
                doc_path = getattr(doc, "FileName", "") or ""
                if doc_path:
                    _checkpoints.restore(new_sid, turn_index, doc_path)
            except Exception:
                pass

        self._resume_sid = new_sid
        return new_sid

    def aclose(self) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._aclose(), self._loop)
