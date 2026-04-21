# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2026 FreeCAD Project Association <www.freecad.org>      *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful,            *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with FreeCAD; if not, write to the Free Software        *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************
"""Claude Code-style chat panel for FreeCAD.

Dark canvas, flush rows (no bubbles), status-dot + IN/OUT badged tool blocks,
and a rounded composer with a circular accent send button.
"""

from __future__ import annotations

import asyncio
import html
import json

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets

from permissions import Decision


translate = App.Qt.translate


DOCK_OBJECT_NAME = "CADAgentChatDock"

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


def _mw():
    """Return the FreeCAD main window."""
    return Gui.getMainWindow()


# --- Small widgets -------------------------------------------------------


class _StatusDot(QtWidgets.QLabel):
    """Tiny colored circle indicator."""

    STATES = {
        "pending": (FG_MUTED, False),
        "active":  (ACCENT, True),
        "done":    (OK, True),
        "error":   (ERR, True),
    }

    def __init__(self, state: str = "pending"):
        super().__init__()
        self.setFixedSize(14, 14)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        color, filled = self.STATES.get(state, self.STATES["pending"])
        pm = QtGui.QPixmap(14, 14)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(color))
        pen.setWidth(2)
        p.setPen(pen)
        if filled:
            p.setBrush(QtGui.QColor(color))
        else:
            p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(3, 3, 8, 8)
        p.end()
        self.setPixmap(pm)


_SELECTABLE = QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard


def _selectable(lbl: QtWidgets.QLabel) -> QtWidgets.QLabel:
    """Make a label's text selectable with a text cursor."""
    lbl.setTextInteractionFlags(_SELECTABLE)
    lbl.setCursor(QtCore.Qt.IBeamCursor)
    return lbl


def _badge(text: str) -> QtWidgets.QLabel:
    """Return a small monospace badge label."""
    lbl = QtWidgets.QLabel(text)
    lbl.setProperty("role", "badge")
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    lbl.setMinimumWidth(36)
    return lbl


def _chip(text: str, accent: bool = False) -> QtWidgets.QLabel:
    """Return a rounded chip-style label."""
    lbl = QtWidgets.QLabel(text)
    lbl.setProperty("role", "chip_accent" if accent else "chip")
    return lbl


# --- Message rows --------------------------------------------------------


class _UserRow(QtWidgets.QWidget):
    def __init__(self, text: str):
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 6)
        outer.setSpacing(0)

        frame = QtWidgets.QFrame()
        frame.setObjectName("UserPromptFrame")
        frame.setStyleSheet(
            f"QFrame#UserPromptFrame {{"
            f"  background: #202020;"
            f"  border-left: 2px solid {ACCENT};"
            f"  border-top-left-radius: 4px;"
            f"  border-bottom-left-radius: 4px;"
            f"  border-top-right-radius: 4px;"
            f"  border-bottom-right-radius: 4px;"
            f"}}"
        )
        fl = QtWidgets.QVBoxLayout(frame)
        fl.setContentsMargins(10, 6, 10, 8)
        fl.setSpacing(2)

        tag = QtWidgets.QLabel(translate("CADAgent", "YOU"))
        tag.setStyleSheet(
            f"color: {FG_MUTED}; font-size: 9px; font-weight: 700;"
            f"letter-spacing: 1px; background: transparent; border: none;"
        )
        fl.addWidget(tag)

        body = QtWidgets.QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(_SELECTABLE)
        body.setCursor(QtCore.Qt.IBeamCursor)
        body.setStyleSheet(
            f"color: {FG}; font-weight: 500; background: transparent; border: none;"
        )
        fl.addWidget(body)

        outer.addWidget(frame)


class _AssistantRow(QtWidgets.QWidget):
    """Flowing assistant text - flush left, markdown-rendered."""

    _DOC_STYLE = (
        f"pre, code {{ background: {BG_CODE}; color: {FG};"
        f" font-family: {MONO_FAMILY}; font-size: 11px; }}"
        f"pre {{ padding: 6px 8px; }}"
        f"code {{ padding: 0 3px; }}"
        f"h1, h2, h3 {{ color: {FG}; }}"
        f"a {{ color: {ACCENT}; }}"
    )

    def __init__(self):
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 4, 10, 6)
        lay.setSpacing(0)

        self._buffer = ""
        self._body = QtWidgets.QTextEdit()
        self._body.setReadOnly(True)
        self._body.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._body.setProperty("role", "assistant")
        self._body.setStyleSheet("QTextEdit{background:transparent;border:none;}")
        self._body.document().setDocumentMargin(0)
        self._body.document().setDefaultStyleSheet(self._DOC_STYLE)
        self._body.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._body.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._body.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
            | QtCore.Qt.TextSelectableByKeyboard
            | QtCore.Qt.LinksAccessibleByMouse
        )
        self._body.document().contentsChanged.connect(self._auto_size)
        lay.addWidget(self._body)

    def _auto_size(self):
        vp_w = max(0, self._body.viewport().width())
        doc = self._body.document()
        if vp_w > 0:
            doc.setTextWidth(vp_w)
        doc_h = int(doc.size().height()) + 4
        self._body.setFixedHeight(max(18, doc_h))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._auto_size()

    def append(self, text: str) -> None:
        self._buffer += text
        doc = self._body.document()
        if hasattr(doc, "setMarkdown"):
            doc.setMarkdown(self._buffer)
            doc.setDefaultStyleSheet(self._DOC_STYLE)
        else:
            self._body.setPlainText(self._buffer)
        self._auto_size()

    def mark_done(self) -> None:
        pass


class _ThinkingRow(QtWidgets.QWidget):
    """Italic collapsible thinking block."""

    def __init__(self, preview: str = ""):
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 4, 10, 4)
        outer.setSpacing(2)

        self._expanded = True

        self._header = QtWidgets.QPushButton(translate("CADAgent", "▾  Thinking"))
        self._header.setCursor(QtCore.Qt.PointingHandCursor)
        self._header.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {FG_DIM}; font-style: italic; font-size: 11px;"
            f" text-align: left; padding: 0; }}"
            f"QPushButton:hover {{ color: {FG}; }}"
        )
        self._header.clicked.connect(self._toggle)
        outer.addWidget(self._header, 0, QtCore.Qt.AlignLeft)

        self._body = QtWidgets.QLabel(preview[:2000])
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(_SELECTABLE)
        self._body.setCursor(QtCore.Qt.IBeamCursor)
        self._body.setStyleSheet(
            f"color: {FG_MUTED}; font-style: italic; font-size: 11px;"
            f" padding-left: 12px;"
        )
        outer.addWidget(self._body)

    def append(self, text: str) -> None:
        current = self._body.text()
        self._body.setText((current + text)[:4000])

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._body.setVisible(expanded)
        caret = "▾" if expanded else "▸"
        self._header.setText(translate("CADAgent", "{0}  Thinking").format(caret))

    def collapse(self) -> None:
        self.set_expanded(False)


class _SystemRow(QtWidgets.QWidget):
    def __init__(self, text: str):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(28, 4, 10, 4)
        lbl = QtWidgets.QLabel(text)
        lbl.setProperty("role", "muted")
        lbl.setWordWrap(True)
        _selectable(lbl)
        lay.addWidget(lbl, 1)


class _ErrorRow(QtWidgets.QWidget):
    def __init__(self, text: str):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 10, 6)
        lay.setSpacing(8)
        lay.setAlignment(QtCore.Qt.AlignTop)
        lay.addWidget(_StatusDot("error"), 0, QtCore.Qt.AlignTop)
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(f"color: {ERR};")
        lbl.setWordWrap(True)
        _selectable(lbl)
        lay.addWidget(lbl, 1)


class _CodeBlock(QtWidgets.QLabel):
    """Monospace code label. Word-wraps, selectable."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setProperty("role", "code")
        self.setTextFormat(QtCore.Qt.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)


class _ToolHeaderButton(QtWidgets.QAbstractButton):
    """Transparent button that hosts arbitrary header widgets and toggles."""

    def __init__(self):
        super().__init__()
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def paintEvent(self, _event):
        pass  # transparent; children paint themselves

    def layout_(self) -> QtWidgets.QHBoxLayout:
        return self._layout


class _ToolEntry(QtWidgets.QWidget):
    """Claude Code-style tool block with collapsible IN/OUT body.

    pending -> expanded caret
    ok done -> collapsed caret with one-line summary beside title
    error   -> expanded caret with red dot
    """

    def __init__(self, tool_name: str, tool_input: dict):
        super().__init__()
        self._short_name = _shorten_tool_name(tool_name)
        self._summary = _summarise_tool_input(tool_input)
        self._expanded = True
        self._result_preview = ""

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 10, 6)
        outer.setSpacing(4)

        self._header = _ToolHeaderButton()
        hl = self._header.layout_()

        self._caret = QtWidgets.QLabel("▾")
        self._caret.setStyleSheet(
            f"color: {FG_DIM}; font-size: 10px; background: transparent;"
        )
        self._caret.setFixedWidth(12)
        hl.addWidget(self._caret, 0, QtCore.Qt.AlignVCenter)

        self._dot = _StatusDot("pending")
        hl.addWidget(self._dot, 0, QtCore.Qt.AlignVCenter)

        self._title = QtWidgets.QLabel(self._short_name)
        self._title.setProperty("role", "tool_title")
        self._title.setStyleSheet(
            f"color: {FG}; font-weight: 600; background: transparent;"
        )
        hl.addWidget(self._title)

        self._result_chip = QtWidgets.QLabel("")
        self._result_chip.setStyleSheet(
            f"color: {FG_DIM}; background: transparent; font-size: 11px;"
        )
        self._result_chip.setWordWrap(False)
        hl.addWidget(self._result_chip, 1)

        outer.addWidget(self._header)

        # --- collapsible body ---
        self._body = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(self._body)
        bl.setContentsMargins(22, 0, 0, 0)
        bl.setSpacing(4)

        if self._summary:
            sub = QtWidgets.QLabel(self._summary)
            sub.setProperty("role", "tool_subtitle")
            sub.setWordWrap(True)
            _selectable(sub)
            bl.addWidget(sub)

        in_row = QtWidgets.QHBoxLayout()
        in_row.setContentsMargins(0, 0, 0, 0)
        in_row.setSpacing(8)
        in_row.setAlignment(QtCore.Qt.AlignTop)
        in_row.addWidget(_badge(translate("CADAgent", "IN")), 0, QtCore.Qt.AlignTop)
        in_row.addWidget(_CodeBlock(_pretty_input(tool_input)), 1)
        bl.addLayout(in_row)

        self._out_row_layout = QtWidgets.QHBoxLayout()
        self._out_row_layout.setContentsMargins(0, 0, 0, 0)
        self._out_row_layout.setSpacing(8)
        self._out_row_layout.setAlignment(QtCore.Qt.AlignTop)
        bl.addLayout(self._out_row_layout)

        outer.addWidget(self._body)

        self._header.clicked.connect(self._toggle)

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._body.setVisible(expanded)
        self._caret.setText("▾" if expanded else "▸")

    def set_result(self, content, is_error: bool) -> None:
        while self._out_row_layout.count():
            item = self._out_row_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        preview = _preview_result(content)
        self._result_preview = preview
        badge_text = translate("CADAgent", "ERR") if is_error else translate("CADAgent", "OUT")
        self._out_row_layout.addWidget(
            _badge(badge_text), 0, QtCore.Qt.AlignTop
        )
        block = _CodeBlock(preview)
        if is_error:
            block.setStyleSheet(
                f"background:{BG_CODE};color:{ERR};"
                f"border:1px solid {BORDER_SOFT};border-radius:4px;padding:6px 8px;"
                f"font-family:{MONO_FAMILY};font-size:11px;"
            )
        self._out_row_layout.addWidget(block, 1)
        self._dot.set_state("error" if is_error else "done")

        head = preview.strip().splitlines()[0] if preview.strip() else ""
        if len(head) > 80:
            head = head[:77] + "…"
        if is_error:
            self._result_chip.setText("")
            self.set_expanded(True)
        else:
            mark = "✓"
            self._result_chip.setText(f"  {mark} {head}" if head else f"  {mark}")
            self.set_expanded(False)


class _TurnFooter(QtWidgets.QWidget):
    """Thin divider plus right-aligned token/cost footer."""

    def __init__(self, text: str):
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 14, 8)
        outer.setSpacing(4)

        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet(
            f"background: {BORDER_SOFT}; border: none; max-height: 1px;"
        )
        outer.addWidget(divider)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(
            f"color: {FG_MUTED}; font-size: 10px; background: transparent;"
        )
        _selectable(lbl)
        row.addWidget(lbl, 0, QtCore.Qt.AlignRight)
        outer.addLayout(row)


class _ToolCallCard(QtWidgets.QWidget):
    """Pending tool call awaiting Apply / Reject."""

    def __init__(self, tool_name: str, tool_input: dict, future: asyncio.Future):
        super().__init__()
        self._future = future
        self._decided = False

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 10, 6)
        outer.setSpacing(8)
        outer.setAlignment(QtCore.Qt.AlignTop)

        self._dot = _StatusDot("active")
        outer.addWidget(self._dot, 0, QtCore.Qt.AlignTop)

        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QtWidgets.QLabel(_shorten_tool_name(tool_name))
        title.setProperty("role", "tool_title")
        _selectable(title)
        header.addWidget(title)
        pending = QtWidgets.QLabel(translate("CADAgent", "pending approval"))
        pending.setProperty("role", "chip_accent")
        header.addWidget(pending)
        header.addStretch(1)
        col.addLayout(header)

        summary = _summarise_tool_input(tool_input)
        if summary:
            sub = QtWidgets.QLabel(summary)
            sub.setProperty("role", "tool_subtitle")
            sub.setWordWrap(True)
            _selectable(sub)
            col.addWidget(sub)

        in_row = QtWidgets.QHBoxLayout()
        in_row.setContentsMargins(0, 0, 0, 0)
        in_row.setSpacing(8)
        in_row.setAlignment(QtCore.Qt.AlignTop)
        in_row.addWidget(_badge(translate("CADAgent", "IN")), 0, QtCore.Qt.AlignTop)
        in_row.addWidget(_CodeBlock(_pretty_input(tool_input)), 1)
        col.addLayout(in_row)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        self._apply_btn = QtWidgets.QPushButton(translate("CADAgent", "Apply"))
        self._apply_btn.setProperty("role", "apply")
        self._apply_btn.setDefault(True)
        self._reject_btn = QtWidgets.QPushButton(translate("CADAgent", "Reject"))
        self._reject_btn.setProperty("role", "reject")
        self._status = QtWidgets.QLabel("")
        self._status.setProperty("role", "muted")
        btn_row.addStretch(1)
        btn_row.addWidget(self._status)
        btn_row.addWidget(self._reject_btn)
        btn_row.addWidget(self._apply_btn)
        col.addLayout(btn_row)

        outer.addLayout(col, 1)

        self._apply_btn.clicked.connect(
            lambda: self._decide(True, "", translate("CADAgent", "applied"))
        )
        self._reject_btn.clicked.connect(
            lambda: self._decide(
                False,
                "User rejected this action.",
                translate("CADAgent", "rejected"),
            )
        )

    def _decide(self, allowed: bool, reason: str, status_text: str):
        if self._decided:
            return
        self._decided = True
        self._apply_btn.setEnabled(False)
        self._reject_btn.setEnabled(False)
        self._status.setText(status_text)
        self._dot.set_state("done" if allowed else "error")
        if not self._future.done():
            self._future.set_result(Decision(allowed=allowed, reason=reason))


# --- Composer ------------------------------------------------------------


class _Composer(QtWidgets.QFrame):
    """Rounded input area with icon buttons and a circular send button."""

    sendRequested = QtCore.Signal()
    stopRequested = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("ComposerFrame")
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(10, 8, 8, 8)
        v.setSpacing(6)

        self.input = QtWidgets.QPlainTextEdit()
        self.input.setObjectName("ComposerInput")
        self.input.setPlaceholderText(translate("CADAgent", "Ask the CAD agent…"))
        self.input.setFixedHeight(44)
        self.input.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.input.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.input.installEventFilter(self)
        v.addWidget(self.input)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        plus = QtWidgets.QPushButton("+")
        plus.setProperty("role", "pill")
        plus.setFixedSize(20, 20)
        plus.setToolTip(translate("CADAgent", "Attach (coming soon)"))
        plus.setCursor(QtCore.Qt.PointingHandCursor)

        slash = QtWidgets.QPushButton("⁄")
        slash.setProperty("role", "pill")
        slash.setFixedSize(20, 20)
        slash.setToolTip(translate("CADAgent", "Commands (coming soon)"))
        slash.setCursor(QtCore.Qt.PointingHandCursor)

        self.context_chip = _chip(translate("CADAgent", "▤  CAD Agent"), accent=False)
        self.context_chip.setToolTip(translate("CADAgent", "Current context"))

        self.permission_chip = QtWidgets.QLabel(
            translate("CADAgent", "⛨  Bypass permissions")
        )
        self.permission_chip.setProperty("role", "perm")
        self.permission_chip.hide()

        self.send_btn = QtWidgets.QPushButton("↑")
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setFixedSize(26, 26)
        self.send_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.send_btn.setToolTip(translate("CADAgent", "Send  (Ctrl+Enter)"))

        self.stop_btn = QtWidgets.QPushButton("■")
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setFixedSize(26, 26)
        self.stop_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.stop_btn.setToolTip(translate("CADAgent", "Stop"))
        self.stop_btn.hide()

        row.addWidget(plus)
        row.addWidget(slash)
        row.addSpacing(4)
        row.addWidget(self.context_chip)
        row.addStretch(1)
        row.addWidget(self.permission_chip)
        row.addSpacing(4)
        row.addWidget(self.stop_btn)
        row.addWidget(self.send_btn)
        v.addLayout(row)

        self.send_btn.clicked.connect(self.sendRequested.emit)
        self.stop_btn.clicked.connect(self.stopRequested.emit)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QtCore.QEvent.KeyPress:
            mod = event.modifiers()
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                if mod & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
                    self.sendRequested.emit()
                    return True
        return super().eventFilter(obj, event)

    def set_busy(self, busy: bool) -> None:
        self.send_btn.setVisible(not busy)
        self.stop_btn.setVisible(busy)

    def set_bypass(self, on: bool) -> None:
        self.permission_chip.setVisible(on)


# --- Helpers -------------------------------------------------------------


def _shorten_tool_name(tool_name: str) -> str:
    """Strip the `mcp__cad__` prefix from a tool name, if present."""
    if tool_name.startswith("mcp__cad__"):
        return tool_name[len("mcp__cad__"):]
    return tool_name


def _summarise_tool_input(tool_input: dict) -> str:
    """Build a short human-skimmable one-line summary of tool inputs."""
    if not isinstance(tool_input, dict):
        return ""
    parts = []
    for k, v in list(tool_input.items())[:4]:
        if isinstance(v, (dict, list)):
            continue
        parts.append(f"{k}={v}")
    return "  ".join(parts)


def _pretty_input(tool_input) -> str:
    """Format tool input as pretty-printed JSON."""
    try:
        return json.dumps(tool_input, indent=2, default=str)
    except Exception:
        return str(tool_input)


def _preview_result(content) -> str:
    """Return a trimmed textual preview of a tool result payload."""
    try:
        if isinstance(content, list) and content and isinstance(content[0], dict) and "text" in content[0]:
            return content[0]["text"][:1200]
    except Exception:
        pass
    try:
        return json.dumps(content, default=str, indent=2)[:1200]
    except Exception:
        return str(content)[:1200]


# --- Panel ---------------------------------------------------------------


class ChatPanel(QtWidgets.QWidget):
    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CADAgentRoot")
        self.setStyleSheet(PANEL_QSS)
        self._runtime = None
        self._assistant_row = None
        self._last_thinking_row: _ThinkingRow | None = None
        self._tool_entries: dict[str, _ToolEntry] = {}
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stream = QtWidgets.QScrollArea()
        self._stream.setObjectName("CADAgentStream")
        self._stream.setWidgetResizable(True)
        self._stream.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget()
        body.setObjectName("CADAgentStreamBody")
        self._stream_body = body
        self._stream_layout = QtWidgets.QVBoxLayout(body)
        self._stream_layout.setAlignment(QtCore.Qt.AlignTop)
        self._stream_layout.setContentsMargins(4, 6, 4, 6)
        self._stream_layout.setSpacing(2)
        self._stream.setWidget(body)
        root.addWidget(self._stream, 1)

        composer_wrap = QtWidgets.QWidget()
        cw = QtWidgets.QVBoxLayout(composer_wrap)
        cw.setContentsMargins(8, 4, 8, 8)
        cw.setSpacing(0)
        self._composer = _Composer()
        cw.addWidget(self._composer)
        root.addWidget(composer_wrap)

        self._composer.sendRequested.connect(self._on_send_clicked)
        self._composer.stopRequested.connect(self._on_stop_clicked)

        self._append(
            _SystemRow(
                translate("CADAgent", "CAD Agent ready. Ask me to model something.")
            )
        )

    # --- External API -------------------------------------------------

    def attach_runtime(self, runtime) -> None:
        """Bind an agent runtime and sync permission-mode UI state."""
        self._runtime = runtime
        try:
            mode = App.ParamGet(
                "User parameter:BaseApp/Preferences/Mod/CADAgent"
            ).GetString("PermissionMode", "default")
            self._composer.set_bypass(mode == "bypassPermissions")
        except Exception:
            pass

    def append_assistant_text(self, text: str) -> None:
        if self._assistant_row is None:
            self._collapse_thinking()
            self._assistant_row = _AssistantRow()
            self._append(self._assistant_row)
        self._assistant_row.append(text)

    def append_thinking(self, text: str) -> None:
        self._close_assistant()
        if self._last_thinking_row is not None:
            self._last_thinking_row.append(text)
            return
        row = _ThinkingRow(text)
        self._last_thinking_row = row
        self._append(row)

    def announce_tool_use(self, tool_use_id: str, name: str, tool_input: dict) -> None:
        self._close_assistant()
        self._collapse_thinking()
        entry = _ToolEntry(name, tool_input)
        if tool_use_id:
            self._tool_entries[tool_use_id] = entry
        self._append(entry)

    def announce_tool_result(self, tool_use_id: str, content, is_error: bool) -> None:
        entry = self._tool_entries.pop(tool_use_id, None)
        if entry is not None:
            entry.set_result(content, is_error)
        else:
            # Fallback: render a standalone OUT block so nothing is lost.
            row = QtWidgets.QWidget()
            rl = QtWidgets.QHBoxLayout(row)
            rl.setContentsMargins(28, 2, 10, 2)
            rl.setSpacing(8)
            rl.setAlignment(QtCore.Qt.AlignTop)
            badge_text = (
                translate("CADAgent", "ERR") if is_error else translate("CADAgent", "OUT")
            )
            rl.addWidget(_badge(badge_text), 0, QtCore.Qt.AlignTop)
            rl.addWidget(_CodeBlock(_preview_result(content)), 1)
            self._append(row)

    def record_result(self, msg) -> None:
        self._close_assistant()
        self._collapse_thinking()
        cost = getattr(msg, "total_cost_usd", None) or getattr(msg, "cost_usd", None)
        usage = getattr(msg, "usage", None)
        tokens = None
        if usage is not None:
            in_tok = getattr(usage, "input_tokens", None)
            out_tok = getattr(usage, "output_tokens", None)
            if in_tok is None and isinstance(usage, dict):
                in_tok = usage.get("input_tokens")
                out_tok = usage.get("output_tokens")
            if in_tok is not None or out_tok is not None:
                tokens = (in_tok or 0) + (out_tok or 0)
        parts = []
        if tokens is not None:
            parts.append(translate("CADAgent", "{0} tok").format(f"{tokens:,}"))
        if cost is not None:
            parts.append(f"${cost:.4f}")
        text = " · ".join(parts) if parts else translate("CADAgent", "turn complete")
        self._append(_TurnFooter(text))

    def mark_turn_complete(self) -> None:
        self._close_assistant()
        self._composer.set_busy(False)
        self._composer.input.setFocus()

    def show_error(self, message: str) -> None:
        self._close_assistant()
        self._append(_ErrorRow(message))

    def request_permission_threadsafe(
        self, tool_name: str, tool_input: dict, cf_future
    ) -> None:
        """Create a pending card whose Apply/Reject resolves ``cf_future``.

        Called from the Qt GUI thread (via the PanelProxy signal). ``cf_future``
        is a concurrent.futures.Future awaited by the async worker thread.
        """
        self._close_assistant()
        card = _ToolCallCard(tool_name, tool_input, cf_future)
        self._append(card)

    # --- Internals ----------------------------------------------------

    def _append(self, widget: QtWidgets.QWidget) -> None:
        self._stream_layout.addWidget(widget)
        QtCore.QTimer.singleShot(
            0,
            lambda: self._stream.verticalScrollBar().setValue(
                self._stream.verticalScrollBar().maximum()
            ),
        )

    def _close_assistant(self) -> None:
        if self._assistant_row is not None:
            self._assistant_row.mark_done()
            self._assistant_row = None

    def _collapse_thinking(self) -> None:
        if self._last_thinking_row is not None:
            self._last_thinking_row.collapse()
            self._last_thinking_row = None

    def _on_send_clicked(self) -> None:
        text = self._composer.input.toPlainText().strip()
        if not text:
            return
        if self._runtime is None:
            self.show_error(translate("CADAgent", "Agent runtime is not ready yet."))
            return
        self._composer.input.clear()
        self._append(_UserRow(text))
        self._composer.set_busy(True)
        self._runtime.submit(text)

    def _on_stop_clicked(self) -> None:
        if self._runtime is None:
            return
        self._runtime.interrupt()
        self._composer.set_busy(False)


def get_or_create_dock() -> QtWidgets.QDockWidget:
    """Return the CAD Agent dock widget, creating it on first use."""
    mw = _mw()
    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if existing is not None:
        return existing

    dock = QtWidgets.QDockWidget(translate("CADAgent", "CAD Agent"), mw)
    dock.setObjectName(DOCK_OBJECT_NAME)
    panel = ChatPanel(dock)
    ChatPanel._instance = panel
    dock.setWidget(panel)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.resize(440, dock.height())
    return dock


def get_panel():
    """Return the singleton ChatPanel instance, if any."""
    return ChatPanel._instance
