# SPDX-License-Identifier: LGPL-2.1-or-later
"""Message-row and small-widget building blocks for the ChatPanel.

Contains row types (user, assistant, thinking, system, error, tool entry,
tool-call card, turn footer) and the label/badge/chip helpers they share.
Kept separate from panel.py so the panel file focuses on stream orchestration.
"""

from __future__ import annotations

import asyncio
import json

import FreeCAD as App

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets

from ..permissions import Decision
from .styles import (
    ACCENT,
    ACCENT_DIM,
    BG_CODE,
    BORDER_SOFT,
    ERR,
    FG,
    FG_DIM,
    FG_MUTED,
    MONO_FAMILY,
    OK,
)


translate = App.Qt.translate


_SELECTABLE = QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard


def selectable(lbl: QtWidgets.QLabel) -> QtWidgets.QLabel:
    """Make a label's text selectable with a text cursor."""
    lbl.setTextInteractionFlags(_SELECTABLE)
    lbl.setCursor(QtCore.Qt.IBeamCursor)
    return lbl


def badge(text: str) -> QtWidgets.QLabel:
    """Return a small monospace badge label."""
    lbl = QtWidgets.QLabel(text)
    lbl.setProperty("role", "badge")
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    lbl.setMinimumWidth(36)
    return lbl


def chip(text: str, accent: bool = False) -> QtWidgets.QLabel:
    """Return a rounded chip-style label."""
    lbl = QtWidgets.QLabel(text)
    lbl.setProperty("role", "chip_accent" if accent else "chip")
    return lbl


def shorten_tool_name(tool_name: str) -> str:
    """Strip the `mcp__cad__` prefix from a tool name, if present."""
    if tool_name.startswith("mcp__cad__"):
        return tool_name[len("mcp__cad__"):]
    return tool_name


def summarise_tool_input(tool_input: dict) -> str:
    """Build a short human-skimmable one-line summary of tool inputs."""
    if not isinstance(tool_input, dict):
        return ""
    parts = []
    for k, v in list(tool_input.items())[:4]:
        if isinstance(v, (dict, list)):
            continue
        parts.append(f"{k}={v}")
    return "  ".join(parts)


def pretty_input(tool_input) -> str:
    """Format tool input as pretty-printed JSON."""
    try:
        return json.dumps(tool_input, indent=2, default=str)
    except Exception:
        return str(tool_input)


def preview_result(content) -> str:
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


class StatusDot(QtWidgets.QLabel):
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
        selectable(lbl)
        lay.addWidget(lbl, 1)


class _ErrorRow(QtWidgets.QWidget):
    def __init__(self, text: str):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 10, 6)
        lay.setSpacing(8)
        lay.setAlignment(QtCore.Qt.AlignTop)
        lay.addWidget(StatusDot("error"), 0, QtCore.Qt.AlignTop)
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(f"color: {ERR};")
        lbl.setWordWrap(True)
        selectable(lbl)
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
        self._short_name = shorten_tool_name(tool_name)
        self._summary = summarise_tool_input(tool_input)
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

        self._dot = StatusDot("pending")
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
            selectable(sub)
            bl.addWidget(sub)

        in_row = QtWidgets.QHBoxLayout()
        in_row.setContentsMargins(0, 0, 0, 0)
        in_row.setSpacing(8)
        in_row.setAlignment(QtCore.Qt.AlignTop)
        in_row.addWidget(badge(translate("CADAgent", "IN")), 0, QtCore.Qt.AlignTop)
        in_row.addWidget(_CodeBlock(pretty_input(tool_input)), 1)
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

        preview = preview_result(content)
        self._result_preview = preview
        badge_text = translate("CADAgent", "ERR") if is_error else translate("CADAgent", "OUT")
        self._out_row_layout.addWidget(
            badge(badge_text), 0, QtCore.Qt.AlignTop
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
        selectable(lbl)
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

        self._dot = StatusDot("active")
        outer.addWidget(self._dot, 0, QtCore.Qt.AlignTop)

        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QtWidgets.QLabel(shorten_tool_name(tool_name))
        title.setProperty("role", "tool_title")
        selectable(title)
        header.addWidget(title)
        pending = QtWidgets.QLabel(translate("CADAgent", "pending approval"))
        pending.setProperty("role", "chip_accent")
        header.addWidget(pending)
        header.addStretch(1)
        col.addLayout(header)

        summary = summarise_tool_input(tool_input)
        if summary:
            sub = QtWidgets.QLabel(summary)
            sub.setProperty("role", "tool_subtitle")
            sub.setWordWrap(True)
            selectable(sub)
            col.addWidget(sub)

        in_row = QtWidgets.QHBoxLayout()
        in_row.setContentsMargins(0, 0, 0, 0)
        in_row.setSpacing(8)
        in_row.setAlignment(QtCore.Qt.AlignTop)
        in_row.addWidget(badge(translate("CADAgent", "IN")), 0, QtCore.Qt.AlignTop)
        in_row.addWidget(_CodeBlock(pretty_input(tool_input)), 1)
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
