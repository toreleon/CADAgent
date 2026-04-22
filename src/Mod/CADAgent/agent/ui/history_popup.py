# SPDX-License-Identifier: LGPL-2.1-or-later
"""Claude Code-style history popover: search + list with relative timestamps."""

from __future__ import annotations

import datetime

import FreeCAD as App

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets


translate = App.Qt.translate


def _relative_time(iso: str) -> str:
    if not iso:
        return ""
    try:
        ts = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return iso[:16]
    delta = datetime.datetime.now() - ts
    secs = int(delta.total_seconds())
    if secs < 45:
        return translate("CADAgent", "now")
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    if secs < 7 * 86400:
        return f"{secs // 86400}d"
    if secs < 30 * 86400:
        return f"{secs // (7 * 86400)}w"
    return ts.strftime("%Y-%m-%d")


class _HistoryRow(QtWidgets.QWidget):
    """One session row: title + relative time, hover-reveal delete button."""

    activated = QtCore.Signal(str)
    deleteRequested = QtCore.Signal(str)

    def __init__(self, session_id: str, title: str, updated_at: str, is_active: bool):
        super().__init__()
        self._sid = session_id
        self.setProperty(
            "role", "history_row_active" if is_active else "history_row"
        )
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 6, 5)
        lay.setSpacing(6)

        self._title_lbl = QtWidgets.QLabel(title or session_id[:8])
        self._title_lbl.setProperty("role", "history_title")
        self._title_lbl.setTextFormat(QtCore.Qt.PlainText)
        self._title_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        # Elide via fixed width handled by parent; rely on clipping.
        lay.addWidget(self._title_lbl, 1)

        self._time_lbl = QtWidgets.QLabel(_relative_time(updated_at))
        self._time_lbl.setProperty("role", "history_time")
        lay.addWidget(self._time_lbl, 0, QtCore.Qt.AlignRight)

        self._del_btn = QtWidgets.QToolButton()
        self._del_btn.setText("\u2715")  # ✕
        self._del_btn.setProperty("role", "row_action")
        self._del_btn.setToolTip(translate("CADAgent", "Delete"))
        self._del_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._del_btn.clicked.connect(self._on_delete)
        self._del_btn.hide()
        lay.addWidget(self._del_btn, 0, QtCore.Qt.AlignRight)

    def _on_delete(self):
        self.deleteRequested.emit(self._sid)

    def enterEvent(self, event):
        self._time_lbl.hide()
        self._del_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._del_btn.hide()
        self._time_lbl.show()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            # Ignore clicks that hit the delete button (it handles its own).
            child = self.childAt(event.pos())
            if child is not self._del_btn:
                self.activated.emit(self._sid)
        super().mouseReleaseEvent(event)


class HistoryPopup(QtWidgets.QFrame):
    """Borderless popup anchored below an anchor widget."""

    sessionActivated = QtCore.Signal(str)
    sessionDeleted = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HistoryPopup")
        self.setWindowFlags(
            QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint
        )
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        self._entries: list[dict] = []
        self._active_id: str | None = None

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        self._search = QtWidgets.QLineEdit()
        self._search.setObjectName("HistorySearch")
        self._search.setPlaceholderText(translate("CADAgent", "Search sessions…"))
        self._search.textChanged.connect(self._rebuild)
        v.addWidget(self._search)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._list_host = QtWidgets.QWidget()
        self._list_lay = QtWidgets.QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(2)
        self._list_lay.setAlignment(QtCore.Qt.AlignTop)
        self._scroll.setWidget(self._list_host)
        v.addWidget(self._scroll, 1)

        self.setFixedWidth(320)
        self.setMinimumHeight(80)
        self.setMaximumHeight(420)

    def set_entries(self, entries: list[dict], active_id: str | None) -> None:
        self._entries = list(entries)
        self._active_id = active_id
        self._search.clear()
        self._rebuild()

    def _rebuild(self) -> None:
        query = (self._search.text() or "").strip().lower()
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        matched = 0
        for entry in self._entries:
            title = (entry.get("title") or "").strip()
            if query and query not in title.lower():
                continue
            sid = entry.get("id") or ""
            row = _HistoryRow(
                sid,
                title or sid[:8],
                entry.get("updated_at") or "",
                is_active=(sid == self._active_id),
            )
            row.activated.connect(self._on_row_activated)
            row.deleteRequested.connect(self._on_row_delete)
            self._list_lay.addWidget(row)
            matched += 1
        if matched == 0:
            empty = QtWidgets.QLabel(
                translate("CADAgent", "No sessions yet")
                if not self._entries
                else translate("CADAgent", "No matches")
            )
            empty.setProperty("role", "history_empty")
            empty.setAlignment(QtCore.Qt.AlignCenter)
            self._list_lay.addWidget(empty)

    def _on_row_activated(self, sid: str) -> None:
        self.sessionActivated.emit(sid)
        self.close()

    def _on_row_delete(self, sid: str) -> None:
        self.sessionDeleted.emit(sid)
        # Remove locally and rebuild so the popup stays open.
        self._entries = [e for e in self._entries if e.get("id") != sid]
        if self._active_id == sid:
            self._active_id = None
        self._rebuild()

    def popup_below(self, anchor: QtWidgets.QWidget) -> None:
        pt = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height() + 4))
        screen = QtWidgets.QApplication.screenAt(pt) or QtWidgets.QApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = min(pt.x(), avail.right() - self.width() - 8)
        x = max(x, avail.left() + 8)
        y = min(pt.y(), avail.bottom() - self.height() - 8)
        self.move(x, y)
        self.show()
        self._search.setFocus()
