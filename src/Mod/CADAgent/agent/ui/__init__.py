# SPDX-License-Identifier: LGPL-2.1-or-later
"""CAD Agent chat UI: native Qt ChatPanel and web QWebEngineView panel.

`WebChatPanel` is exposed lazily because it pulls in `QtWebEngineWidgets`,
which may not be available in every Qt install. Accessing the attribute
(or `from agent.ui import WebChatPanel`) triggers the import on demand.
"""

from __future__ import annotations

from .panel import ChatPanel


def __getattr__(name):
    if name == "WebChatPanel":
        from .web_panel import WebChatPanel
        return WebChatPanel
    raise AttributeError(f"module 'agent.ui' has no attribute {name!r}")


__all__ = ["ChatPanel", "WebChatPanel"]
