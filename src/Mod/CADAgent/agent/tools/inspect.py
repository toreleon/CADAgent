# SPDX-License-Identifier: LGPL-2.1-or-later
"""Worker-backed inspection tools.

A long-lived FreeCADCmd subprocess (``WorkerClient``) holds the active doc
in memory. The headless runtime starts it at session entry; tools below
borrow it through the module-level singleton in :mod:`agent.worker.client`.
The doc path is threaded through every call so we can reload-on-mismatch
transparently — agents shouldn't have to think about worker state.

Tool names (``inspect``, ``verify_spec``, ``doc_reload``) are kept verbose
on purpose: the agent picks them by name, and shorter names would collide
with built-in SDK tools.
"""

from __future__ import annotations

from ..worker.client import WorkerClient, WorkerError, get_shared
from ._common import READ_ONLY, err, handle, ok, schema
from ._registry import cad_tool
from .categories import Category


_worker_open_doc: str | None = None  # tracks last-opened path so we skip redundant opens


async def _ensure_open(client: WorkerClient, path: str, *, reload: bool = False) -> None:
    """Make ``path`` the worker's current doc, reloading if requested."""
    global _worker_open_doc
    if reload or _worker_open_doc != path:
        await client.call("doc.open", path=path)
        _worker_open_doc = path


@cad_tool(
    "inspect",
    "Run a structured geometry query against the active .FCStd. Cheap (sub-100ms): the worker holds the doc in memory. "
    "Query DSL: 'bbox' | 'bbox of NAME' | 'face_types' | 'face_types of NAME' | "
    "'holes diameter=15 [axis=z] [tol=0.5]' | 'bosses diameter=30' | "
    "'slots width=8 length=20' | 'fillets radius=10' | 'spheres radius=250' | "
    "'solids' | 'section z=35' | 'mass [of NAME]'. "
    "Pass reload=true after a Bash script that mutated the .FCStd.",
    schema(
        query={"type": "string", "required": True},
        reload={"type": "boolean"},
    ),
    category=Category.INSPECT,
    annotations=READ_ONLY,
)
async def inspect(args):
    try:
        doc = handle(args)
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query is required")
        client = await get_shared()
        await _ensure_open(client, doc.FileName, reload=bool(args.get("reload")))
        result = await client.call("inspect.query", query=query)
        return ok(result)
    except WorkerError as exc:
        return err(f"worker: {exc}")
    except Exception as exc:
        return err(str(exc))


@cad_tool(
    "verify_spec",
    "Run every parameter's `verify` query through the worker and return a structured "
    "PASS/FAIL table. This is the same gate the harness runs at Stop — call it before "
    "declaring done so you can fix any FAIL rows BEFORE the harness blocks your stop. "
    "Inch→mm conversion is automatic; the table shows the mm-native query that ran.",
    schema(),
    category=Category.INSPECT,
    annotations=READ_ONLY,
)
async def verify_spec(args):
    try:
        # Verify gate currently lives under cli/; Step 10 moves it up to agent/.
        from ..cli import verify_gate
        doc = handle(args)
        client = await get_shared()
        await _ensure_open(client, doc.FileName, reload=True)
        rows = await verify_gate.run_gate(client, doc.FileName)
        rows.extend(verify_gate.coverage_rows(doc.FileName))
        failed = verify_gate.fails(rows)
        return ok({
            "rows": rows,
            "passed": len(rows) - len(failed),
            "failed": len(failed),
            "all_pass": len(failed) == 0,
            "table": verify_gate.format_table(rows),
        })
    except WorkerError as exc:
        return err(f"worker: {exc}")
    except Exception as exc:
        return err(str(exc))


@cad_tool(
    "doc_reload",
    "Force the worker to re-read the active .FCStd from disk. Call after a Bash script that touched the file if you "
    "haven't already passed reload=true to inspect.",
    schema(),
    category=Category.MUTATING,
)
async def doc_reload(args):
    try:
        doc = handle(args)
        client = await get_shared()
        await _ensure_open(client, doc.FileName, reload=True)
        return ok({"reloaded": doc.FileName})
    except WorkerError as exc:
        return err(f"worker: {exc}")
    except Exception as exc:
        return err(str(exc))


__all__ = ["doc_reload", "inspect", "verify_spec"]
