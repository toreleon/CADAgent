# SPDX-License-Identifier: LGPL-2.1-or-later
"""Worker entry point.

Reads newline-delimited JSON requests from stdin, dispatches to registered
handlers, and writes one JSON response per line to stdout. Shuts down on
EOF. Never crashes on a bad request — malformed input becomes an error
response with ``id: 0`` if the id couldn't be recovered.

Run as::

    python -m agent.worker.server
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import TextIO

from . import registry
from .protocol import Request, Response, err, ok


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------


@registry.handler("ping")
def _ping() -> dict[str, object]:
    """Liveness probe. No FreeCAD dependency."""
    return {"pong": True, "pid": os.getpid()}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _recover_id(stripped: str) -> int:
    """Best-effort id extraction for malformed requests."""
    try:
        obj = json.loads(stripped)
    except Exception:
        return 0
    if isinstance(obj, dict) and isinstance(obj.get("id"), int):
        return obj["id"]
    return 0


async def handle_line(line: str) -> Response | None:
    """Parse and dispatch a single line. Returns ``None`` for blank lines."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        req = Request.from_json(stripped)
    except Exception as exc:
        return err(_recover_id(stripped), f"parse error: {exc}")

    try:
        result = await registry.dispatch(req.method, req.params)
    except registry.UnknownMethod:
        return err(req.id, f"unknown method: {req.method}")
    except TypeError as exc:
        return err(req.id, f"bad params for {req.method}: {exc}")
    except Exception as exc:
        # Handler failures are data, not crashes — the loop keeps serving.
        return err(req.id, f"{type(exc).__name__}: {exc}")

    return ok(req.id, result)


# ---------------------------------------------------------------------------
# stdio loop
# ---------------------------------------------------------------------------


async def _attach_stdin_reader() -> asyncio.StreamReader | None:
    """Attach an asyncio StreamReader to sys.stdin if it's a pipe/tty.

    Returns ``None`` if stdin is a regular file (e.g. shell here-strings,
    redirected files) — ``connect_read_pipe`` rejects those, so we fall
    back to synchronous line reads on a background thread.
    """
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    try:
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    except ValueError:
        return None
    return reader


def _write_response(out: TextIO, response: Response) -> None:
    out.write(response.to_json())
    out.write("\n")
    out.flush()


async def serve(out: TextIO | None = None) -> int:
    """Run the stdio loop until EOF. Returns an exit code."""
    sink = out if out is not None else sys.stdout
    reader = await _attach_stdin_reader()

    async def next_line() -> str:
        if reader is not None:
            raw = await reader.readline()
            return raw.decode("utf-8") if raw else ""
        # Fallback: blocking read in a thread. Fine for one-shot shell usage.
        return await asyncio.to_thread(sys.stdin.readline)

    while True:
        line = await next_line()
        if not line:  # EOF
            return 0
        response = await handle_line(line)
        if response is not None:
            _write_response(sink, response)


def main() -> int:
    try:
        return asyncio.run(serve())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
