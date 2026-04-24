# SPDX-License-Identifier: LGPL-2.1-or-later
"""Process-wide accessor for the CLI agent's :class:`WorkerClient`.

The CLI runtime starts a single worker subprocess per invocation; verb-tool
shims (landing in later PRs) can reach it via :func:`get_worker` without
threading the client object through every call site.
"""

from __future__ import annotations

from .worker_client import WorkerClient

_WORKER: WorkerClient | None = None


def set_worker(client: WorkerClient | None) -> None:
    global _WORKER
    _WORKER = client


def get_worker() -> WorkerClient | None:
    return _WORKER
