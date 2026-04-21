# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qt stylesheet constants and the main panel QSS string.

A VS Code dark-ish palette used by ChatPanel and its message-row widgets.
Kept in one module so the colour tokens and the CSS-ish QSS string stay in
sync and can be updated in a single place.
"""

from __future__ import annotations


# --- VS Code dark-ish palette -------------------------------------------

BG          = "#1e1e1e"
BG_ALT      = "#252526"
BG_CODE     = "#181818"
FG          = "#d4d4d4"
FG_DIM      = "#858585"
FG_MUTED    = "#6b6b6b"
BORDER      = "#303030"
BORDER_SOFT = "#2a2a2a"
ACCENT      = "#e97b3f"
ACCENT_DIM  = "#b05e2f"
OK          = "#4cb860"
WARN        = "#d8a84a"
ERR         = "#e05757"

MONO_FAMILY = "Menlo, Consolas, 'DejaVu Sans Mono', monospace"

PANEL_QSS = f"""
QWidget#CADAgentRoot {{
    background: {BG};
    color: {FG};
    font-size: 12px;
}}
QScrollArea#CADAgentStream, QWidget#CADAgentStreamBody {{
    background: {BG};
    border: none;
}}
QLabel {{
    color: {FG};
}}
QLabel[role="dim"] {{
    color: {FG_DIM};
}}
QLabel[role="muted"] {{
    color: {FG_MUTED};
}}
QLabel[role="tool_title"] {{
    color: {FG};
    font-weight: 600;
}}
QLabel[role="tool_subtitle"] {{
    color: {FG_DIM};
}}
QLabel[role="badge"] {{
    color: {FG_DIM};
    background: {BG_ALT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 1px 6px;
    font-family: {MONO_FAMILY};
    font-size: 10px;
    letter-spacing: 1px;
}}
QLabel[role="chip"] {{
    color: {FG_DIM};
    background: #2d2d2d;
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 1px 6px;
    font-size: 10px;
}}
QLabel[role="chip_accent"] {{
    color: {ACCENT};
    background: transparent;
    border: 1px solid {ACCENT_DIM};
    border-radius: 5px;
    padding: 1px 6px;
    font-size: 10px;
}}
QLabel[role="perm"] {{
    color: {FG_DIM};
    background: transparent;
    border: none;
    padding: 0 4px;
    font-size: 10px;
}}
QFrame#ComposerFrame {{
    background: #262626;
    border: 1px solid #3a3a3a;
    border-radius: 12px;
}}
QFrame#ComposerFrame:focus-within {{
    border: 1px solid {ACCENT};
}}
QPlainTextEdit#ComposerInput, QTextEdit[role="assistant"] {{
    background: transparent;
    color: {FG};
    border: none;
    selection-background-color: {ACCENT_DIM};
    font-size: 12px;
}}
QPlainTextEdit#ComposerInput {{
    padding: 0;
}}
QTextEdit[role="code"], QLabel[role="code"] {{
    background: {BG_CODE};
    color: {FG};
    border: 1px solid {BORDER_SOFT};
    border-radius: 4px;
    padding: 6px 8px;
    font-family: {MONO_FAMILY};
    font-size: 11px;
}}
QPushButton[role="icon"] {{
    background: transparent;
    color: {FG_DIM};
    border: none;
    padding: 2px 6px;
    font-size: 14px;
}}
QPushButton[role="icon"]:hover {{
    color: {FG};
}}
QPushButton#SendButton {{
    background: {ACCENT};
    color: #1b1b1b;
    border: none;
    border-radius: 13px;
    font-weight: 700;
    font-size: 13px;
}}
QPushButton#SendButton:hover {{
    background: #f08a4a;
}}
QPushButton#SendButton:disabled {{
    background: {BORDER};
    color: {FG_MUTED};
}}
QPushButton#StopButton {{
    background: transparent;
    color: {FG_DIM};
    border: 1px solid {BORDER};
    border-radius: 13px;
    font-size: 10px;
}}
QPushButton#StopButton:hover {{
    color: {ERR};
    border-color: {ERR};
}}
QPushButton[role="pill"] {{
    background: transparent;
    color: {FG_DIM};
    border: none;
    padding: 0;
    font-size: 14px;
    font-weight: 500;
}}
QPushButton[role="pill"]:hover {{
    color: {FG};
}}
QPushButton[role="ghost"] {{
    background: transparent;
    color: {FG_DIM};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 10px;
}}
QPushButton[role="ghost"]:hover {{
    color: {FG};
    border-color: {FG_MUTED};
}}
QPushButton[role="apply"] {{
    background: {OK};
    color: #0e1a10;
    border: none;
    border-radius: 4px;
    padding: 4px 12px;
    font-weight: 600;
}}
QPushButton[role="apply"]:hover {{
    background: #5ec86e;
}}
QPushButton[role="reject"] {{
    background: transparent;
    color: {FG_DIM};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 12px;
}}
QPushButton[role="reject"]:hover {{
    color: {ERR};
    border-color: {ERR};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {FG_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""
