# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qt stylesheet for the ChatPanel.

FreeCAD ships its own application stylesheet that paints dock contents.
We deliberately do NOT set backgrounds on the panel root / scroll area so
FreeCAD's theme shows through. Only the pieces that need a distinct look
(composer frame, code blocks, send button, status dots) are styled here.
"""

from __future__ import annotations


# --- Brand / semantic colors (stay fixed across themes) -----------------

ACCENT      = "#e97b3f"
ACCENT_DIM  = "#b05e2f"
OK          = "#4cb860"
WARN        = "#d8a84a"
ERR         = "#e05757"

# --- Theme-adaptive tokens ---------------------------------------------
#
# These are substituted into QSS strings. `palette(...)` resolves at paint
# time so text/borders track the active theme. Backgrounds use neutral
# translucent overlays so they read as a subtle panel on either light or
# dark FreeCAD themes without hard-coding a color.

def _resolve_fg() -> str:
    """Pick pure white or black for chat text based on theme brightness."""
    try:
        from PySide import QtGui, QtWidgets  # type: ignore
    except ImportError:
        try:
            from PySide6 import QtGui, QtWidgets  # type: ignore
        except ImportError:
            from PySide2 import QtGui, QtWidgets  # type: ignore
    app = QtWidgets.QApplication.instance()
    if app is None:
        return "#ffffff"
    pal = app.palette()
    win = pal.color(QtGui.QPalette.Window)
    txt = pal.color(QtGui.QPalette.WindowText)
    # Prefer whichever of the palette pair is brighter than its partner;
    # fall back to WindowText brightness when Window is unreliable (some
    # FreeCAD themes paint dark backgrounds via QSS while leaving the
    # palette Window light).
    if txt.lightness() > win.lightness():
        return "#ffffff" if txt.lightness() > 127 else "#000000"
    return "#000000" if win.lightness() > 127 else "#ffffff"


FG          = "palette(text)"  # fallback; real value resolved in build_panel_qss()
FG_DIM      = "palette(mid)"
FG_MUTED    = "palette(mid)"
BORDER      = "palette(mid)"
BORDER_SOFT = "palette(midlight)"

# Soft surface tints — render darker on light themes, lighter on dark.
SURFACE_1   = "rgba(127, 127, 127, 0.10)"   # composer / user bubble
SURFACE_2   = "rgba(127, 127, 127, 0.18)"   # code blocks

BG_ALT      = SURFACE_1
BG_CODE     = SURFACE_2
BG_INPUT    = SURFACE_1
BG_USER     = SURFACE_1

MONO_FAMILY = "Menlo, Consolas, 'DejaVu Sans Mono', monospace"

PANEL_QSS = f"""
/* Root + stream: no background — inherit FreeCAD's theme. */
QWidget#CADAgentRoot {{
    color: {FG};
    font-size: 12px;
}}
QScrollArea#CADAgentStream, QWidget#CADAgentStreamBody {{
    background: transparent;
    border: none;
}}

QLabel {{
    color: {FG};
    background: transparent;
}}
QLabel[role="dim"]      {{ color: {FG_DIM}; }}
QLabel[role="muted"]    {{ color: {FG_MUTED}; font-size: 11px; }}
QLabel[role="tool_title"]    {{ color: {FG}; font-weight: 600; }}
QLabel[role="tool_subtitle"] {{ color: {FG_DIM}; }}
QLabel[role="io_label"] {{
    color: {FG_MUTED};
    font-family: {MONO_FAMILY};
    font-size: 10px;
    letter-spacing: 1px;
    padding: 4px 0 0 0;
}}
QLabel[role="badge"] {{
    color: {FG_MUTED};
    background: transparent;
    border: none;
    font-family: {MONO_FAMILY};
    font-size: 10px;
    letter-spacing: 1px;
}}
QLabel[role="chip"] {{
    color: {FG_DIM};
    background: {BG_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
}}
QLabel[role="chip_accent"] {{
    color: {ACCENT};
    background: transparent;
    border: 1px solid {ACCENT_DIM};
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
}}
QLabel[role="perm"] {{
    color: {FG_MUTED};
    background: transparent;
    border: none;
    padding: 0 4px;
    font-size: 11px;
}}

QTextEdit[role="code"], QLabel[role="code"] {{
    background: {BG_CODE};
    color: {FG};
    border: 1px solid {BORDER_SOFT};
    border-radius: 4px;
    padding: 6px 10px;
    font-family: {MONO_FAMILY};
    font-size: 11px;
}}
QTextEdit[role="assistant"] {{
    background: transparent;
    color: {FG};
    border: none;
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    font-size: 12px;
}}

QFrame#ComposerFrame {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#ComposerFrame:focus-within {{
    border-color: {ACCENT_DIM};
}}
QPlainTextEdit#ComposerInput {{
    background: transparent;
    color: {FG};
    border: none;
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    font-size: 12px;
    padding: 0;
}}

QPushButton[role="icon"], QToolButton[role="icon"] {{
    background: transparent;
    color: {FG};
    border: none;
    padding: 2px 4px;
    font-size: 14px;
}}
QPushButton[role="icon"]:hover, QToolButton[role="icon"]:hover {{
    color: {ACCENT};
}}
QPushButton#SendButton {{
    background: {ACCENT};
    color: white;
    border: none;
    border-radius: 12px;
    font-weight: 700;
    font-size: 13px;
}}
QPushButton#SendButton:hover   {{ background: #f08a4a; }}
QPushButton#SendButton:disabled {{ background: {BG_ALT}; color: {FG_MUTED}; }}

QPushButton#StopButton {{
    background: transparent;
    color: {FG_DIM};
    border: 1px solid {BORDER};
    border-radius: 12px;
    font-size: 10px;
}}
QPushButton#StopButton:hover {{ color: {ERR}; border-color: {ERR}; }}

QPushButton[role="pill"] {{
    background: transparent;
    color: {FG_MUTED};
    border: none;
    padding: 0;
    font-size: 15px;
    font-weight: 500;
}}
QPushButton[role="pill"]:hover {{ color: {FG}; }}

QPushButton[role="ghost"] {{
    background: transparent;
    color: {FG_DIM};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 10px;
}}
QPushButton[role="ghost"]:hover {{ color: {FG}; border-color: {FG_MUTED}; }}

QPushButton[role="apply"] {{
    background: {OK};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 4px 12px;
    font-weight: 600;
}}
QPushButton[role="apply"]:hover {{ background: #5ec86e; }}

QPushButton[role="reject"] {{
    background: transparent;
    color: {FG_DIM};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 12px;
}}
QPushButton[role="reject"]:hover {{ color: {ERR}; border-color: {ERR}; }}

QFrame#HistoryPopup {{
    background: {BG_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLineEdit#HistorySearch {{
    background: {BG_INPUT};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: palette(highlight);
}}
QLineEdit#HistorySearch:focus {{ border-color: {ACCENT}; }}

QWidget[role="history_row"] {{ background: transparent; border-radius: 6px; }}
QWidget[role="history_row"]:hover {{ background: {BG_ALT}; }}
QWidget[role="history_row_active"] {{ background: {BG_ALT}; border-radius: 6px; }}
QLabel[role="history_title"] {{ color: {FG}; font-size: 12px; }}
QLabel[role="history_time"]  {{ color: {FG_MUTED}; font-size: 11px; }}
QLabel[role="history_empty"] {{ color: {FG_MUTED}; font-size: 11px; padding: 16px 8px; }}

QToolButton[role="row_action"] {{
    background: transparent;
    color: {FG_MUTED};
    border: none;
    padding: 2px 4px;
    font-size: 12px;
}}
QToolButton[role="row_action"]:hover {{ color: {ERR}; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {FG_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def build_panel_qss() -> str:
    """Return PANEL_QSS with FG resolved to pure white/black for the current theme."""
    return PANEL_QSS.replace("palette(text)", _resolve_fg())
