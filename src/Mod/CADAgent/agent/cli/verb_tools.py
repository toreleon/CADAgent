# SPDX-License-Identifier: LGPL-2.1-or-later
"""MCP shims that route into the long-lived ``cad_worker`` subprocess.

These are thin wrappers: argument validation + ``WorkerClient.call(...)``
plus the standard ``_ok`` / ``_err`` envelope from :mod:`mcp_tools`. The
actual work happens in the handler registered on the worker side (see
``agent.worker.handlers``). Prefer these tools over spawning
``FreeCADCmd`` via Bash — the worker keeps documents open across calls
and answers in milliseconds.
"""

from __future__ import annotations

from claude_agent_sdk import tool

from . import mcp_tools
from .worker_singleton import get_worker


async def _call_worker(method: str, params: dict) -> dict:
    """Send ``method(params)`` to the worker. Raises on missing/dead worker."""
    worker = get_worker()
    if worker is None or not worker.is_alive:
        raise RuntimeError("cad_worker is not running")
    return await worker.call(method, params)


@tool(
    "doc_inspect",
    (
        "Inspect the given .FCStd document: return name, label, dirty flag, "
        "object count, and per-object {name, label, type, visible}. Prefer "
        "this over Bash+FreeCADCmd for read-only inspection — it runs in the "
        "persistent cad_worker and reuses any already-open document."
    ),
    mcp_tools._schema(include_hidden={"type": "boolean"}),
    annotations=mcp_tools._READ_ONLY,
)
async def doc_inspect(args):
    try:
        handle = mcp_tools._handle(args)
        result = await _call_worker(
            "doc_inspect",
            {
                "doc": handle.FileName,
                "include_hidden": bool(args.get("include_hidden", True)),
            },
        )
        return mcp_tools._ok(result)
    except Exception as exc:
        return mcp_tools._err(str(exc))


# ---------------------------------------------------------------------------
# registry helpers — mirror ``mcp_tools`` so runtime can concatenate them.
# ---------------------------------------------------------------------------


TOOL_FUNCS = [doc_inspect]

TOOL_NAMES = [f.name if hasattr(f, "name") else f.__name__ for f in TOOL_FUNCS]


def allowed_tool_names(server_name: str = "cad") -> list[str]:
    return [f"mcp__{server_name}__{n}" for n in TOOL_NAMES]
