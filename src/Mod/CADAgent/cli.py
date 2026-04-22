# SPDX-License-Identifier: LGPL-2.1-or-later
"""Single-shot CLI for driving CADAgent headlessly.

Usage::

    scripts/cadagent-cli "your prompt here"

Takes one prompt, forces ``PermissionMode = bypassPermissions`` so the agent
runs without approval gates, streams everything it does (assistant text,
thinking, tool calls with inputs, tool results) to stdout, and exits when
the turn completes. Built to be cheap to spin up during development —
faster feedback than launching the GUI.

``AskUserQuestion`` is auto-skipped; if you want to answer questions, use
the QML panel instead.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import FreeCAD as App

try:
    from PySide6 import QtCore
except ImportError:  # pragma: no cover
    from PySide2 import QtCore


# --- ANSI helpers --------------------------------------------------------

_NO_COLOR = not sys.stdout.isatty() or bool(os.environ.get("NO_COLOR"))


def _c(seq: str) -> str:
    return "" if _NO_COLOR else seq


DIM    = _c("\033[2m")
BOLD   = _c("\033[1m")
ITAL   = _c("\033[3m")
ACCENT = _c("\033[38;5;39m")
GREEN  = _c("\033[32m")
RED    = _c("\033[31m")
RESET  = _c("\033[0m")


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _preview(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _truncate(value.replace("\n", " "), limit)
    if isinstance(value, list):
        parts = []
        for block in value:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block, default=str))
        return _truncate(" ".join(parts).replace("\n", " "), limit)
    try:
        return _truncate(json.dumps(value, default=str), limit)
    except Exception:
        return _truncate(str(value), limit)


# --- Panel ---------------------------------------------------------------


class CliPanel(QtCore.QObject):
    """Terminal panel — prints every event from AgentRuntime to stdout.

    No interactive prompts: permissions are bypassed via pref, and
    ``AskUserQuestion`` is auto-skipped. The CLI is for tracing agent
    trajectories, not for conversational use.
    """

    def __init__(self):
        super().__init__()
        self._assistant_open = False
        self._thinking_open = False
        self._turn_done = False
        self._tool_names: dict[str, str] = {}

    @property
    def turn_done(self) -> bool:
        return self._turn_done

    def attach_runtime(self, runtime) -> None:
        pass  # no interactive surface needs a runtime reference

    # --- streaming text ------------------------------------------------

    def append_assistant_text(self, text: str) -> None:
        if self._thinking_open:
            sys.stdout.write(RESET + "\n")
            self._thinking_open = False
        if not self._assistant_open:
            sys.stdout.write(f"\n{ACCENT}⏺{RESET} ")
            self._assistant_open = True
        sys.stdout.write(text)
        sys.stdout.flush()

    def append_thinking(self, text: str) -> None:
        if self._assistant_open:
            sys.stdout.write("\n")
            self._assistant_open = False
        if not self._thinking_open:
            sys.stdout.write(f"\n{DIM}{ITAL}✻ ")
            self._thinking_open = True
        sys.stdout.write(text)
        sys.stdout.flush()

    def _close_streams(self) -> None:
        if self._assistant_open or self._thinking_open:
            sys.stdout.write(RESET + "\n")
        self._assistant_open = False
        self._thinking_open = False

    # --- tool calls ----------------------------------------------------

    def announce_tool_use(self, tool_use_id: str, name: str, tool_input) -> None:
        if name == "AskUserQuestion":
            return
        self._close_streams()
        self._tool_names[tool_use_id or ""] = name
        inp = _preview(tool_input, 200)
        body = f"{name}({DIM}{inp}{RESET})" if inp else f"{name}()"
        sys.stdout.write(f"{ACCENT}⏺{RESET} {BOLD}{body}{RESET}\n")
        sys.stdout.flush()

    def announce_tool_result(self, tool_use_id: str, content, is_error: bool) -> None:
        if tool_use_id and tool_use_id not in self._tool_names:
            return
        self._tool_names.pop(tool_use_id or "", None)
        color = RED if is_error else GREEN
        label = "ERR" if is_error else "OK"
        body = _preview(content, 400)
        sys.stdout.write(f"  {DIM}⎿{RESET} {color}{label}{RESET} {DIM}{body}{RESET}\n")
        sys.stdout.flush()

    # --- turn lifecycle ------------------------------------------------

    def record_result(self, msg) -> None:
        self._close_streams()
        cost = getattr(msg, "total_cost_usd", None) or getattr(msg, "cost_usd", None)
        usage = getattr(msg, "usage", None)
        toks = None
        if usage is not None:
            in_t = getattr(usage, "input_tokens", None)
            out_t = getattr(usage, "output_tokens", None)
            if in_t is None and isinstance(usage, dict):
                in_t = usage.get("input_tokens")
                out_t = usage.get("output_tokens")
            if in_t is not None or out_t is not None:
                toks = (in_t or 0) + (out_t or 0)
        parts = []
        if toks is not None:
            parts.append(f"{toks:,} tok")
        if cost is not None:
            parts.append(f"${cost:.4f}")
        if parts:
            sys.stdout.write(f"{DIM}  {' · '.join(parts)}{RESET}\n")
            sys.stdout.flush()

    def mark_turn_complete(self) -> None:
        self._close_streams()
        self._turn_done = True

    def show_error(self, message: str) -> None:
        self._close_streams()
        sys.stdout.write(f"{RED}!{RESET} {message}\n")
        sys.stdout.flush()

    # --- non-interactive stubs ----------------------------------------

    def request_permission_threadsafe(
        self, tool_name: str, tool_input: dict, cf_future
    ) -> None:
        # bypassPermissions should prevent this from firing, but approve if it
        # ever does so the agent doesn't hang.
        from agent.permissions import Decision
        if not cf_future.done():
            cf_future.set_result(Decision(allowed=True, reason="cli-auto"))

    def ask_user_question_threadsafe(self, questions, cf_future) -> None:
        self._close_streams()
        sys.stdout.write(f"{DIM}  (auto-skipping AskUserQuestion — CLI non-interactive){RESET}\n")
        sys.stdout.flush()
        answers = [
            {"header": (q or {}).get("header", ""), "selected": None, "skipped": True}
            for q in (questions or [])
        ]
        if not cf_future.done():
            cf_future.set_result(answers)


# --- Entrypoint -----------------------------------------------------------


def _force_bypass_permissions() -> None:
    """Force bypassPermissions for this CLI run.

    Writes into FreeCAD's parameter store (which ``AgentRuntime`` reads). We
    don't restore the previous value on exit — the CLI always runs unattended,
    so sticky bypass in the CLI's redirected $HOME is the desired behaviour.
    """
    App.ParamGet(
        "User parameter:BaseApp/Preferences/Mod/CADAgent"
    ).SetString("PermissionMode", "bypassPermissions")


def main(prompt: str | None = None) -> int:
    if prompt is None:
        prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        sys.stderr.write("usage: cadagent-cli \"<prompt>\"\n")
        return 2

    _force_bypass_permissions()

    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    from agent import gui_thread
    gui_thread.init_dispatcher()

    from agent.runtime import AgentRuntime

    panel = CliPanel()
    runtime = AgentRuntime(panel)
    panel.attach_runtime(runtime)

    sys.stdout.write(f"{ACCENT}>{RESET} {prompt}\n")
    sys.stdout.flush()

    runtime.submit(prompt)
    try:
        while not panel.turn_done:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
    except KeyboardInterrupt:
        sys.stdout.write(f"\n{DIM}interrupting…{RESET}\n")
        try:
            runtime.interrupt()
        except Exception:
            pass
        while not panel.turn_done:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
