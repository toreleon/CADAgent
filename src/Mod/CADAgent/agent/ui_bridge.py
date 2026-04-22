# SPDX-License-Identifier: LGPL-2.1-or-later
"""Bridge between async tools and the Qt UI for interactive prompts.

Tools running on the asyncio worker thread call into the ChatPanel via the
PanelProxy signals registered here. A `concurrent.futures.Future` carries
the user's answer back across the thread boundary.
"""

from __future__ import annotations

import asyncio
import concurrent.futures


_PROXY = None


def set_proxy(proxy) -> None:
    """Register the PanelProxy used to dispatch UI requests."""
    global _PROXY
    _PROXY = proxy


async def ask_user(questions: list[dict]) -> list[dict]:
    """Show an AskUserQuestion card and return the user's selection list.

    Each answer has shape ``{"header": str, "selected": str | list[str] | None,
    "skipped": bool}``. Returns once the user clicks Submit or Skip.
    """
    if _PROXY is None:
        raise RuntimeError("CAD Agent UI bridge is not initialised yet.")
    cf: concurrent.futures.Future = concurrent.futures.Future()
    _PROXY.askUserQuestion.emit(list(questions), cf)
    return await asyncio.wrap_future(cf)
