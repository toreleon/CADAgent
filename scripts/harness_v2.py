# SPDX-License-Identifier: LGPL-2.1-or-later
"""Harness test for v2 verbs — verifies tool calls actually take effect.

Runs under FreeCADCmd. Bypasses the Claude SDK entirely and drives the v2
dispatcher (``agent.verbs._dispatch``) directly, asserting that each call
mutates FreeCAD state as expected (documents exist, objects created,
properties set, sketches constrained, etc.).

The point is to distinguish two failure modes:
  (a) the v2 verb plumbing itself is broken (wrong param folding, passthrough
      wiring, transaction wrapper, etc.), vs.
  (b) the SDK → dispatcher edge is broken (tool names, allowed_tools, hook
      rejections, permission gating).

If every case here passes, (a) is ruled out and the hang is in (b).
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback


def _print(tag: str, msg: str = "") -> None:
    sys.stdout.write(f"[{tag}] {msg}\n")
    sys.stdout.flush()


def _extract(result: dict) -> dict:
    """Pull the JSON payload out of an MCP-shaped {'content': [...]} dict."""
    try:
        text = result["content"][0]["text"]
        return json.loads(text)
    except Exception:
        return {"__raw__": result}


class Harness:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.errors: list[str] = []
        self._loop = asyncio.new_event_loop()

    def call(self, verb: str, kind: str, **args) -> dict:
        from agent import verbs as cad_verbs
        payload = {"kind": kind, **args}
        result = self._loop.run_until_complete(cad_verbs._dispatch(verb, payload))
        return _extract(result)

    def check(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passed += 1
            _print("PASS", f"{label}")
        else:
            self.failed += 1
            _print("FAIL", f"{label}  {detail}")
            self.errors.append(f"{label}: {detail}")

    def section(self, name: str) -> None:
        _print("----", name)


def _setup_qt_and_dispatcher():
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets  # type: ignore
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv or [""])
    from agent import gui_thread
    gui_thread.init_dispatcher()
    return app


def main() -> int:
    app = _setup_qt_and_dispatcher()

    # Registry population + dispatcher import.
    from agent import registry
    from agent import verbs as cad_verbs  # noqa: F401 — import runs providers.load_all()

    import FreeCAD as App

    h = Harness()

    # Drive the Qt event loop while an async dispatch is running so `run_sync`
    # callbacks can hop to this thread. We only need it during dispatch, but
    # the loop we use is a new asyncio loop running on THIS thread — since
    # run_sync uses a dispatcher bound to this QApplication, executing the
    # coroutine blocks, and the dispatcher signal can't be delivered. We fix
    # this by running dispatches on a worker thread and processing Qt events
    # here.

    import concurrent.futures
    import threading

    def call_via_worker(verb: str, kind: str, **args) -> dict:
        """Run ``_dispatch`` on a worker thread so run_sync can pump the GUI thread."""
        from agent import verbs as cad_verbs
        payload = {"kind": kind, **args}
        done = threading.Event()
        box: dict = {}

        def worker():
            loop = asyncio.new_event_loop()
            try:
                r = loop.run_until_complete(cad_verbs._dispatch(verb, payload))
                box["result"] = r
            except Exception as exc:
                box["exc"] = exc
                box["tb"] = traceback.format_exc()
            finally:
                loop.close()
                done.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        try:
            from PySide6 import QtCore
        except ImportError:
            from PySide2 import QtCore  # type: ignore
        while not done.is_set():
            app.processEvents(QtCore.QEventLoop.AllEvents, 20)
        if "exc" in box:
            raise RuntimeError(f"dispatch raised: {box['exc']}\n{box.get('tb','')}")
        return _extract(box["result"])

    h.call = call_via_worker  # type: ignore[assignment]

    # -----------------------------------------------------------------
    # Registry sanity
    # -----------------------------------------------------------------
    h.section("registry")
    all_kinds = registry.all_kinds()
    h.check("registry populated", len(all_kinds) >= 30, f"got {len(all_kinds)} kinds")
    by_verb = {v: len(registry.kinds_for(v)) for v in registry.VERBS}
    _print("INFO", f"kinds per verb: {by_verb}")
    for verb in ("create", "modify", "inspect", "verify", "io", "memory", "plan", "exec", "delete", "render"):
        h.check(f"verb has kinds: {verb}", by_verb[verb] > 0)

    # -----------------------------------------------------------------
    # inspect — no doc needed
    # -----------------------------------------------------------------
    h.section("inspect.document.list (no doc)")
    r = h.call("inspect", "document.list")
    h.check("document.list ok", r.get("ok") is True, str(r)[:200])

    # -----------------------------------------------------------------
    # create document
    # -----------------------------------------------------------------
    h.section("create.document")
    r = h.call("create", "document", params={"name": "HarnessDoc"})
    h.check("create.document ok", r.get("ok") is True, str(r)[:200])
    h.check("doc present in App", "HarnessDoc" in App.listDocuments())

    # -----------------------------------------------------------------
    # create part.box  → primitive Part::Box
    # -----------------------------------------------------------------
    h.section("create.part.box")
    r = h.call("create", "part.box", params={"length": 20, "width": 10, "height": 5, "name": "Box1", "doc": "HarnessDoc"})
    h.check("part.box ok", r.get("ok") is True, str(r)[:200])
    doc = App.getDocument("HarnessDoc")
    box_obj = doc.getObject("Box1") if doc else None
    h.check("Box1 object exists", box_obj is not None)
    if box_obj is not None:
        h.check("Box1 length=20mm", abs(float(box_obj.Length) - 20) < 1e-6, f"got {box_obj.Length}")
        h.check("Box1 width=10mm", abs(float(box_obj.Width) - 10) < 1e-6, f"got {box_obj.Width}")
        h.check("Box1 height=5mm", abs(float(box_obj.Height) - 5) < 1e-6, f"got {box_obj.Height}")

    # -----------------------------------------------------------------
    # create.part.cylinder
    # -----------------------------------------------------------------
    h.section("create.part.cylinder")
    r = h.call("create", "part.cylinder", params={"radius": 3, "height": 8, "name": "Cyl1", "doc": "HarnessDoc"})
    h.check("part.cylinder ok", r.get("ok") is True, str(r)[:200])
    cyl = doc.getObject("Cyl1")
    h.check("Cyl1 exists", cyl is not None)

    # -----------------------------------------------------------------
    # inspect.object.list → expects 2+ objects
    # -----------------------------------------------------------------
    h.section("inspect.object.list")
    r = h.call("inspect", "object.list", doc="HarnessDoc")
    h.check("object.list ok", r.get("ok") is True, str(r)[:200])
    objs = r.get("objects") or r.get("result", {}).get("objects") or []
    h.check("object.list returns >=2", len(objs) >= 2, f"got {len(objs)}: {objs}")

    # -----------------------------------------------------------------
    # macro.parametric_box
    # -----------------------------------------------------------------
    h.section("create.macro.parametric_box")
    r = h.call("create", "macro.parametric_box", params={"length": 30, "width": 15, "height": 4, "doc": "HarnessDoc"})
    h.check("macro.parametric_box ok", r.get("ok") is True, str(r)[:300])

    # -----------------------------------------------------------------
    # partdesign.body + sketch + pad
    # -----------------------------------------------------------------
    h.section("partdesign.body → sketch → pad")
    r = h.call("create", "partdesign.body", params={"label": "TestBody", "doc": "HarnessDoc"})
    h.check("partdesign.body ok", r.get("ok") is True, str(r)[:200])
    # Native envelope: created is list[dict{name,...}].
    created0 = (r.get("created") or [None])[0]
    body_name = created0.get("name") if isinstance(created0, dict) else (created0 or r.get("primary"))
    h.check("body created name returned", bool(body_name), str(r)[:200])
    if body_name:
        body_obj = doc.getObject(body_name)
        origin = getattr(body_obj, "Origin", None)
        feats = list(getattr(origin, "OriginFeatures", []) or []) if origin else []
        _print("INFO", f"body.Origin={origin!r} feats={[f'{f.Name}/{f.Label}' for f in feats]}")

    # Sketch from profile (closed rectangle, DoF=0)
    r = h.call("create", "partdesign.sketch_from_profile", params={
        "plane": "XY",
        "body": body_name,
        "profile": {"kind": "rectangle", "width": 20, "height": 10, "center": [0, 0]},
        "doc": "HarnessDoc",
    })
    h.check("sketch_from_profile ok", r.get("ok") is True, str(r)[:400])
    # Native envelope: created is list[dict].
    _sk0 = (r.get("created") or [None])[0]
    sketch_name = _sk0.get("name") if isinstance(_sk0, dict) else (_sk0 or r.get("primary"))

    if sketch_name:
        # Verify DoF=0
        r = h.call("verify", "sketcher.sketch", params={"sketch": sketch_name, "doc": "HarnessDoc"})
        h.check("verify sketcher.sketch ok", r.get("ok") is True, str(r)[:300])
        dof = r.get("dof")
        if dof is None:
            dof = (r.get("result") or {}).get("dof")
        h.check(f"sketch DoF=0 (got {dof})", dof == 0)

        # Pad 3mm — native provider now, returns envelope with created[].name
        r = h.call("create", "partdesign.pad", params={"sketch": sketch_name, "length": 3.0, "doc": "HarnessDoc"})
        h.check("partdesign.pad ok", r.get("ok") is True, str(r)[:400])
        # created is list[dict{name,type,bbox,volume,valid}] in the new envelope.
        created0 = (r.get("created") or [None])[0]
        pad_name = created0.get("name") if isinstance(created0, dict) else created0
        pad_name = pad_name or r.get("primary")
        h.check("pad created", bool(pad_name))
        h.check(
            "pad envelope shape",
            all(k in r for k in ("ok", "kind", "created", "modified", "deleted", "context", "warnings", "error")),
            f"keys={sorted(r.keys())}",
        )
        h.check(
            "pad created entry is dict with name+valid",
            isinstance(created0, dict) and "name" in created0 and "valid" in created0,
            str(created0)[:200],
        )
        if pad_name:
            pad = doc.getObject(pad_name)
            h.check("pad has Shape", pad is not None and getattr(pad, "Shape", None) is not None)
            if pad is not None and pad.Shape is not None:
                h.check("pad Volume > 0", pad.Shape.Volume > 0, f"vol={pad.Shape.Volume}")

            # Verify fold of `target` → kind-specific alias (`feature` for
            # verify_feature, `sketch` for verify_sketcher.sketch). Regression
            # guard for the v2 dispatcher's _TARGET_ALIASES fold.
            h.section("target→alias fold (passthrough kinds)")
            r = h.call("verify", "partdesign.feature", target=pad_name, doc="HarnessDoc")
            h.check("cad_verify(target=pad) ok", r.get("ok") is True, str(r)[:300])
            r = h.call("verify", "sketcher.sketch", target=sketch_name, doc="HarnessDoc")
            h.check("cad_verify(target=sketch) ok", r.get("ok") is True, str(r)[:300])

    # -----------------------------------------------------------------
    # memory verbs
    # -----------------------------------------------------------------
    h.section("memory.note.write → memory.read")
    r = h.call("memory", "note.write", params={"section": "test", "key": "harness", "value": 42, "doc": "HarnessDoc"})
    h.check("memory.note.write ok", r.get("ok") is True, str(r)[:200])
    r = h.call("memory", "read", params={"doc": "HarnessDoc"})
    h.check("memory.read ok", r.get("ok") is True, str(r)[:200])
    body_blob = r.get("test") or (r.get("result") or {}).get("test") or {}
    h.check("memory.read returns written note", body_blob.get("harness") == 42, f"got {body_blob}")

    # -----------------------------------------------------------------
    # exec.python.exec — escape hatch
    # -----------------------------------------------------------------
    h.section("exec.python.exec")
    r = h.call("exec", "python.exec", params={
        "code": "App.ActiveDocument.addObject('Part::Box','ExecBox')",
        "label": "harness-exec",
        "doc": "HarnessDoc",
    })
    h.check("exec.python.exec ok", r.get("ok") is True, str(r)[:300])
    h.check("ExecBox created via exec", doc.getObject("ExecBox") is not None)

    # Top-level code/label fold — the model usually passes these at the
    # verb top level rather than inside params. Regression guard.
    r = h.call(
        "exec", "python.exec",
        code="App.ActiveDocument.addObject('Part::Box','ExecBoxTop')",
        label="harness-top",
        doc="HarnessDoc",
    )
    h.check("exec.python.exec (top-level code) ok", r.get("ok") is True, str(r)[:300])
    h.check("ExecBoxTop created via top-level exec", doc.getObject("ExecBoxTop") is not None)

    # -----------------------------------------------------------------
    # missing required params → structured error with expected_params
    # -----------------------------------------------------------------
    h.section("native missing-params (invalid_argument)")
    # The legacy `missing_params` preflight lived on the passthrough path;
    # passthrough is gone, so Pydantic-backed native kinds surface missing
    # fields as invalid_argument with the validator message as hint.
    r = h.call("create", "partdesign.pad", params={"length": 2.0, "doc": "HarnessDoc"})
    err_field = r.get("error")
    err_kind = err_field.get("kind") if isinstance(err_field, dict) else err_field
    h.check(
        "native missing-params → invalid_argument",
        r.get("ok") is False and err_kind == "invalid_argument",
        str(r)[:300],
    )
    h.check(
        "native missing-params hint mentions sketch",
        "sketch" in (err_field.get("hint") or "").lower() if isinstance(err_field, dict) else False,
        str(err_field)[:300],
    )

    # -----------------------------------------------------------------
    # unknown kind → structured error
    # -----------------------------------------------------------------
    h.section("error paths")
    r = h.call("create", "totally.bogus.kind", params={})
    err_field = r.get("error") if isinstance(r, dict) else None
    err_kind = err_field.get("kind") if isinstance(err_field, dict) else err_field
    h.check(
        "unknown kind returns structured error",
        r.get("ok") is False and err_kind == "unknown_kind",
        str(r)[:300],
    )

    # -----------------------------------------------------------------
    # schema.describe — the agent's self-help lookup
    # -----------------------------------------------------------------
    h.section("inspect.schema.describe")
    r = h.call("inspect", "schema.describe", params={"of_kind": "partdesign.pad"})
    h.check("schema.describe ok", r.get("ok") is True, str(r)[:300])
    describes = r.get("describes") or {}
    h.check("describes.verb=create", describes.get("verb") == "create", str(describes)[:200])
    h.check("describes.kind=partdesign.pad", describes.get("kind") == "partdesign.pad")
    h.check("describes.implementation=native", describes.get("implementation") == "native")
    h.check(
        "describes.example has 'sketch'",
        isinstance(describes.get("example"), dict) and "sketch" in describes["example"],
        str(describes.get("example"))[:200],
    )
    h.check(
        "describes.json_schema is dict (pydantic)",
        isinstance(describes.get("json_schema"), dict)
        and "properties" in (describes.get("json_schema") or {}),
        str(describes.get("json_schema"))[:200],
    )
    r = h.call("inspect", "schema.describe", params={"of_kind": "nope.missing"})
    err_field = r.get("error")
    err_kind = err_field.get("kind") if isinstance(err_field, dict) else err_field
    h.check(
        "schema.describe unknown → invalid_argument",
        r.get("ok") is False and err_kind == "invalid_argument",
        str(r)[:300],
    )

    # -----------------------------------------------------------------
    # partdesign.pocket — invalid_argument when neither length nor through_all
    # -----------------------------------------------------------------
    h.section("partdesign.pocket validation")
    if sketch_name:
        # Make a fresh sketch to pocket (first one was consumed by pad).
        r = h.call("create", "partdesign.sketch_from_profile", params={
            "plane": "XY",
            "body": body_name,
            "profile": {"kind": "circle", "center_x": 0, "center_y": 0, "radius": 2},
            "doc": "HarnessDoc",
        })
        pocket_sketch = (r.get("created") or [None])[0] or r.get("primary")
        if isinstance(pocket_sketch, dict):
            pocket_sketch = pocket_sketch.get("name")
        if pocket_sketch:
            # Neither length nor through_all → invalid_argument from Pydantic
            r = h.call("create", "partdesign.pocket", params={
                "sketch": pocket_sketch, "doc": "HarnessDoc",
            })
            err_field = r.get("error")
            err_kind = err_field.get("kind") if isinstance(err_field, dict) else err_field
            h.check(
                "pocket without length/through_all → invalid_argument",
                r.get("ok") is False and err_kind == "invalid_argument",
                str(r)[:300],
            )
            # through_all=true → success envelope
            r = h.call("create", "partdesign.pocket", params={
                "sketch": pocket_sketch, "through_all": True, "doc": "HarnessDoc",
            })
            h.check("pocket through_all ok", r.get("ok") is True, str(r)[:400])
            pocket0 = (r.get("created") or [None])[0]
            h.check(
                "pocket envelope created[0] is dict",
                isinstance(pocket0, dict) and "name" in pocket0,
                str(pocket0)[:200],
            )

    # -----------------------------------------------------------------
    # inspect.context — one-call active-state snapshot
    # -----------------------------------------------------------------
    h.section("inspect.context")
    r = h.call("inspect", "context", params={"doc": "HarnessDoc"})
    h.check("inspect.context ok", r.get("ok") is True, str(r)[:300])
    h.check(
        "context.objects is a list of dicts",
        isinstance(r.get("objects"), list) and len(r["objects"]) > 0
        and isinstance(r["objects"][0], dict) and "name" in r["objects"][0],
        str(r.get("objects"))[:200],
    )
    h.check(
        "context.documents includes HarnessDoc",
        isinstance(r.get("documents"), list) and "HarnessDoc" in r["documents"],
        str(r.get("documents"))[:200],
    )
    h.check("context.units=mm", r.get("units") == "mm")

    # -----------------------------------------------------------------
    # native datum.set — 'property' (not 'property_'), 'value' (not 'value_or_expr')
    # -----------------------------------------------------------------
    h.section("modify.datum.set (native)")
    if pad_name:
        r = h.call("modify", "datum.set", params={
            "feature": pad_name, "property": "Length", "value": 5.0, "doc": "HarnessDoc",
        })
        h.check("datum.set literal ok", r.get("ok") is True, str(r)[:300])
        pad = doc.getObject(pad_name)
        h.check("Pad.Length == 5mm", pad is not None and abs(float(pad.Length) - 5.0) < 1e-6,
                f"got {getattr(pad, 'Length', None)}")
        h.check(
            "datum.set modified[] carries feature",
            isinstance(r.get("modified"), list) and len(r["modified"]) == 1
            and r["modified"][0].get("name") == pad_name,
            str(r.get("modified"))[:200],
        )
        # Wrong property name → invalid_argument with hint
        r = h.call("modify", "datum.set", params={
            "feature": pad_name, "property": "NotAProp", "value": 1, "doc": "HarnessDoc",
        })
        err_field = r.get("error")
        err_kind = err_field.get("kind") if isinstance(err_field, dict) else err_field
        h.check(
            "datum.set wrong property → invalid_argument",
            r.get("ok") is False and err_kind == "invalid_argument",
            str(r)[:300],
        )

    # -----------------------------------------------------------------
    # native fillet — edge-ref validation + real feature name
    # -----------------------------------------------------------------
    h.section("create.partdesign.fillet (native)")
    if pad_name:
        # Bad edge-ref shape → invalid_argument (Pydantic validator)
        r = h.call("create", "partdesign.fillet", params={
            "edges": ["not an edge ref"], "radius": 1.0, "doc": "HarnessDoc",
        })
        err_field = r.get("error")
        err_kind = err_field.get("kind") if isinstance(err_field, dict) else err_field
        h.check(
            "fillet bad edge ref → invalid_argument",
            r.get("ok") is False and err_kind == "invalid_argument",
            str(r)[:300],
        )
        # Good ref — reuse an edge from the padded box
        r = h.call("create", "partdesign.fillet", params={
            "edges": [f"{pad_name}.Edge1"], "radius": 0.5, "doc": "HarnessDoc",
        })
        h.check("fillet ok", r.get("ok") is True, str(r)[:400])
        fillet0 = (r.get("created") or [None])[0]
        h.check(
            "fillet created[0] is dict with valid=True",
            isinstance(fillet0, dict) and fillet0.get("valid") is True,
            str(fillet0)[:200],
        )

    # -----------------------------------------------------------------
    # sketch_from_profile native envelope — health + named_constraints
    # -----------------------------------------------------------------
    h.section("sketch_from_profile (native) envelope")
    r = h.call("create", "partdesign.sketch_from_profile", params={
        "plane": "XY",
        "body": body_name,
        "profile": {"kind": "rectangle", "width": 6, "height": 4, "center": [0, 0]},
        "name": "ProfileTest",
        "doc": "HarnessDoc",
    })
    h.check("sketch_from_profile (native) ok", r.get("ok") is True, str(r)[:400])
    prof_sketch_dict = (r.get("created") or [None])[0]
    prof_sketch_name = prof_sketch_dict.get("name") if isinstance(prof_sketch_dict, dict) else prof_sketch_dict
    h.check(
        "sketch_from_profile health.dof == 0",
        isinstance(r.get("health"), dict) and r["health"].get("dof") == 0,
        str(r.get("health"))[:200],
    )
    h.check(
        "sketch_from_profile named_constraints populated",
        isinstance(r.get("named_constraints"), dict) and len(r["named_constraints"]) > 0,
        str(r.get("named_constraints"))[:200],
    )

    # -----------------------------------------------------------------
    # Compositional path: create blank sketch → add line + circle → add
    # constraints via both raw refs AND anchors → close.
    # -----------------------------------------------------------------
    h.section("sketcher.geometry/constraint + close (native)")
    r = h.call("create", "partdesign.sketch", params={
        "plane": "XZ", "body": body_name, "name": "CompTest", "doc": "HarnessDoc",
    })
    h.check("partdesign.sketch (blank) ok", r.get("ok") is True, str(r)[:400])
    _bl = (r.get("created") or [None])[0]
    blank_sketch = _bl.get("name") if isinstance(_bl, dict) else _bl
    h.check(
        "blank sketch envelope carries health",
        isinstance(r.get("health"), dict) and "dof" in r["health"],
        str(r.get("health"))[:200],
    )

    if blank_sketch:
        # Add a line
        r = h.call("modify", "sketcher.geometry.add", params={
            "sketch": blank_sketch, "kind": "line",
            "params": {"start": [0, 0], "end": [10, 0]},
            "doc": "HarnessDoc",
        })
        h.check("geometry.add line ok", r.get("ok") is True, str(r)[:300])
        line_ids = r.get("geo_ids") or []
        h.check("geometry.add returns geo_ids", len(line_ids) >= 1, str(r)[:200])
        h.check("geometry.add envelope has health.dof",
                isinstance(r.get("health"), dict) and "dof" in r["health"],
                str(r.get("health"))[:200])

        # Add a horizontal constraint using the ergonomic 'anchors' form
        line_id = line_ids[0]
        r = h.call("modify", "sketcher.constraint.add", params={
            "sketch": blank_sketch, "kind": "Horizontal",
            "anchors": [{"geo_id": line_id, "pos": "edge"}],
            "doc": "HarnessDoc",
        })
        h.check("constraint.add via anchors ok", r.get("ok") is True, str(r)[:300])
        h.check(
            "anchors translated to refs correctly",
            r.get("refs_used") == [line_id],
            f"got {r.get('refs_used')}",
        )

        # Raw refs still work (backward compatibility)
        r = h.call("modify", "sketcher.constraint.add", params={
            "sketch": blank_sketch, "kind": "DistanceX",
            "refs": [line_id, 1, line_id, 2], "value": 10.0,
            "doc": "HarnessDoc",
        })
        h.check("constraint.add via raw refs ok", r.get("ok") is True, str(r)[:300])

        # Neither refs nor anchors → invalid_argument from Pydantic validator
        r = h.call("modify", "sketcher.constraint.add", params={
            "sketch": blank_sketch, "kind": "Horizontal",
            "doc": "HarnessDoc",
        })
        err_field = r.get("error")
        err_kind = err_field.get("kind") if isinstance(err_field, dict) else err_field
        h.check(
            "constraint.add without refs/anchors → invalid_argument",
            r.get("ok") is False and err_kind == "invalid_argument",
            str(r)[:300],
        )

        # close returns envelope with health
        r = h.call("verify", "sketcher.close", params={
            "sketch": blank_sketch, "doc": "HarnessDoc",
        })
        h.check("sketcher.close ok", r.get("ok") is True, str(r)[:300])
        h.check(
            "close returns health dict",
            isinstance(r.get("health"), dict) and "dof" in r["health"],
            str(r.get("health"))[:200],
        )

    # -----------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------
    _print("====", f"PASSED {h.passed}  FAILED {h.failed}")
    for e in h.errors:
        _print("ERR ", e)
    return 0 if h.failed == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
