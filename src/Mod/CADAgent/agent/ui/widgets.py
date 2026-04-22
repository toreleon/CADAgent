# SPDX-License-Identifier: LGPL-2.1-or-later
"""Message-row building blocks for the ChatPanel.

Claude Code-style layout: a left gutter with a small status bullet, and a
content column holding the row title, IN/OUT labels, and code blocks.
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
    BG_USER,
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

# Left gutter width: bullet + breathing room. Content column starts here.
GUTTER = 22
# IO label column width ("IN" / "OUT").
IO_COL = 30


def selectable(lbl: QtWidgets.QLabel) -> QtWidgets.QLabel:
    lbl.setTextInteractionFlags(_SELECTABLE)
    lbl.setCursor(QtCore.Qt.IBeamCursor)
    return lbl


def badge(text: str) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    lbl.setProperty("role", "badge")
    lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
    lbl.setMinimumWidth(IO_COL)
    return lbl


def chip(text: str, accent: bool = False) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    lbl.setProperty("role", "chip_accent" if accent else "chip")
    return lbl


def shorten_tool_name(tool_name: str) -> str:
    if tool_name.startswith("mcp__cad__"):
        return tool_name[len("mcp__cad__"):]
    return tool_name


def summarise_tool_input(tool_input: dict) -> str:
    if not isinstance(tool_input, dict):
        return ""
    # Prefer a natural one-liner: first short string value wins.
    for k in ("description", "command", "file_path", "path", "query", "pattern"):
        v = tool_input.get(k)
        if isinstance(v, str) and v.strip():
            s = v.strip().splitlines()[0]
            return s[:120]
    parts = []
    for k, v in list(tool_input.items())[:3]:
        if isinstance(v, (dict, list)):
            continue
        parts.append(f"{k}={v}")
    return "  ".join(parts)[:120]


def pretty_input(tool_input) -> str:
    try:
        return json.dumps(tool_input, indent=2, default=str)
    except Exception:
        return str(tool_input)


def preview_result(content) -> str:
    try:
        if isinstance(content, list) and content and isinstance(content[0], dict) and "text" in content[0]:
            return content[0]["text"][:1200]
    except Exception:
        pass
    try:
        return json.dumps(content, default=str, indent=2)[:1200]
    except Exception:
        return str(content)[:1200]


def _palette_mid() -> str:
    """Resolve the current app palette's Mid color as a hex string."""
    app = QtWidgets.QApplication.instance()
    if app is not None:
        return app.palette().color(QtGui.QPalette.Mid).name()
    return "#888888"


class StatusDot(QtWidgets.QLabel):
    """Tiny circle used in the left gutter: filled when done, ring when idle."""

    STATES = {
        "pending": (None, False),  # None → use palette Mid at paint time
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
        if color is None:
            color = _palette_mid()
        pm = QtGui.QPixmap(14, 14)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(color))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(QtGui.QColor(color) if filled else QtCore.Qt.NoBrush)
        p.drawEllipse(3, 3, 8, 8)
        p.end()
        self.setPixmap(pm)


def _gutter(dot: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget:
    """Left column with a top-aligned status bullet (or blank)."""
    w = QtWidgets.QWidget()
    w.setFixedWidth(GUTTER)
    w.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(0, 3, 0, 0)
    lay.setSpacing(0)
    if dot is not None:
        lay.addWidget(dot, 0, QtCore.Qt.AlignTop | QtCore.Qt.AlignHCenter)
    return w


# --- message rows -------------------------------------------------------

class _UserRow(QtWidgets.QWidget):
    """User prompt: a compact dark block, flush with the content column."""

    def __init__(self, text: str):
        super().__init__()
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(10, 10, 12, 6)
        outer.setSpacing(0)
        outer.addSpacing(GUTTER - 10)

        frame = QtWidgets.QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {BG_USER}; border-radius: 6px; }}"
        )
        fl = QtWidgets.QVBoxLayout(frame)
        fl.setContentsMargins(12, 8, 12, 8)
        fl.setSpacing(2)

        body = QtWidgets.QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(_SELECTABLE)
        body.setCursor(QtCore.Qt.IBeamCursor)
        body.setStyleSheet(
            f"color: {FG}; background: transparent; border: none;"
        )
        fl.addWidget(body)

        outer.addWidget(frame, 1)


class _AssistantRow(QtWidgets.QWidget):
    """Flowing assistant text — content column, no gutter bullet."""

    @staticmethod
    def _doc_style() -> str:
        # QTextDocument CSS doesn't evaluate palette(); resolve real hex now.
        # Derive code bg by blending window text ~15% into the window color so
        # it reads as a subtle inset on either light or dark FreeCAD themes.
        app = QtWidgets.QApplication.instance()
        pal = app.palette() if app is not None else QtGui.QPalette()
        win = pal.color(QtGui.QPalette.Window)
        txt = pal.color(QtGui.QPalette.WindowText)
        code_bg = QtGui.QColor(
            int(win.red() * 0.85 + txt.red() * 0.15),
            int(win.green() * 0.85 + txt.green() * 0.15),
            int(win.blue() * 0.85 + txt.blue() * 0.15),
        ).name()
        fg = txt.name()
        return (
            f"pre, code {{ background: {code_bg}; color: {fg};"
            f" font-family: {MONO_FAMILY}; font-size: 11px; }}"
            f"pre {{ padding: 6px 8px; }}"
            f"code {{ padding: 0 3px; }}"
            f"h1, h2, h3 {{ color: {fg}; }}"
            f"a {{ color: {ACCENT}; }}"
            f"ul, ol {{ margin-left: 16px; }}"
        )

    def __init__(self):
        super().__init__()
        self._DOC_STYLE = self._doc_style()
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum
        )
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 12, 4)
        lay.setSpacing(0)
        lay.addWidget(_gutter())

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
        self._body.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self._body.setFixedHeight(18)
        self._body.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
            | QtCore.Qt.TextSelectableByKeyboard
            | QtCore.Qt.LinksAccessibleByMouse
        )
        lay.addWidget(self._body, 1)

        # Debounce renders: coalesce rapid delta bursts so Qt gets paint
        # cycles between updates. ~33ms → ~30 fps, smooth without waste.
        self._render_timer = QtCore.QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(33)
        self._render_timer.timeout.connect(self._flush_render)

    def _auto_size(self):
        vp_w = self._body.viewport().width()
        if vp_w <= 0:
            QtCore.QTimer.singleShot(0, self._auto_size)
            return
        doc = self._body.document()
        doc.setTextWidth(vp_w)
        doc_h = int(doc.size().height()) + 2
        self._body.setFixedHeight(max(18, doc_h))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._auto_size()

    def append(self, text: str) -> None:
        self._buffer += text
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush_render(self) -> None:
        doc = self._body.document()
        if hasattr(doc, "setMarkdown"):
            doc.setMarkdown(self._buffer)
            doc.setDefaultStyleSheet(self._DOC_STYLE)
        else:
            self._body.setPlainText(self._buffer)
        self._auto_size()

    def mark_done(self) -> None:
        self._render_timer.stop()
        self._flush_render()


class _ThinkingRow(QtWidgets.QWidget):
    """Gutter bullet + muted 'Thinking' label, click to expand body."""

    def __init__(self, preview: str = ""):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 12, 4)
        lay.setSpacing(0)

        self._dot = StatusDot("pending")
        lay.addWidget(_gutter(self._dot))

        content = QtWidgets.QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(2)
        lay.addLayout(content, 1)

        self._expanded = False

        self._header = QtWidgets.QPushButton(translate("CADAgent", "Thinking"))
        self._header.setCursor(QtCore.Qt.PointingHandCursor)
        self._header.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {FG_MUTED}; font-size: 12px;"
            f" text-align: left; padding: 0; }}"
            f"QPushButton:hover {{ color: {FG_DIM}; }}"
        )
        self._header.clicked.connect(self._toggle)
        content.addWidget(self._header, 0, QtCore.Qt.AlignLeft)

        self._body = QtWidgets.QLabel(preview[:2000])
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(_SELECTABLE)
        self._body.setCursor(QtCore.Qt.IBeamCursor)
        self._body.setStyleSheet(
            f"color: {FG_MUTED}; font-size: 11px; padding: 2px 0 0 0;"
        )
        self._body.setVisible(False)
        content.addWidget(self._body)

    def append(self, text: str) -> None:
        current = self._body.text()
        self._body.setText((current + text)[:4000])

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._body.setVisible(expanded and bool(self._body.text()))

    def collapse(self) -> None:
        self._dot.set_state("done")
        self.set_expanded(False)


class _SystemRow(QtWidgets.QWidget):
    def __init__(self, text: str):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 12, 4)
        lay.setSpacing(0)
        lay.addWidget(_gutter())
        lbl = QtWidgets.QLabel(text)
        lbl.setProperty("role", "muted")
        lbl.setWordWrap(True)
        selectable(lbl)
        lay.addWidget(lbl, 1)


class _ErrorRow(QtWidgets.QWidget):
    def __init__(self, text: str):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 12, 6)
        lay.setSpacing(0)
        lay.addWidget(_gutter(StatusDot("error")))
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


class _ToolEntry(QtWidgets.QWidget):
    """Tool block: gutter dot + '**Name**  subtitle' header, indented IN/OUT.

    Click the title to toggle body visibility. The body is visible while
    pending and collapses automatically once a successful result lands.
    """

    def __init__(self, tool_name: str, tool_input: dict):
        super().__init__()
        self._short_name = shorten_tool_name(tool_name)
        self._summary = summarise_tool_input(tool_input)
        self._expanded = True
        self._tool_input = tool_input

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(10, 6, 12, 6)
        outer.setSpacing(0)

        self._dot = StatusDot("pending")
        outer.addWidget(_gutter(self._dot))

        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        outer.addLayout(col, 1)

        # --- clickable header: bold name + subtitle
        self._header_btn = QtWidgets.QPushButton()
        self._header_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._header_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " text-align: left; padding: 0; }"
        )
        hl = QtWidgets.QHBoxLayout(self._header_btn)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)

        self._title = QtWidgets.QLabel(self._short_name)
        self._title.setProperty("role", "tool_title")
        hl.addWidget(self._title)

        self._sub = QtWidgets.QLabel(self._summary)
        self._sub.setProperty("role", "tool_subtitle")
        self._sub.setWordWrap(False)
        hl.addWidget(self._sub, 1)

        self._header_btn.clicked.connect(self._toggle)
        col.addWidget(self._header_btn)

        # --- collapsible body
        self._body = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(self._body)
        bl.setContentsMargins(0, 2, 0, 0)
        bl.setSpacing(4)

        self._body_stack = bl

        in_row = self._make_io_row(translate("CADAgent", "IN"), pretty_input(tool_input), False)
        bl.addWidget(in_row)

        self._out_row: QtWidgets.QWidget | None = None

        col.addWidget(self._body)

    def _make_io_row(self, label_text: str, code_text: str, is_error: bool) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.setAlignment(QtCore.Qt.AlignTop)

        label = QtWidgets.QLabel(label_text)
        label.setProperty("role", "io_label")
        label.setFixedWidth(IO_COL)
        rl.addWidget(label, 0, QtCore.Qt.AlignTop)

        block = _CodeBlock(code_text)
        if is_error:
            block.setStyleSheet(
                f"background:{BG_CODE};color:{ERR};"
                f"border:1px solid {BORDER_SOFT};border-radius:4px;padding:6px 10px;"
                f"font-family:{MONO_FAMILY};font-size:11px;"
            )
        rl.addWidget(block, 1)
        return row

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._body.setVisible(expanded)

    def set_result(self, content, is_error: bool) -> None:
        if self._out_row is not None:
            self._out_row.deleteLater()
            self._out_row = None

        preview = preview_result(content)
        label = translate("CADAgent", "ERR") if is_error else translate("CADAgent", "OUT")
        row = self._make_io_row(label, preview, is_error)
        self._body_stack.addWidget(row)
        self._out_row = row

        self._dot.set_state("error" if is_error else "done")
        # Successful runs collapse to keep the stream skimmable.
        self.set_expanded(is_error)


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
        outer.setContentsMargins(10, 6, 12, 6)
        outer.setSpacing(0)

        self._dot = StatusDot("active")
        outer.addWidget(_gutter(self._dot))

        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        outer.addLayout(col, 1)

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
        in_label = QtWidgets.QLabel(translate("CADAgent", "IN"))
        in_label.setProperty("role", "io_label")
        in_label.setFixedWidth(IO_COL)
        in_row.addWidget(in_label, 0, QtCore.Qt.AlignTop)
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


class _OptionButton(QtWidgets.QPushButton):
    """Checkable option row: bold label on top, optional description beneath."""

    def __init__(self, label: str, description: str, multi: bool):
        super().__init__()
        self._label_text = label
        self._multi = multi
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setProperty("role", "option")
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        self._marker = QtWidgets.QLabel("◻" if multi else "○")
        self._marker.setFixedWidth(14)
        self._marker.setStyleSheet(f"color: {FG_MUTED}; background: transparent;")
        lay.addWidget(self._marker, 0, QtCore.Qt.AlignTop)

        textcol = QtWidgets.QVBoxLayout()
        textcol.setContentsMargins(0, 0, 0, 0)
        textcol.setSpacing(2)
        lay.addLayout(textcol, 1)

        lbl = QtWidgets.QLabel(label)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {FG}; font-weight: 600; background: transparent;"
        )
        textcol.addWidget(lbl)

        if description:
            d = QtWidgets.QLabel(description)
            d.setWordWrap(True)
            d.setStyleSheet(
                f"color: {FG_MUTED}; font-size: 11px; background: transparent;"
            )
            textcol.addWidget(d)

        self.toggled.connect(self._on_toggled)

    def label(self) -> str:
        return self._label_text

    def _on_toggled(self, checked: bool) -> None:
        if self._multi:
            self._marker.setText("☑" if checked else "◻")
        else:
            self._marker.setText("●" if checked else "○")
        color = ACCENT if checked else FG_MUTED
        self._marker.setStyleSheet(f"color: {color}; background: transparent;")


class _AskUserQuestionCard(QtWidgets.QWidget):
    """Inline card asking the user one or more multiple-choice questions.

    ``questions`` is a list of ``{question, header?, options: [{label,
    description?}], multiSelect?}`` dicts. On Submit / Skip the supplied
    ``concurrent.futures.Future`` is resolved with a list of answers shaped as
    ``{header, selected, skipped}`` where ``selected`` is a single label for
    single-select questions, a list of labels for multi-select, and ``None``
    when the user skipped.
    """

    def __init__(self, questions: list[dict], future):
        super().__init__()
        self._future = future
        self._decided = False
        self._questions = list(questions or [])
        self._groups: list[tuple[dict, list[_OptionButton]]] = []

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(10, 6, 12, 6)
        outer.setSpacing(0)

        self._dot = StatusDot("active")
        outer.addWidget(_gutter(self._dot))

        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        outer.addLayout(col, 1)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QtWidgets.QLabel(translate("CADAgent", "Ask user"))
        title.setProperty("role", "tool_title")
        header.addWidget(title)
        pending = QtWidgets.QLabel(translate("CADAgent", "awaiting answer"))
        pending.setProperty("role", "chip_accent")
        header.addWidget(pending)
        header.addStretch(1)
        col.addLayout(header)

        for q in self._questions:
            col.addWidget(self._build_question(q))

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        self._status = QtWidgets.QLabel("")
        self._status.setProperty("role", "muted")
        self._skip_btn = QtWidgets.QPushButton(translate("CADAgent", "Skip"))
        self._skip_btn.setProperty("role", "reject")
        self._submit_btn = QtWidgets.QPushButton(translate("CADAgent", "Submit"))
        self._submit_btn.setProperty("role", "apply")
        self._submit_btn.setDefault(True)
        btn_row.addStretch(1)
        btn_row.addWidget(self._status)
        btn_row.addWidget(self._skip_btn)
        btn_row.addWidget(self._submit_btn)
        col.addLayout(btn_row)

        self._submit_btn.clicked.connect(self._on_submit)
        self._skip_btn.clicked.connect(self._on_skip)

    def _build_question(self, q: dict) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)

        header_text = str(q.get("header") or "").strip()
        q_text = str(q.get("question") or "").strip()
        multi = bool(q.get("multiSelect"))

        if q_text:
            qlbl = QtWidgets.QLabel(q_text)
            qlbl.setWordWrap(True)
            qlbl.setStyleSheet(
                f"color: {FG}; font-weight: 600; background: transparent;"
            )
            bl.addWidget(qlbl)
        if header_text and header_text != q_text:
            hdr = QtWidgets.QLabel(header_text)
            hdr.setProperty("role", "muted")
            hdr.setWordWrap(True)
            bl.addWidget(hdr)

        group = QtWidgets.QButtonGroup(box)
        group.setExclusive(not multi)
        buttons: list[_OptionButton] = []
        for opt in (q.get("options") or []):
            label = str(opt.get("label") or "").strip()
            if not label:
                continue
            desc = str(opt.get("description") or "").strip()
            btn = _OptionButton(label, desc, multi)
            group.addButton(btn)
            buttons.append(btn)
            bl.addWidget(btn)

        self._groups.append((q, buttons))
        return box

    def _collect_answers(self) -> list[dict]:
        answers = []
        for q, buttons in self._groups:
            multi = bool(q.get("multiSelect"))
            chosen = [b.label() for b in buttons if b.isChecked()]
            answers.append({
                "header": q.get("header") or q.get("question") or "",
                "selected": chosen if multi else (chosen[0] if chosen else None),
                "skipped": False,
            })
        return answers

    def _skipped_answers(self) -> list[dict]:
        answers = []
        for q, _buttons in self._groups:
            multi = bool(q.get("multiSelect"))
            answers.append({
                "header": q.get("header") or q.get("question") or "",
                "selected": [] if multi else None,
                "skipped": True,
            })
        return answers

    def _on_submit(self) -> None:
        if self._decided:
            return
        self._finish(
            self._collect_answers(),
            translate("CADAgent", "submitted"),
            "done",
        )

    def _on_skip(self) -> None:
        if self._decided:
            return
        self._finish(
            self._skipped_answers(),
            translate("CADAgent", "skipped"),
            "error",
        )

    def _finish(self, answers, status_text: str, dot_state: str) -> None:
        self._decided = True
        for _q, buttons in self._groups:
            for b in buttons:
                b.setEnabled(False)
        self._submit_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._status.setText(status_text)
        self._dot.set_state(dot_state)
        if self._future is not None and not self._future.done():
            self._future.set_result(answers)
