# SPDX-License-Identifier: LGPL-2.1-or-later
"""CAD Agent chat UI — QML-only panel.

The legacy QWidget-based ``ChatPanel`` and the web (``QWebEngineView``) panel
have been removed; :class:`QmlChatPanel` is the single entry point.
"""

from __future__ import annotations

from .qml_panel import QmlChatPanel


__all__ = ["QmlChatPanel"]
