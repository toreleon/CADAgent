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
"""Marshal callables onto the Qt GUI thread and wait synchronously.

FreeCAD's document/feature API must be mutated on the GUI thread. Tools run on
the asyncio worker thread, so they use `run_sync(fn)` to hop over.

The helper uses a singleton QObject that lives on the main (GUI) thread. A
cross-thread `QMetaObject.invokeMethod(..., BlockingQueuedConnection)` would
dispatch the slot and wait for it, but that API is awkward to pass arbitrary
callables through in PySide. Instead we emit a signal with a callable + a
`concurrent.futures.Future`; a QueuedConnection delivers the signal to the GUI
thread, the slot runs the callable, and we block on the future from the
caller. Same net effect, simpler plumbing.
"""

from __future__ import annotations

import concurrent.futures
import threading

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets


_dispatcher = None
_dispatcher_lock = threading.Lock()


class _Dispatcher(QtCore.QObject):
    invoke = QtCore.Signal(object, object)  # callable, cf_future

    def __init__(self):
        super().__init__()
        self.invoke.connect(self._on_invoke, QtCore.Qt.QueuedConnection)

    def _on_invoke(self, fn, cf_future):
        if cf_future.cancelled():
            return
        try:
            result = fn()
            cf_future.set_result(result)
        except BaseException as exc:  # propagate to caller
            cf_future.set_exception(exc)


def on_gui_thread() -> bool:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return False
    return QtCore.QThread.currentThread() is app.thread()


def init_dispatcher() -> None:
    """Create the singleton dispatcher. Must be called from the GUI thread
    so the QObject's thread affinity is correct from the start.

    Idempotent: subsequent calls are no-ops.
    """
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is not None:
            return
        app = QtWidgets.QApplication.instance()
        if app is None:
            raise RuntimeError(
                "No QApplication; gui_thread.init_dispatcher requires Qt GUI."
            )
        if QtCore.QThread.currentThread() is not app.thread():
            raise RuntimeError(
                "init_dispatcher() must be called from the Qt GUI thread."
            )
        _dispatcher = _Dispatcher()


def run_sync(fn, timeout: float = 30.0):
    """Run `fn()` on the Qt GUI thread and block until it returns.

    Re-raises any exception raised by `fn`. If already on the GUI thread, runs
    inline to avoid deadlock. The dispatcher must have been initialised first
    via `init_dispatcher()` from the GUI thread.
    """
    if on_gui_thread():
        return fn()
    if _dispatcher is None:
        raise RuntimeError(
            "gui_thread dispatcher not initialised — call init_dispatcher() "
            "from the GUI thread before invoking run_sync() from a worker."
        )
    fut: concurrent.futures.Future = concurrent.futures.Future()
    _dispatcher.invoke.emit(fn, fut)
    return fut.result(timeout=timeout)
