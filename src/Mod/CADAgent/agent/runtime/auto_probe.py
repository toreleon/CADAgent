# SPDX-License-Identifier: LGPL-2.1-or-later
"""PostToolUse(Bash) hook: script verdict + auto-probe + parameter verifies.

After every Bash tool call, look at the active .FCStd. If its mtime moved,
the script likely mutated geometry — reload the worker's copy and run
``inspect.probe`` (bbox + face_types + solids in one round-trip). The
result is appended to the model's next turn via ``additionalContext`` so
verification appears "for free" without the agent having to remember.

Failures degrade to a no-op: the model just doesn't get the probe line.
We never block the Bash result on probe issues — too many legitimate
intermediate states (e.g. mid-boolean) would tangle the agent loop.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .. import memory as project_memory
from ..cli.doc_handle import DocHandle
from ..worker.client import WorkerError, get_shared
from .context_builder import format_additional_context


def active_doc_path() -> str | None:
    p = (os.environ.get("CADAGENT_DOC") or "").strip()
    return p or None


# Module-global mtime cache. Reset implicitly on import; long-lived per
# agent process. Step 13 moves this onto a per-DockRuntime store.
_probe_mtimes: dict[str, float] = {}


def _summarize_probe(probe: dict) -> str:
    """Compact one-line view of the standard probe so the agent sees signal,
    not a 4 KB JSON wall of triage data each turn."""
    bbox = probe.get("bbox") or {}
    size = bbox.get("size") or [0, 0, 0]
    ft = (probe.get("face_types") or {}).get("counts") or {}
    ft_str = ",".join(f"{k}={v}" for k, v in sorted(ft.items()))
    solids = (probe.get("solids") or {}).get("items") or []
    real = [s for s in solids if s.get("n_solids", 0) >= 1]
    invalid = [s["name"] for s in real if not s.get("isValid", True)]
    parts = [
        f"bbox={size[0]:.2f}x{size[1]:.2f}x{size[2]:.2f}",
        f"faces[{ft_str}]" if ft_str else "faces[]",
        f"solids={len(real)}",
    ]
    if invalid:
        parts.append(f"invalid={invalid}")
    return " ".join(parts)


def _summarize_verify(name: str, query: str, result: dict) -> str:
    """One-line summary of a single verify query's result."""
    payload = (result or {}).get("result") or {}
    if "count" in payload:
        return f"{name} `{query}` count={payload['count']}"
    if "size" in payload:
        sz = payload["size"]
        return f"{name} `{query}` size={sz}"
    if "items" in payload:
        return f"{name} `{query}` items={len(payload['items'])}"
    return f"{name} `{query}` => {json.dumps(payload, default=str)[:120]}"


async def run_verifies(client, doc_path: str) -> list[str]:
    """Look up every parameter with a `verify` query and run it."""
    try:
        params = project_memory.get_parameters(DocHandle(doc_path))
    except Exception:
        return []
    out: list[str] = []
    for name, spec in (params or {}).items():
        q = spec.get("verify") if isinstance(spec, dict) else None
        if not q:
            continue
        try:
            r = await client.call("inspect.query", query=str(q))
            out.append(_summarize_verify(name, q, r))
        except WorkerError as exc:
            out.append(f"{name} `{q}` worker-error: {exc}")
        except Exception as exc:
            out.append(f"{name} `{q}` error: {type(exc).__name__}: {exc}")
    return out


_SCRIPT_VERDICT_RE = re.compile(r"^(RESULT|ERROR):.*", re.MULTILINE)


def extract_script_verdict(tool_response: Any) -> str | None:
    """Pull every ``RESULT:`` / ``ERROR:`` line out of a Bash tool response.

    The agent's scripts end with one structured RESULT or ERROR line that
    encodes the script's actual outcome. When the rest of the output is a
    50KB OCC-warning flood, that line gets buried by the SDK's truncation;
    we surface it explicitly so the model always sees the verdict.
    """
    if tool_response is None:
        return None
    text = ""
    if isinstance(tool_response, str):
        text = tool_response
    elif isinstance(tool_response, dict):
        content = tool_response.get("content")
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    text += "\n" + (blk.get("text") or "")
        for k in ("stdout", "stderr", "output"):
            v = tool_response.get(k)
            if isinstance(v, str):
                text += "\n" + v
    elif isinstance(tool_response, list):
        for blk in tool_response:
            if isinstance(blk, dict) and blk.get("type") == "text":
                text += "\n" + (blk.get("text") or "")
    if not text:
        return None
    full = [m.group(0) for m in _SCRIPT_VERDICT_RE.finditer(text)]
    if not full:
        return None
    return " | ".join(line[:300] for line in full[-3:])


async def post_bash_probe(input_data, tool_use_id, context):  # noqa: ANN001 — SDK callback signature
    """PostToolUse(Bash) — append script verdict + geometry probe + parameter verifies."""
    pieces: list[str] = []
    try:
        if isinstance(input_data, dict):
            verdict = extract_script_verdict(input_data.get("tool_response"))
            if verdict:
                pieces.append(f"[script] {verdict}")
    except Exception as exc:
        pieces.append(f"[script] (verdict-extract error: {exc})")
    try:
        path = active_doc_path()
        if not path or not os.path.exists(path):
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": " ".join(pieces)}} if pieces else {}
        mtime = os.path.getmtime(path)
        full_probe = _probe_mtimes.get(path) != mtime
        _probe_mtimes[path] = mtime
        client = await get_shared()
        await client.call("doc.open", path=path)
        if full_probe:
            await client.call("doc.reload")
            probe = await client.call("inspect.probe")
            pieces.append("[auto-probe] " + _summarize_probe(probe))
        verifies = await run_verifies(client, path)
        if verifies:
            pieces.append("verify: " + " ; ".join(verifies))
    except WorkerError as exc:
        pieces.append(f"[auto-probe] worker error: {exc}")
    except Exception as exc:
        pieces.append(f"[auto-probe] error: {type(exc).__name__}: {exc}")
    if not pieces:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": format_additional_context(pieces),
        }
    }


__all__ = [
    "active_doc_path",
    "extract_script_verdict",
    "post_bash_probe",
    "run_verifies",
]
