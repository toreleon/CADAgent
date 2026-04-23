# SPDX-License-Identifier: LGPL-2.1-or-later
"""Adapter: wrap an existing v1 SDK tool as a *native* registry kind.

The kind is registered with ``native=True`` and an async ``execute`` that
awaits the v1 handler and then re-shapes its legacy MCP payload into the
uniform envelope (``ok_envelope`` / ``err_envelope``).

Motivation: we want v1_passthrough.py and the legacy passthrough dispatch
branch gone, but rewriting every remaining v1 tool from scratch is a
multi-day job. This adapter gives us:

  - uniform envelope shape on the wire (so agents see one result schema),
  - Pydantic validation at the boundary (so errors are ``invalid_argument``
    with a useful hint, not raw KeyError tracebacks),
  - structured ``error`` objects (error.kind + hint + recover_tools),
  - the existing v1 handler body unchanged underneath, preserving behaviour.

When a kind's behaviour needs per-handler changes (chamfer Size guard,
semantic sketch refs), it gets a proper native handler like the ones in
``partdesign_native.py`` / ``sketch_native.py``. This adapter is the
default — it costs ~6 lines per kind.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from .. import registry
from ..envelope import err_envelope, ok_envelope


# Legacy top-level fields that summarise_result puts on mutating payloads;
# they go into the envelope's created[] list (via the object-name route)
# rather than staying as top-level noise.
_LEGACY_SUMMARY_KEYS = {
    "created", "primary", "bbox", "volume", "is_valid_solid",
}


def _unwrap(result: Any) -> dict:
    """Pull JSON body out of an MCP ``{content:[{text:...}]}`` dict."""
    try:
        return json.loads(result["content"][0]["text"])
    except Exception:
        return {"__raw__": str(result)[:400]}


def _reshape(body: dict, *, kind: str, doc, mutating: bool,
              extract_created: Callable[[dict], Iterable[str]] | None) -> dict:
    """Convert a legacy v1 MCP body into the uniform envelope."""
    if body.get("ok") is False:
        err_kind = body.get("error") or "internal_error"
        message = body.get("message") or str(err_kind)
        hint = body.get("hint")
        extras = {k: v for k, v in body.items()
                  if k not in ("ok", "error", "message", "hint", "recover_tools")}
        return err_envelope(
            kind, error_kind=err_kind, message=message, hint=hint,
            doc=doc, extras=extras,
        )
    # Success.
    created_names: list[str] = []
    if mutating:
        if extract_created is not None:
            created_names = [n for n in extract_created(body) if isinstance(n, str)]
        else:
            legacy_created = body.get("created")
            if isinstance(legacy_created, list):
                created_names = [n for n in legacy_created if isinstance(n, str)]
            elif isinstance(body.get("primary"), str):
                created_names = [body["primary"]]
    extras = {
        k: v for k, v in body.items()
        if k not in _LEGACY_SUMMARY_KEYS and k != "ok"
    }
    return ok_envelope(
        kind, doc=doc,
        created=created_names,
        extras=extras,
    )


def port(
    *,
    verb: str,
    kind: str,
    v1_tool: Any,
    description: str,
    params_schema: dict[str, str] | None = None,
    model: Any | None = None,
    example: dict[str, Any] | None = None,
    read_only: bool | None = None,
    extract_created: Callable[[dict], Iterable[str]] | None = None,
    arg_translate: Callable[[dict], dict] | None = None,
) -> None:
    """Register ``v1_tool`` as a native kind producing uniform envelopes.

    ``arg_translate`` lets a provider rename or lift fields before they hit
    the v1 handler (e.g. ``value`` → ``value_or_expr``). By default the
    validated params dict is passed straight through.

    ``extract_created`` is called on a successful v1 body to pick the list
    of object names that should land in ``envelope.created[]``; most v1
    tools already put them in ``body["created"]`` and the default handles
    that.
    """
    v1_handler = getattr(v1_tool, "handler", None)
    if v1_handler is None:
        raise ValueError(f"{verb}:{kind} v1_tool has no .handler")
    is_mutating = not bool(read_only)

    async def _execute(doc, validated_params):  # noqa: ANN001
        v1_args = arg_translate(validated_params) if arg_translate else validated_params
        result = await v1_handler(v1_args)
        body = _unwrap(result)
        return _reshape(
            body, kind=kind, doc=doc,
            mutating=is_mutating, extract_created=extract_created,
        )

    registry.register(
        verb=verb,
        kind=kind,
        description=description,
        params_schema=params_schema or {},
        execute=_execute,
        native=True,
        model=model,
        example=example,
        read_only=read_only,
    )
