# SPDX-License-Identifier: LGPL-2.1-or-later
"""Workbench registry for the v2 verb surface.

The v1 tool surface is 39 narrow tools (one per FreeCAD operation). v2
collapses that into ~10 generalized verbs (`cad.create`, `cad.modify`,
`cad.inspect`, …) that dispatch through this registry. Each workbench
contributes a provider module under ``agent/providers/`` that registers
``Kind`` records — one per FreeCAD operation it exposes.

Adding a new workbench means writing one provider file. The verb tools
themselves never change.

See ``/home/tore/.claude/plans/review-the-tool-design-snappy-axolotl.md``
for the full design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

# The fixed set of verbs. Anything outside this list is a programming error
# (caught at register() time so providers fail loudly during import).
VERBS: tuple[str, ...] = (
    "create",
    "modify",
    "delete",
    "inspect",
    "verify",
    "render",
    "io",
    "memory",
    "plan",
    "exec",
)

# Verbs whose operations mutate the document and should be wrapped in a
# transaction (one undo step per call). Read-only verbs skip the wrapper.
MUTATING_VERBS: frozenset[str] = frozenset({
    "create", "modify", "delete", "io", "memory", "plan", "exec"
})


# Postflight hint: when the response payload contains ``key`` equal to
# ``equals`` (or matches a predicate), inject ``hint`` into the next agent
# turn as additionalContext.
@dataclass(frozen=True)
class PostHint:
    key: str
    equals: Any
    hint: str
    # Optional dotted-path lookup; if ``key`` contains '.', it traverses
    # nested dicts (e.g. "error.kind").
    path: tuple[str, ...] = field(default=())

    def matches(self, payload: dict) -> bool:
        cur: Any = payload
        parts = self.path or tuple(self.key.split("."))
        for p in parts:
            if not isinstance(cur, dict):
                return False
            cur = cur.get(p)
        return cur == self.equals


@dataclass
class Kind:
    """One operation registered against a verb (e.g. ``create:partdesign.pad``)."""

    verb: str
    kind: str
    description: str
    params_schema: dict[str, str]
    execute: Callable[[Any, dict], Any]
    # Optional preflight: return None to accept, or a string error message
    # to deny. Receives the raw params dict.
    preflight: Callable[[dict], str | None] | None = None
    # Optional summarize: receives (doc, raw_execute_result) and returns the
    # payload dict. Defaults to ``summarise_result(doc, [created_name])`` for
    # mutating verbs, or returning the result verbatim for read-only.
    summarize: Callable[[Any, Any], dict] | None = None
    postflight_hints: tuple[PostHint, ...] = field(default=())
    # Read-only override (some verbs are mixed: cad.memory has read+write ops).
    read_only: bool | None = None
    # Passthrough mode: ``execute`` is an async v1 SDK tool handler
    # (``async def handler(args) -> {"content": [...]})``. The dispatcher
    # awaits it and returns the result verbatim, skipping its own
    # transaction wrapping, summarize, and ok() wrap. Used during the v1→v2
    # migration so we don't rewrite 39 tool bodies.
    passthrough: bool = False
    # Native mode: ``execute`` is itself the full handler, takes (doc, params),
    # is responsible for its own transaction / envelope / error shape, and
    # returns an MCP content dict. The dispatcher skips preflight/transaction/
    # summarize machinery — the handler owns everything. Used by the PR1+
    # native providers that want Pydantic validation and the uniform envelope.
    native: bool = False
    # Optional Pydantic model used to validate params before ``execute`` runs
    # (native kinds only). Providing this lets ``schema.describe`` emit a real
    # JSON Schema + typed errors instead of the legacy string-dict shape.
    model: Any = None
    # Optional concrete example args dict — surfaced by ``schema.describe`` so
    # the agent has a canonical call to copy.
    example: dict[str, Any] | None = None

    @property
    def is_mutating(self) -> bool:
        if self.read_only is not None:
            return not self.read_only
        return self.verb in MUTATING_VERBS


_REGISTRY: dict[str, dict[str, Kind]] = {v: {} for v in VERBS}


def register(
    *,
    verb: str,
    kind: str,
    description: str,
    params_schema: dict[str, str],
    execute: Callable[[Any, dict], Any],
    preflight: Callable[[dict], str | None] | None = None,
    summarize: Callable[[Any, Any], dict] | None = None,
    postflight_hints: Iterable[PostHint] = (),
    read_only: bool | None = None,
    passthrough: bool = False,
    native: bool = False,
    model: Any = None,
    example: dict[str, Any] | None = None,
) -> None:
    """Register a kind. Called at provider import time."""
    if verb not in VERBS:
        raise ValueError(f"Unknown verb {verb!r}. Must be one of {VERBS}.")
    if not kind or not isinstance(kind, str):
        raise ValueError(f"kind must be a non-empty string (got {kind!r}).")
    if passthrough and native:
        raise ValueError(f"{verb}:{kind} cannot be both passthrough and native.")
    bucket = _REGISTRY[verb]
    if kind in bucket:
        raise ValueError(f"Duplicate registration: verb={verb} kind={kind}")
    bucket[kind] = Kind(
        verb=verb,
        kind=kind,
        description=description,
        params_schema=dict(params_schema),
        execute=execute,
        preflight=preflight,
        summarize=summarize,
        postflight_hints=tuple(postflight_hints),
        read_only=read_only,
        passthrough=passthrough,
        native=native,
        model=model,
        example=example,
    )


def get(verb: str, kind: str) -> Kind | None:
    return _REGISTRY.get(verb, {}).get(kind)


def kinds_for(verb: str) -> list[Kind]:
    return list(_REGISTRY.get(verb, {}).values())


def all_kinds() -> list[Kind]:
    out: list[Kind] = []
    for bucket in _REGISTRY.values():
        out.extend(bucket.values())
    return out


def render_verb_description(verb: str, header: str) -> str:
    """Render an MCP tool description listing the registered kinds.

    The verb tool's description starts with ``header`` (one paragraph
    explaining the verb) and appends a grouped list of kinds: workbench
    prefix → kinds → one-line description each. The model uses this to
    pick the right kind without us having to ship a separate help tool.
    """
    kinds = kinds_for(verb)
    if not kinds:
        return header
    by_prefix: dict[str, list[Kind]] = {}
    for k in kinds:
        prefix = k.kind.split(".", 1)[0]
        by_prefix.setdefault(prefix, []).append(k)
    lines = [header.rstrip(), "", "Available kinds:"]
    for prefix in sorted(by_prefix):
        lines.append(f"  [{prefix}]")
        for k in sorted(by_prefix[prefix], key=lambda x: x.kind):
            params = ", ".join(f"{n}:{t}" for n, t in k.params_schema.items())
            lines.append(f"    - {k.kind}({params}) — {k.description}")
    return "\n".join(lines)


# Generic preflight rules reusable across providers ----------------------

def positive_number(*field_names: str) -> Callable[[dict], str | None]:
    """Preflight: required numeric fields must be > 0."""
    def check(params: dict) -> str | None:
        for name in field_names:
            if name not in params:
                continue
            try:
                v = float(params[name])
            except (TypeError, ValueError):
                return f"{name} must be a number"
            if v <= 0:
                return f"{name} must be > 0 (got {v})"
        return None
    return check


def required_str(*field_names: str) -> Callable[[dict], str | None]:
    def check(params: dict) -> str | None:
        for name in field_names:
            v = params.get(name)
            if not isinstance(v, str) or not v.strip():
                return f"{name} must be a non-empty string"
        return None
    return check


def chain(*checks: Callable[[dict], str | None]) -> Callable[[dict], str | None]:
    """Compose preflight checks; first failure wins."""
    def check(params: dict) -> str | None:
        for c in checks:
            err = c(params)
            if err:
                return err
        return None
    return check


# Hints reusable across providers ----------------------------------------

INVALID_SOLID_HINT = PostHint(
    key="is_valid_solid",
    equals=False,
    hint=(
        "is_valid_solid=false. Call cad.verify(kind='partdesign.feature', "
        "target=...) to diagnose, then fix the upstream sketch or operation."
    ),
)


def sketch_dof_hint(predicate_value: int) -> PostHint:
    """DoF mismatch hint. Matches when payload['dof'] equals the value."""
    if predicate_value > 0:
        msg = (
            f"sketch DoF={predicate_value} (>0). Call cad.modify with "
            "kind='sketcher.constraint.*' to add the missing constraint, then "
            "cad.verify(kind='sketcher.sketch', target=...) again."
        )
    else:
        msg = (
            f"sketch DoF={predicate_value} (<0, over-constrained). Remove a "
            "conflicting constraint, then cad.verify(kind='sketcher.sketch') again."
        )
    return PostHint(key="dof", equals=predicate_value, hint=msg)


def reset_for_tests() -> None:
    """Clear the registry (test helper only)."""
    for v in VERBS:
        _REGISTRY[v].clear()
