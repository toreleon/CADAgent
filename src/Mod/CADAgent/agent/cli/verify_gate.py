# SPDX-License-Identifier: LGPL-2.1-or-later
"""Harness-level completeness gate.

The model is unreliable about self-grading: it omits features, claims PASS,
and then declares done. A prompt instruction can describe the gate; only
code can enforce it. This module owns:

* ``rewrite_verify_for_unit`` — auto-convert inch dim values in a verify
  DSL query to mm when the parameter unit is inches. Inspect is mm-native;
  passing inches in is the #1 cause of false-negative count=0 verdicts.
* ``run_gate`` — walk every parameter with a ``verify`` query, run it
  against the worker, classify each as pass/fail, return a structured
  table. No prose; no model judgment.
* ``format_table`` — turn the table into a tight markdown block for
  ``additionalContext``.

The Stop hook in ``runtime.py`` calls ``run_gate`` after the model says
"done"; if any row failed and we haven't retried 3 times, it blocks the
stop and re-injects the failed rows so the model has to rebuild.
"""

from __future__ import annotations

import re
from typing import Any

from .. import memory as project_memory
from .doc_handle import DocHandle


# Verify DSL keywords whose values are mm dimensions. axis= and tol=
# are not dimensions; we leave them alone.
_DIM_KEYS = ("diameter", "radius", "width", "length", "z", "x", "y")
_DIM_RE = re.compile(rf"\b({'|'.join(_DIM_KEYS)})=(-?\d+(?:\.\d+)?)\b")


def rewrite_verify_for_unit(
    query: str,
    unit: str | None,
    param_value: float | None = None,
) -> str:
    """Convert inch dim values in the query to mm — but only when we are
    confident the model wrote inches. Two heuristics:

    1. If ``param_value`` is given and the query's numeric matches it
       (within rounding), the model wrote the raw inch value — convert.
    2. Otherwise, fall back to a magnitude check: any value < 10 looks
       like inches for typical CAD parts (FreeCAD is mm-native, so a
       50 mm dim shows as 50 not 1.97). Values ≥ 10 are left alone.

    This prevents the double-conversion bug where the model
    pre-converted to mm (``diameter=50.8``) but the param's unit
    was still ``in``, and the naive rewrite would do
    ``50.8 × 25.4 = 1290.32``.
    ``axis=…``/``tol=…`` are never touched — they are not lengths."""
    if not query or not unit:
        return query
    u = unit.strip().lower()
    if u not in ("in", "inch", "inches", '"'):
        return query

    def _conv(m: re.Match) -> str:
        key, val = m.group(1), float(m.group(2))
        if param_value is not None and abs(val - float(param_value)) < 1e-6:
            return f"{key}={val * 25.4:g}"
        if val < 10.0:  # looks like an inch value, not a mm-pre-converted one
            return f"{key}={val * 25.4:g}"
        return m.group(0)  # already mm — leave alone

    return _DIM_RE.sub(_conv, query)


def _summarize_result(payload: dict) -> tuple[str, str]:
    """Return (status, detail) from a worker inspect.query result payload."""
    if not isinstance(payload, dict):
        return "fail", f"unexpected payload: {payload!r}"
    if "count" in payload:
        c = payload["count"]
        return ("pass" if c > 0 else "fail"), f"count={c}"
    if "size" in payload:
        s = payload["size"]
        try:
            sx, sy, sz = (float(x) for x in s)
            non_zero = sx > 0 and sy > 0 and sz > 0
            return ("pass" if non_zero else "fail"), f"size=[{sx:.2f},{sy:.2f},{sz:.2f}]"
        except Exception:
            return "fail", f"size={s!r}"
    if "items" in payload:
        n = len(payload["items"])
        return ("pass" if n > 0 else "fail"), f"items={n}"
    if payload.get("empty"):
        return "fail", "empty"
    # Shape valid but unrecognized — call it pass; the gate's job is to
    # catch missing features, not nitpick payload shapes.
    return "pass", "ok"


async def run_gate(client, doc_path: str) -> list[dict]:
    """Run every parameter's verify query through the worker. Each row:
    ``{name, query, query_mm, status: "pass"|"fail", detail, unit}``.
    Parameters without a verify entry are skipped — they don't gate done."""
    try:
        params = project_memory.get_parameters(DocHandle(doc_path))
    except Exception as exc:
        return [{
            "name": "<sidecar>", "query": "", "query_mm": "",
            "status": "fail", "detail": f"sidecar read error: {exc}",
            "unit": "",
        }]
    rows: list[dict] = []
    for name, spec in (params or {}).items():
        if not isinstance(spec, dict):
            continue
        q = spec.get("verify")
        if not q:
            continue
        unit = spec.get("unit") or ""
        q_mm = rewrite_verify_for_unit(str(q), unit, spec.get("value"))
        try:
            r = await client.call("inspect.query", query=q_mm)
            payload = (r or {}).get("result") or {}
            status, detail = _summarize_result(payload)
            rows.append({
                "name": name, "query": str(q), "query_mm": q_mm,
                "status": status, "detail": detail, "unit": unit,
            })
        except Exception as exc:
            rows.append({
                "name": name, "query": str(q), "query_mm": q_mm,
                "status": "fail", "detail": f"{type(exc).__name__}: {exc}",
                "unit": unit,
            })
    return rows


def format_table(rows: list[dict]) -> str:
    """Compact markdown-ish table for additionalContext / final summary."""
    if not rows:
        return "(no parameters had a `verify` query — nothing to gate against)"
    out = ["param | verify (mm) | got | status", "------|-------------|-----|------"]
    for r in rows:
        flag = "PASS" if r["status"] == "pass" else "**FAIL**"
        out.append(f"{r['name']} | `{r['query_mm']}` | {r['detail']} | {flag}")
    return "\n".join(out)


def fails(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["status"] != "pass"]


# ---------------------------------------------------------------------------
# Coverage check: scan spec_from_drawing for "N × <thing>" patterns and
# require a matching count_* parameter for each. Without this, the model
# can list "8 corner cutouts" in the spec, never set a parameter for it,
# and the parameter-only gate has nothing to fail on. Coverage gives the
# harness a way to surface "feature mentioned, not built".
# ---------------------------------------------------------------------------

# Match either a leading multiplier ("12 ×", "12×", "12x", "4 X")
# or a trailing one ("R0.09 32×", "R0.09, 32 places"). The unicode
# multiplication sign × (U+00D7) is what FreeCAD title blocks use; we
# also accept the ASCII x/X and the word "places".
_COUNT_PATTERNS = (
    # "12×Ø0.14", "12 × Ø0.14", "12x R0.5" — leading multiplier.
    # The lookbehind blocks decimal fragments (3.94 × 3 has "94" but is
    # preceded by ".", not a count). The lookahead requires a feature
    # marker (Ø/R/Φ/digit) so dim-style "100 × 100" doesn't match.
    re.compile(r"(?<![\d.])(\d{1,3})\s*[×xX]\s*(?=[ØøRrΦϕ]|\d*\.?\d*\s*(?:hole|fillet|round|cut|slot))"),
    # "× 32 places", "32 places", "32 pcs"
    re.compile(r"(?<![\d.])(\d{1,3})\s*(?:places?|pcs?)\b"),
)


def _extract_spec_counts(spec_text: str) -> list[int]:
    """Pull every plausible feature-count integer out of the spec text.

    Returns a sorted, deduped list of counts. Ignores 1 (degenerate) and
    > 999 (unlikely feature counts; probably a dimension misread)."""
    if not spec_text:
        return []
    found: set[int] = set()
    for pat in _COUNT_PATTERNS:
        for m in pat.finditer(spec_text):
            try:
                n = int(m.group(1))
            except (ValueError, IndexError):
                continue
            if 2 <= n <= 999:
                found.add(n)
    return sorted(found)


def coverage_rows(doc_path: str) -> list[dict]:
    """Return one row per feature-count in spec_from_drawing that has no
    matching ``count_*`` (or ``*_count``) parameter. Rows have the same
    shape as ``run_gate`` rows so they can be merged in the same table."""
    try:
        data = project_memory.load(DocHandle(doc_path))
    except Exception:
        return []
    spec = ((data.get("design_intent") or {}).get("spec_from_drawing")) or ""
    if not isinstance(spec, str):
        return []
    expected = _extract_spec_counts(spec)
    if not expected:
        return []
    params = data.get("parameters") or {}
    # Pull every numeric value from any parameter whose name suggests
    # it's a count: count_*, *_count, n_*, num_*, *_n.
    have: set[int] = set()
    for name, spec_p in params.items():
        if not isinstance(spec_p, dict):
            continue
        n = name.lower()
        if (
            n.startswith("count_") or n.endswith("_count")
            or n.startswith("n_") or n.startswith("num_") or n.endswith("_n")
        ):
            try:
                v = int(float(spec_p.get("value", -1)))
            except (TypeError, ValueError):
                continue
            if v > 0:
                have.add(v)
    rows: list[dict] = []
    for n in expected:
        if n in have:
            continue  # has a matching count_* param — covered by run_gate
        rows.append({
            "name": f"<spec count {n}>",
            "query": f"(no count_* parameter for the '{n}×' feature in spec_from_drawing)",
            "query_mm": "",
            "status": "fail",
            "detail": f"spec mentions {n}× but no count_*={n} parameter exists",
            "unit": "",
        })
    return rows
