# SPDX-License-Identifier: LGPL-2.1-or-later
"""v2 verb tools — the ~10 generalized MCP tools that dispatch into providers.

Each verb (``cad.create``, ``cad.modify``, …) is a single ``@tool``-decorated
async function. The handler:

  1. Validates ``kind`` exists in the registry for this verb.
  2. Runs the kind's preflight; rejects with structured error on failure.
  3. For mutating verbs, wraps execution in ``with_transaction`` (one undo step).
  4. Calls the kind's ``execute(doc, params)`` on the Qt GUI thread.
  5. Calls the kind's ``summarize(doc, raw)`` (or a sensible default).
  6. Returns ``ok(payload)``. Postflight hints are emitted by the hook layer
     (``hooks.py``) by reading the registry.

Verb tool descriptions are generated from the registry — every kind a
provider registers shows up in the verb's description automatically, so
adding a workbench means adding a provider file with no edits here.

This module assumes ``providers.load_all()`` has already populated the
registry. ``runtime.py`` calls it before constructing the MCP server.
"""

from __future__ import annotations

import inspect
import traceback
from typing import Any

from claude_agent_sdk import tool
from mcp.types import ToolAnnotations

from . import providers as _providers
from . import registry

# Populate the registry before the @tool decorators below render their
# descriptions — the description strings enumerate the registered kinds.
_providers.load_all()

from .tools._shared import (
    err,
    ok,
    on_gui,
    resolve_doc,
    summarise_result,
    with_transaction,
)


_READ_ONLY = ToolAnnotations(readOnlyHint=True)


# Per-verb headers. The registry appends the available kinds list under each.
_HEADERS: dict[str, str] = {
    "create": (
        "Create a new FreeCAD object (body, sketch, feature, primitive, "
        "assembly, …). The 'kind' selects what to create; 'params' carries "
        "kind-specific arguments. One undo step per call."
    ),
    "modify": (
        "Modify an existing FreeCAD object: edit a property, add a sketch "
        "constraint, set a placement, retarget a feature. One undo step."
    ),
    "delete": (
        "Delete an object from the active document. One undo step."
    ),
    "inspect": (
        "Read-only introspection: list documents/objects, fetch object "
        "properties, dump topology, get the current selection, get parameters."
    ),
    "verify": (
        "Read-only verification of a sketch's DoF or a feature's solid "
        "validity / topology. May trigger a recompute. Use after a mutation."
    ),
    "render": (
        "Render the active 3D view to a PNG returned inline as base64. "
        "Use sparingly — costs context tokens."
    ),
    "io": (
        "Import or export geometry to/from disk (STEP, IGES, STL, OBJ, BREP, "
        "DXF, …). Specify op='import'|'export' and format."
    ),
    "memory": (
        "Read or write the project memory sidecar: design intent, parameters, "
        "decisions, free-form notes. The 'kind' already encodes the op — use "
        "'read', 'note.write', 'decision.record', or 'decision.list' directly. "
        "Do NOT split into kind='note' + op='write'."
    ),
    "plan": (
        "Submit or update the milestone plan and lifecycle (emit_plan, "
        "mark_active, mark_done, mark_failed, get_active). Used by the "
        "orchestrator/executor split."
    ),
    "exec": (
        "Escape hatch: execute arbitrary FreeCAD Python in a transaction. "
        "Use only when no registered 'kind' under create/modify/io can express "
        "the operation, and explain to the user why first."
    ),
}


# ---------------------------------------------------------------------------
# Internal dispatch
# ---------------------------------------------------------------------------

def _missing_kind_error(verb: str, kind: str | None) -> dict:
    available = sorted(k.kind for k in registry.kinds_for(verb))
    return err(
        f"Unknown kind {kind!r} for verb {verb!r}.",
        kind="unknown_kind",
        available=available[:50],  # cap to keep payload small
        hint=f"Pick one of the kinds listed in the cad_{verb} tool description.",
    )


async def _dispatch(verb: str, args: dict[str, Any]) -> dict:
    """Common dispatch path for every verb. Returns an MCP payload."""
    kind_name = args.get("kind") if args else None
    if not kind_name or not isinstance(kind_name, str):
        return err(
            f"'kind' is required for cad_{verb}.",
            kind="missing_kind",
            available=sorted(k.kind for k in registry.kinds_for(verb))[:50],
        )
    rec = registry.get(verb, kind_name)
    if rec is None:
        return _missing_kind_error(verb, kind_name)

    # Fold well-known top-level aliases into params BEFORE the passthrough
    # branch, so v1 translators (which read ``args.get("params")``) see the
    # same flattened shape as native v2 providers. Without this, a call like
    # ``cad_create(kind="document", name="Bracket")`` never passes ``name``
    # to create_document's handler.
    folded = dict(args) if args else {}
    params = dict(folded.get("params") or {})
    # ``code`` / ``label`` are top-level on ``cad_exec``; ``width`` / ``height``
    # on ``cad_render``. Fold them along with the generic aliases so
    # passthrough translators (which read ``args.get("params")``) see them.
    for k in ("target", "name", "doc", "parent", "op", "code", "label", "width", "height"):
        if k in folded and k not in params:
            params[k] = folded[k]
    # ``target`` is the v2-canonical "thing this verb operates on". v1
    # handlers read it under kind-specific names (``feature``, ``sketch``,
    # ``part_ref``, …). If the caller provided ``target`` and the kind's
    # params_schema names one of those slots that's still empty, forward it.
    _TARGET_ALIASES = ("feature", "sketch", "part_ref", "assembly", "object")
    tgt = params.get("target")
    if isinstance(tgt, str) and tgt:
        for alias in _TARGET_ALIASES:
            if alias in rec.params_schema and alias not in params:
                params[alias] = tgt
                break
    folded["params"] = params

    # Native: handler owns everything (validation, transaction, envelope).
    # Dispatcher just resolves the doc, runs execute on the Qt thread for
    # mutating verbs, and returns the handler's MCP content dict verbatim.
    if rec.native:
        return await _dispatch_native(rec, params)

    # Passthrough: execute is the v1 SDK tool's async handler. It already
    # handles its own preflight, transaction, and result shaping.
    if rec.passthrough:
        # Translate v2 args → v1 args. Providers register a translator as
        # ``execute`` that returns the v1 args dict. The actual v1 handler
        # is stored in ``summarize`` (overloaded for migration convenience).
        v1_args = rec.execute(folded)  # type: ignore[misc]
        # Fast structured rejection for missing required params. Without this,
        # the v1 tool body raises a bare KeyError whose repr ('feature',
        # 'edges', …) doesn't tell the model what it should have sent. The
        # registry already carries the expected shape — use it.
        missing = _missing_required_params(rec, v1_args)
        if missing:
            return err(
                f"Missing required params for {verb}/{kind_name}: {missing}.",
                kind="missing_params",
                verb=verb,
                of_kind=kind_name,
                expected_params=rec.params_schema,
                received_keys=sorted(v1_args.keys()) if isinstance(v1_args, dict) else [],
                missing=missing,
            )
        v1_handler = rec.summarize  # the v1 SDK tool's .handler
        if v1_handler is None:
            return err(
                f"passthrough kind {kind_name!r} has no v1 handler",
                kind="internal_error",
            )
        result = v1_handler(v1_args)  # type: ignore[misc]
        if inspect.isawaitable(result):
            result = await result
        return _augment_error_with_schema(result, rec)

    # ``params`` already populated above (shared with the passthrough branch).

    if rec.preflight is not None:
        msg = rec.preflight(params)
        if msg:
            return err(
                msg,
                kind="preflight_rejected",
                verb=verb,
                of_kind=kind_name,
            )

    try:
        doc_arg = params.get("doc")
        if rec.is_mutating:
            doc = resolve_doc(doc_arg)
            label = f"{verb}:{kind_name}"

            def work():
                return rec.execute(doc, params)

            raw = with_transaction(doc, label, work)
        else:
            # Read-only: still on GUI thread, but no transaction.
            doc = resolve_doc(doc_arg) if doc_arg or _kind_needs_doc(rec) else None

            def work():
                return rec.execute(doc, params)

            raw = on_gui(work)

        if rec.summarize is not None:
            payload = rec.summarize(doc, raw)
        elif rec.is_mutating:
            # Default mutating summary: created list of object names.
            created = _coerce_created(raw)
            payload = summarise_result(doc, created)
        else:
            # Default read-only summary: pass-through if dict, else wrap.
            payload = raw if isinstance(raw, dict) else {"result": raw}
        return ok(payload)
    except Exception as exc:
        return err(
            f"{exc}\n{traceback.format_exc(limit=4)}",
            kind="internal_error",
            verb=verb,
            of_kind=kind_name,
        )


async def _dispatch_native(rec: registry.Kind, params: dict) -> dict:
    """Native handler path. Validates against ``rec.model`` if present, then
    calls ``rec.execute(doc, validated_params)`` on the GUI thread (inside a
    transaction for mutating verbs). The handler returns the MCP content dict
    directly — the dispatcher does not wrap it.
    """
    from .envelope import err_envelope

    validated: dict = params
    if rec.model is not None:
        try:
            instance = rec.model(**params)
            validated = instance.model_dump(exclude_none=False)
        except Exception as exc:
            return err_envelope(
                rec.kind,
                error_kind="invalid_argument",
                message=f"Invalid arguments for {rec.verb}:{rec.kind}.",
                hint=str(exc),
                extras={"expected_params": rec.params_schema, "received": sorted(params.keys())},
            )

    try:
        doc_arg = validated.get("doc")
        # Native handlers own their own transactions (they need to decide when
        # to commit vs. abort based on preflight checks). The dispatcher only
        # marshals to the Qt thread.
        doc = resolve_doc(doc_arg) if doc_arg or _kind_needs_doc(rec) or rec.is_mutating else None

        def work():
            return rec.execute(doc, validated)

        return on_gui(work)
    except Exception as exc:
        return err_envelope(
            rec.kind,
            error_kind="internal_error",
            message=str(exc),
            hint="Unhandled exception inside native handler — see traceback.",
            extras={"traceback": traceback.format_exc(limit=6)},
        )


def _missing_required_params(rec: registry.Kind, v1_args: Any) -> list[str]:
    """Return the list of schema-required keys absent from ``v1_args``.

    Schema entries ending in ``?`` (e.g. ``"str?"``) are optional. The v2→v1
    translator folds top-level aliases into ``v1_args`` before we get here,
    so what's missing here is really missing.
    """
    if not isinstance(v1_args, dict):
        return []
    missing: list[str] = []
    for key, type_hint in (rec.params_schema or {}).items():
        if isinstance(type_hint, str) and type_hint.endswith("?"):
            continue
        if key not in v1_args or v1_args.get(key) in (None, ""):
            # ``doc`` is optional at the call site even without a ``?`` —
            # v1 tools default to App.ActiveDocument when it's missing.
            if key == "doc":
                continue
            missing.append(key)
    return missing


def _augment_error_with_schema(result: Any, rec: registry.Kind) -> Any:
    """If a passthrough v1 handler returned an error, append the kind's
    param schema as a hint so the model can fix the call on the next turn.

    The v1 tools return ``{"content": [{"type": "text", "text": "..."}]}``
    where the text is either a success JSON (``{"ok": true, ...}``) or an
    error JSON (``{"ok": false, "error": "...", "message": "...", ...}``).
    We only touch the error branch, and we only add fields the v1 tool
    didn't already set.
    """
    try:
        if not isinstance(result, dict):
            return result
        content = result.get("content")
        if not (isinstance(content, list) and content):
            return result
        block = content[0]
        if not (isinstance(block, dict) and block.get("type") == "text"):
            return result
        import json as _json
        body = _json.loads(block.get("text") or "{}")
        if body.get("ok") is True:
            return result
        if "expected_params" not in body and rec.params_schema:
            body["expected_params"] = rec.params_schema
            body.setdefault("of_kind", rec.kind)
            block["text"] = _json.dumps(body, default=str)
        return result
    except Exception:
        return result


def _kind_needs_doc(rec: registry.Kind) -> bool:
    """Heuristic: most kinds need an active doc; a few (e.g. inspect:documents) don't.

    Providers that operate without a doc should declare ``params_schema`` with
    no ``doc`` key AND set ``read_only=True``; this helper still resolves a
    doc if one is open, but won't fail if none is. Kept simple — providers
    can always call ``resolve_doc()`` themselves inside ``execute`` if needed.
    """
    return "doc" in rec.params_schema


def _coerce_created(raw: Any) -> list[str]:
    """Best-effort normalisation of an execute() return into a list of object names."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            name = getattr(item, "Name", None)
            out.append(name if isinstance(name, str) else str(item))
        return out
    name = getattr(raw, "Name", None)
    if isinstance(name, str):
        return [name]
    return []


# ---------------------------------------------------------------------------
# The 10 verb tools
# ---------------------------------------------------------------------------
# Each verb is a single MCP tool. Its description is generated from the
# registry at import time. Adding a kind is one provider-file edit.

def _make_verb_schema(verb: str) -> dict:
    """All verbs share the same loose schema: ``kind`` is the only required
    property. Everything else (``params``, ``target``, ``name``, …) is
    optional so the model can make minimal read-only calls like
    ``cad_inspect(kind='document.list')`` without padding arguments.

    We build the JSON Schema object directly because the SDK's dict-style
    shorthand marks every listed property as required (see
    ``claude_agent_sdk.__init__._build_schema``).
    """
    properties: dict[str, dict] = {
        "kind": {"type": "string"},
        "params": {"type": "object"},
        "doc": {"type": "string"},
    }
    if verb in {"modify", "delete", "verify"}:
        properties["target"] = {"type": "string"}
    if verb == "create":
        properties["name"] = {"type": "string"}
        properties["parent"] = {"type": "string"}
    if verb in {"memory", "plan", "io"}:
        properties["op"] = {"type": "string"}
    return {
        "type": "object",
        "properties": properties,
        "required": ["kind"],
    }


@tool(
    "cad_create",
    registry.render_verb_description("create", _HEADERS["create"]),
    _make_verb_schema("create"),
)
async def cad_create(args):
    return await _dispatch("create", args)


@tool(
    "cad_modify",
    registry.render_verb_description("modify", _HEADERS["modify"]),
    _make_verb_schema("modify"),
)
async def cad_modify(args):
    return await _dispatch("modify", args)


@tool(
    "cad_delete",
    registry.render_verb_description("delete", _HEADERS["delete"]),
    _make_verb_schema("delete"),
)
async def cad_delete(args):
    return await _dispatch("delete", args)


@tool(
    "cad_inspect",
    registry.render_verb_description("inspect", _HEADERS["inspect"]),
    _make_verb_schema("inspect"),
    annotations=_READ_ONLY,
)
async def cad_inspect(args):
    return await _dispatch("inspect", args)


@tool(
    "cad_verify",
    registry.render_verb_description("verify", _HEADERS["verify"]),
    _make_verb_schema("verify"),
    annotations=_READ_ONLY,
)
async def cad_verify(args):
    return await _dispatch("verify", args)


@tool(
    "cad_render",
    registry.render_verb_description("render", _HEADERS["render"]),
    {
        "type": "object",
        "properties": {
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "doc": {"type": "string"},
            "kind": {"type": "string"},
            "params": {"type": "object"},
        },
        "required": [],
    },
    annotations=_READ_ONLY,
)
async def cad_render(args):
    # render has a single canonical kind; default it for ergonomics.
    if not args.get("kind"):
        args = dict(args)
        args["kind"] = "view.png"
    return await _dispatch("render", args)


@tool(
    "cad_io",
    registry.render_verb_description("io", _HEADERS["io"]),
    _make_verb_schema("io"),
)
async def cad_io(args):
    return await _dispatch("io", args)


@tool(
    "cad_memory",
    registry.render_verb_description("memory", _HEADERS["memory"]),
    _make_verb_schema("memory"),
)
async def cad_memory(args):
    return await _dispatch("memory", args)


@tool(
    "cad_plan",
    registry.render_verb_description("plan", _HEADERS["plan"]),
    _make_verb_schema("plan"),
)
async def cad_plan(args):
    return await _dispatch("plan", args)


@tool(
    "cad_exec",
    registry.render_verb_description("exec", _HEADERS["exec"]),
    {
        "type": "object",
        "properties": {
            "kind": {"type": "string"},
            "params": {"type": "object"},
            "code": {"type": "string"},
            "label": {"type": "string"},
            "doc": {"type": "string"},
        },
        "required": [],
    },
)
async def cad_exec(args):
    if not args.get("kind"):
        args = dict(args)
        args["kind"] = "python.exec"
    return await _dispatch("exec", args)


VERB_TOOLS: tuple = (
    cad_create,
    cad_modify,
    cad_delete,
    cad_inspect,
    cad_verify,
    cad_render,
    cad_io,
    cad_memory,
    cad_plan,
)

VERB_TOOL_NAMES: tuple[str, ...] = (
    "cad_create",
    "cad_modify",
    "cad_delete",
    "cad_inspect",
    "cad_verify",
    "cad_render",
    "cad_io",
    "cad_memory",
    "cad_plan",
)
# ``cad_exec`` is intentionally NOT exposed as an MCP tool any more. The
# ``exec`` verb and ``python.exec`` kind remain in the registry so internal
# callers (and the harness) can still dispatch to ``_dispatch("exec", …)``,
# but the model reaches for the SDK-built-in ``Bash`` tool instead for any
# shell-level / subprocess escape hatch. We were seeing the agent fail
# repeatedly on multi-line Python through cad_exec; Bash is the more
# reliable tool the model already knows how to drive.


def tool_funcs() -> list:
    return list(VERB_TOOLS)


def tool_names() -> list[str]:
    return list(VERB_TOOL_NAMES)


def allowed_tool_names() -> list[str]:
    """Full names with the SDK's ``mcp__cad__`` prefix (set by server name)."""
    return [f"mcp__cad__{n}" for n in VERB_TOOL_NAMES]
