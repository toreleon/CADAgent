# SPDX-License-Identifier: LGPL-2.1-or-later
"""CAD Agent chat UI: native Qt ChatPanel, web panel, and QML panel.

``WebChatPanel`` and ``QmlChatPanel`` are exposed lazily because they pull in
optional Qt modules (``QtWebEngineWidgets`` / ``QtQuickWidgets``) that may not
be present in every Qt install.
"""

from __future__ import annotations

from .panel import ChatPanel


def __getattr__(name):
    if name == "WebChatPanel":
        from .web_panel import WebChatPanel
        return WebChatPanel
    if name == "QmlChatPanel":
        from .qml_panel import QmlChatPanel
        return QmlChatPanel
    raise AttributeError(f"module 'agent.ui' has no attribute {name!r}")


__all__ = ["ChatPanel", "WebChatPanel", "QmlChatPanel"]
