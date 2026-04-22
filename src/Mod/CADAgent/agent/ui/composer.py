# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rounded input composer for the ChatPanel: text area, pill buttons, send/stop."""

from __future__ import annotations

import FreeCAD as App

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets

translate = App.Qt.translate


class _Composer(QtWidgets.QFrame):
    """Rounded input area with icon buttons and a circular send button."""

    sendRequested = QtCore.Signal()
    stopRequested = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("ComposerFrame")
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(12, 10, 8, 8)
        v.setSpacing(6)

        self.input = QtWidgets.QPlainTextEdit()
        self.input.setObjectName("ComposerInput")
        self.input.setPlaceholderText(
            translate("CADAgent", "Ask the CAD agent…")
        )
        self.input.setFixedHeight(40)
        self.input.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.input.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.input.installEventFilter(self)
        v.addWidget(self.input)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        plus = QtWidgets.QPushButton("+")
        plus.setProperty("role", "pill")
        plus.setFixedSize(22, 22)
        plus.setToolTip(translate("CADAgent", "Attach (coming soon)"))
        plus.setCursor(QtCore.Qt.PointingHandCursor)

        slash = QtWidgets.QPushButton("\u2215")
        slash.setProperty("role", "pill")
        slash.setFixedSize(22, 22)
        slash.setToolTip(translate("CADAgent", "Commands (coming soon)"))
        slash.setCursor(QtCore.Qt.PointingHandCursor)

        self.permission_chip = QtWidgets.QLabel(
            translate("CADAgent", "\u26E8  Bypass permissions")
        )
        self.permission_chip.setProperty("role", "perm")
        self.permission_chip.hide()

        self.send_btn = QtWidgets.QPushButton("\u2191")
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setFixedSize(24, 24)
        self.send_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.send_btn.setToolTip(translate("CADAgent", "Send  (Ctrl+Enter)"))

        self.stop_btn = QtWidgets.QPushButton("\u25A0")
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setFixedSize(24, 24)
        self.stop_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.stop_btn.setToolTip(translate("CADAgent", "Stop"))
        self.stop_btn.hide()

        row.addWidget(plus)
        row.addWidget(slash)
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
