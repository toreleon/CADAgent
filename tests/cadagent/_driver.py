"""Headless driver run INSIDE FreeCADCmd.

Loads the CADAgent module, submits a single prompt, captures the tool-call
trace + final document topology into a JSON report, and exits. Tests invoke
this via ``FreeCADCmd -c "exec(open(_driver.py).read())"`` — see
``tests/cadagent/replay.py::run_agent``.

All configuration comes from environment variables to keep the invocation
shell simple:

    CADAGENT_TEST_PROMPT   required — the user prompt to submit
    CADAGENT_TEST_OUT      required — path to write the JSON report to
    CADAGENT_TEST_DOC      optional — path to an existing .FCStd to open first
    CADAGENT_TEST_SAVE_AS  optional — if set, save the doc to this path at end
    CADAGENT_TEST_TIMEOUT  optional — seconds, default 180
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

import FreeCAD as App

try:
    from PySide6 import QtCore
except ImportError:  # pragma: no cover
    from PySide2 import QtCore


def _emit(path: str, payload: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
    except Exception:
        sys.stderr.write(f"[driver] failed to write report: {traceback.format_exc()}\n")


def _doc_topology(doc) -> dict:
    """Snapshot every object in the doc with a real finite-volume solid.

    Filters out PartDesign datum primitives (Origin, axes, reference planes)
    whose bboxes extend to ±1e100 — they clutter assertions without carrying
    actual design geometry.
    """
    out: list[dict] = []
    if doc is None:
        return {"objects": out}
    for obj in list(doc.Objects):
        entry: dict = {"name": obj.Name, "label": obj.Label, "type": obj.TypeId}
        shape = getattr(obj, "Shape", None)
        if shape is not None:
            try:
                bb = shape.BoundBox
                dims = (bb.XLength, bb.YLength, bb.ZLength)
                # Datum planes/axes: infinite extents or zero-volume reference geometry.
                if any(abs(d) > 1e50 for d in dims):
                    continue
                volume = float(shape.Volume)
                if volume <= 0.0:
                    continue
                entry["bbox"] = {
                    "xmin": bb.XMin, "ymin": bb.YMin, "zmin": bb.ZMin,
                    "xmax": bb.XMax, "ymax": bb.YMax, "zmax": bb.ZMax,
                    "xlen": dims[0], "ylen": dims[1], "zlen": dims[2],
                }
                entry["volume"] = volume
                entry["is_valid_solid"] = bool(shape.isValid())
            except Exception:
                continue
        else:
            continue
        out.append(entry)
    return {"objects": out}


class _TracePanel(QtCore.QObject):
    """Minimal panel: records every tool call and message for the report."""

    def __init__(self):
        super().__init__()
        self._turn_done = False
        self.trace: list[dict] = []
        self.errors: list[str] = []
        self._tool_names: dict[str, str] = {}

    @property
    def turn_done(self) -> bool:
        return self._turn_done

    def attach_runtime(self, runtime) -> None:
        pass

    def append_assistant_text(self, text: str) -> None:
        self.trace.append({"kind": "assistant_text", "text": text})

    def append_thinking(self, text: str) -> None:
        self.trace.append({"kind": "thinking", "text": text})

    def announce_tool_use(self, tool_use_id: str, name: str, tool_input) -> None:
        self._tool_names[tool_use_id or ""] = name
        try:
            inp = dict(tool_input) if isinstance(tool_input, dict) else tool_input
        except Exception:
            inp = str(tool_input)
        self.trace.append({"kind": "tool_use", "id": tool_use_id, "name": name, "input": inp})

    def announce_tool_result(self, tool_use_id: str, content, is_error: bool) -> None:
        name = self._tool_names.pop(tool_use_id or "", None)
        self.trace.append({
            "kind": "tool_result",
            "id": tool_use_id,
            "name": name,
            "is_error": bool(is_error),
        })

    def record_result(self, msg) -> None:
        usage = getattr(msg, "usage", None) or {}
        if not isinstance(usage, dict):
            usage = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }
        self.trace.append({"kind": "result", "usage": usage})

    def mark_turn_complete(self) -> None:
        self._turn_done = True

    def show_error(self, message: str) -> None:
        self.errors.append(message)
        self.trace.append({"kind": "error", "message": message})

    def _debug_raw(self, msg) -> None:
        """Capture raw SDK messages for diagnosis of empty-AssistantMessage bugs."""
        self.trace.append({
            "kind": "raw",
            "type": type(msg).__name__,
            "repr": repr(msg)[:2000],
        })

    def on_session_changed(self, session_id: str) -> None:
        self.trace.append({"kind": "session", "id": session_id})

    def request_permission_threadsafe(self, tool_name, tool_input, cf_future):
        from agent.permissions import Decision
        if not cf_future.done():
            cf_future.set_result(Decision(allowed=True, reason="test-auto"))

    def ask_user_question_threadsafe(self, questions, cf_future):
        answers = [
            {"header": (q or {}).get("header", ""), "selected": None, "skipped": True}
            for q in (questions or [])
        ]
        if not cf_future.done():
            cf_future.set_result(answers)


def main() -> int:
    prompt = os.environ.get("CADAGENT_TEST_PROMPT", "").strip()
    out_path = os.environ.get("CADAGENT_TEST_OUT", "").strip()
    doc_in = os.environ.get("CADAGENT_TEST_DOC", "").strip()
    save_as = os.environ.get("CADAGENT_TEST_SAVE_AS", "").strip()
    timeout = float(os.environ.get("CADAGENT_TEST_TIMEOUT", "180"))

    if not prompt or not out_path:
        sys.stderr.write("[driver] CADAGENT_TEST_PROMPT and CADAGENT_TEST_OUT required\n")
        return 2

    # Mirror test env into the param store so AgentRuntime uses the test's
    # proxy / model. runtime._resolve_model() has no env fallback — its only
    # source of truth is the param store — so we write the env value in here.
    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/CADAgent")
    params.SetString("PermissionMode", "bypassPermissions")
    if os.environ.get("ANTHROPIC_MODEL"):
        params.SetString("Model", os.environ["ANTHROPIC_MODEL"])
    if os.environ.get("ANTHROPIC_BASE_URL"):
        params.SetString("BaseURL", os.environ["ANTHROPIC_BASE_URL"])
    if os.environ.get("ANTHROPIC_API_KEY"):
        params.SetString("ApiKey", os.environ["ANTHROPIC_API_KEY"])

    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    from agent import gui_thread
    gui_thread.init_dispatcher()

    doc = None
    if doc_in:
        doc = App.openDocument(doc_in)
    else:
        doc = App.newDocument("TestDoc")

    from agent.runtime import AgentRuntime

    panel = _TracePanel()
    runtime = AgentRuntime(panel)
    panel.attach_runtime(runtime)
    runtime.bind_document(doc)

    # Monkey-patch _route_message to also capture raw SDK messages.
    if os.environ.get("CADAGENT_TEST_DEBUG_RAW"):
        _orig_route = runtime._route_message
        def _route_with_raw(msg):
            panel._debug_raw(msg)
            _orig_route(msg)
        runtime._route_message = _route_with_raw

    t0 = time.monotonic()
    runtime.submit(prompt)
    try:
        while not panel.turn_done and (time.monotonic() - t0) < timeout:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
    except KeyboardInterrupt:
        panel.show_error("interrupted")

    elapsed = time.monotonic() - t0
    timed_out = not panel.turn_done

    topology = None
    try:
        topology = _doc_topology(App.ActiveDocument)
        if save_as and App.ActiveDocument is not None:
            App.ActiveDocument.saveAs(save_as)
    except Exception:
        panel.errors.append(f"topology capture failed: {traceback.format_exc()}")

    _emit(out_path, {
        "prompt": prompt,
        "doc_in": doc_in or None,
        "doc_out": save_as or None,
        "elapsed_s": elapsed,
        "timed_out": timed_out,
        "trace": panel.trace,
        "errors": panel.errors,
        "topology": topology,
    })

    # Clean shutdown to avoid background client hanging FreeCAD process.
    try:
        runtime.aclose()
    except Exception:
        pass
    return 0 if (not timed_out and not panel.errors) else 1


if __name__ == "__main__":
    sys.exit(main())
