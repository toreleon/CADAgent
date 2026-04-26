# SPDX-License-Identifier: LGPL-2.1-or-later
"""Auto-compaction primitives for CADAgent.

Pure-logic module: no FreeCAD imports at module top. The dock runtime calls
into here after each turn to decide whether the running context window is
close to its limit, and (separately) to recover from context-overflow errors
raised by the SDK by force-compacting and retrying.

Public surface (see Wave 1 plan):

* :data:`DEFAULT_CONTEXT_LIMIT` / :data:`MODEL_CONTEXT_LIMITS`
* :func:`context_limit_for` — settings override → exact match → prefix match
  → default
* :class:`SessionTokens` — running totals across a session, fed by SDK
  ``ResultMessage.usage`` payloads (object or dict)
* :func:`should_auto_compact` — threshold check, default 95%
* :func:`is_context_overflow_error` — recognise the SDK / provider error
  shapes that mean "too long, retry smaller"
* :func:`summarize_transcript` — STUB; Unit D will replace with a real
  ``query()`` round-trip
* :func:`compact_session` — orchestrate truncate-and-fork via the rewind /
  sessions modules (lazy-imported)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Context window sizing
# ---------------------------------------------------------------------------

DEFAULT_CONTEXT_LIMIT: int = 256_000

# Exact-match table. Prefix matching (longest first) handles dated suffixes
# like ``claude-3-5-sonnet-20241022`` without an entry per snapshot.
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # Claude families: 200k tokens.
    "claude-3-5-sonnet": 200_000,
    "claude-3-7-sonnet": 200_000,
    "claude-opus-4": 200_000,
    "claude-opus-4-7": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4-5": 200_000,
    # GPT-5 family: 400k tokens.
    "gpt-5-mini": 400_000,
    "gpt-5": 400_000,
    # GPT-4o: 128k tokens.
    "gpt-4o": 128_000,
}


def context_limit_for(model: str, settings: dict | None = None) -> int:
    """Return the effective context window size for ``model``.

    Resolution order:

    1. ``settings["compaction"]["context_limit"]`` if present and a positive int.
    2. Exact match in :data:`MODEL_CONTEXT_LIMITS`.
    3. Longest prefix match in :data:`MODEL_CONTEXT_LIMITS`.
    4. :data:`DEFAULT_CONTEXT_LIMIT`.
    """
    if settings:
        override = (settings.get("compaction") or {}).get("context_limit")
        if isinstance(override, int) and override > 0:
            return override
    if not isinstance(model, str) or not model:
        return DEFAULT_CONTEXT_LIMIT
    if model in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[model]
    # Longest-prefix match: prefer "claude-3-5-sonnet" over "claude" for a
    # dated snapshot like "claude-3-5-sonnet-20241022".
    best_key: str | None = None
    for key in MODEL_CONTEXT_LIMITS:
        if model.startswith(key) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    if best_key is not None:
        return MODEL_CONTEXT_LIMITS[best_key]
    return DEFAULT_CONTEXT_LIMIT


# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _read_usage_field(usage: Any, name: str) -> int:
    """Read ``name`` from either an attr-style or mapping-style usage object."""
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return _coerce_int(usage.get(name, 0))
    return _coerce_int(getattr(usage, name, 0))


@dataclass
class SessionTokens:
    """Running token totals for a single chat session.

    Fed from SDK ``ResultMessage.usage`` payloads after every turn. The SDK
    surfaces this as either a typed object (with ``input_tokens`` etc.) or a
    plain dict, depending on transport — :meth:`accumulate` accepts both.

    ``effective_context_used`` excludes ``cache_read_input_tokens`` because
    cache reads do not count against the prompt window in the providers we
    target; including them would trip the threshold spuriously on cache-warm
    sessions.
    """

    input_total: int = 0
    output_total: int = 0
    cache_read_total: int = 0
    last_turn_total: int = 0

    def accumulate(self, usage: Any) -> None:
        """Add one turn's usage to the running totals."""
        in_tok = _read_usage_field(usage, "input_tokens")
        out_tok = _read_usage_field(usage, "output_tokens")
        cache_tok = _read_usage_field(usage, "cache_read_input_tokens")
        self.input_total += in_tok
        self.output_total += out_tok
        self.cache_read_total += cache_tok
        self.last_turn_total = in_tok + out_tok

    def effective_context_used(self) -> int:
        """Return tokens that count against the prompt window."""
        return self.input_total + self.output_total

    def reset(self, seed_size: int = 0) -> None:
        """Clear totals; seed ``input_total`` with the size of a carry-over summary."""
        self.input_total = _coerce_int(seed_size)
        self.output_total = 0
        self.cache_read_total = 0
        self.last_turn_total = 0


# ---------------------------------------------------------------------------
# Threshold + error detection
# ---------------------------------------------------------------------------


def should_auto_compact(
    used: int, limit: int, settings: dict | None = None
) -> bool:
    """Return True when ``used`` has crossed the auto-compact threshold.

    Threshold default is 95% of ``limit``; override via
    ``settings["compaction"]["trigger_pct"]`` (a fraction in (0, 1]).
    """
    pct = 0.95
    if settings:
        candidate = (settings.get("compaction") or {}).get("trigger_pct")
        if isinstance(candidate, (int, float)) and 0 < float(candidate) <= 1:
            pct = float(candidate)
    if not isinstance(limit, int) or limit <= 0:
        return False
    return _coerce_int(used) >= int(limit * pct)


# Substrings (case-insensitive) that mean "context overflow" across providers.
_OVERFLOW_MARKERS = (
    "context_length_exceeded",
    "prompt is too long",
    "context length",
    "maximum context",
    "input length",
    "too many tokens",
)


def is_context_overflow_error(exc: BaseException) -> bool:
    """Heuristically classify ``exc`` as a context-overflow from the SDK / provider."""
    if exc is None:
        return False
    message = ""
    try:
        message = str(exc).lower()
    except Exception:
        message = ""
    for marker in _OVERFLOW_MARKERS:
        if marker in message:
            return True
    status = getattr(exc, "status_code", None)
    if status in (400, 413) and "token" in message:
        return True
    return False


# ---------------------------------------------------------------------------
# Summarisation + compaction orchestration
# ---------------------------------------------------------------------------


_SUMMARY_OPEN = "<compaction-summary>"
_SUMMARY_CLOSE = "</compaction-summary>"
_SUMMARY_MAX_BODY = 4000


def summarize_transcript(rows: list, model: str, sdk_options: Any) -> str:
    """Build a deterministic compaction summary string.

    TODO(Unit D): replace with a real ``claude_agent_sdk.query()`` round-trip
    that produces an LLM-authored summary. The wrapper format is stable so the
    rest of the pipeline (rewind seed insertion, transcript display, tests)
    will not need to change.

    The current stub yields ``"<compaction-summary>\\n[kind] text\\n...\\n</compaction-summary>"``,
    truncated to ~4000 chars of body. ``model`` and ``sdk_options`` are
    accepted for API stability but unused in the stub.
    """
    lines: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "unknown")
        text = row.get("text")
        if text is None:
            text = row.get("content") or ""
        text = str(text).replace("\n", " ").strip()
        if not text:
            continue
        lines.append(f"[{kind}] {text}")
    body = "\n".join(lines)
    if len(body) > _SUMMARY_MAX_BODY:
        body = body[:_SUMMARY_MAX_BODY]
    return f"{_SUMMARY_OPEN}\n{body}\n{_SUMMARY_CLOSE}"


def compact_session(
    doc: Any,
    sid: str,
    rows: list,
    summary: str,
    fork: bool = True,
) -> str:
    """Truncate (and optionally fork) the session, seeding it with ``summary``.

    Lazily imports :mod:`agent.rewind` and :mod:`agent.sessions` so this
    module remains importable without FreeCAD. ``rewind.truncate_session``
    gains a ``seed_summary`` keyword in Unit B; ``sessions.mark_compacted``
    is added in Unit C. Tests monkeypatch both.
    """
    from . import rewind, sessions  # lazy: avoid FreeCAD imports at top level

    new_sid = rewind.truncate_session(
        doc,
        sid,
        keep_through_row_index=-1,
        fork=fork,
        seed_summary=summary,
    )
    if fork:
        sessions.mark_compacted(doc, new_sid, parent_sid=sid)
    return new_sid


__all__ = [
    "DEFAULT_CONTEXT_LIMIT",
    "MODEL_CONTEXT_LIMITS",
    "SessionTokens",
    "compact_session",
    "context_limit_for",
    "is_context_overflow_error",
    "should_auto_compact",
    "summarize_transcript",
]
