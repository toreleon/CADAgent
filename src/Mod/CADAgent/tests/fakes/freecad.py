"""In-memory fake of the `FreeCAD` module for headless tests.

Only the surface used by `agent/` is implemented:
- `App.getUserAppDataDir()` -> a tmp dir
- `App.ParamGet(path)` -> a fake parameter group
- `App.ActiveDocument` / `App.listDocuments()` / open/new/close/setActive
- `App.Console.PrintMessage/PrintWarning/PrintError`
"""
from __future__ import annotations

import os
import tempfile
from typing import Any


class FakeParamGroup:
    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._bools: dict[str, bool] = {}
        self._ints: dict[str, int] = {}
        self._floats: dict[str, float] = {}

    def GetString(self, key: str, default: str = "") -> str:
        return self._strings.get(key, default)

    def SetString(self, key: str, value: str) -> None:
        self._strings[key] = value

    def GetBool(self, key: str, default: bool = False) -> bool:
        return self._bools.get(key, default)

    def SetBool(self, key: str, value: bool) -> None:
        self._bools[key] = value

    def GetInt(self, key: str, default: int = 0) -> int:
        return self._ints.get(key, default)

    def SetInt(self, key: str, value: int) -> None:
        self._ints[key] = value

    def GetFloat(self, key: str, default: float = 0.0) -> float:
        return self._floats.get(key, default)

    def SetFloat(self, key: str, value: float) -> None:
        self._floats[key] = value

    def RemString(self, key: str) -> None:
        self._strings.pop(key, None)


class FakeConsole:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def PrintMessage(self, msg: str) -> None:
        self.messages.append(("info", msg))

    def PrintWarning(self, msg: str) -> None:
        self.messages.append(("warn", msg))

    def PrintError(self, msg: str) -> None:
        self.messages.append(("err", msg))

    def PrintLog(self, msg: str) -> None:
        self.messages.append(("log", msg))


class FakeDocument:
    def __init__(self, name: str, label: str | None = None, file_name: str = "") -> None:
        self.Name = name
        self.Label = label or name
        self.FileName = file_name
        self.Objects: list[Any] = []

    def save(self) -> None:
        if self.FileName:
            with open(self.FileName, "wb") as f:
                f.write(b"FAKE_FCSTD\x00" + self.Name.encode("utf-8"))


class _AppNamespace:
    """Mimics the global `FreeCAD` module namespace."""

    def __init__(self) -> None:
        self._user_data_dir = tempfile.mkdtemp(prefix="cadagent-fake-home-")
        self._params: dict[str, FakeParamGroup] = {}
        self._documents: dict[str, FakeDocument] = {}
        self._active_name: str | None = None
        self.Console = FakeConsole()

    # --- paths ---
    def getUserAppDataDir(self) -> str:
        return self._user_data_dir

    # --- parameters ---
    def ParamGet(self, path: str) -> FakeParamGroup:
        return self._params.setdefault(path, FakeParamGroup())

    # --- documents ---
    @property
    def ActiveDocument(self) -> FakeDocument | None:
        if self._active_name is None:
            return None
        return self._documents.get(self._active_name)

    def listDocuments(self) -> dict[str, FakeDocument]:
        return dict(self._documents)

    def newDocument(self, label: str = "Unnamed") -> FakeDocument:
        idx = len(self._documents)
        name = f"Doc{idx}"
        while name in self._documents:
            idx += 1
            name = f"Doc{idx}"
        doc = FakeDocument(name=name, label=label)
        self._documents[name] = doc
        self._active_name = name
        return doc

    def openDocument(self, path: str) -> FakeDocument:
        base = os.path.splitext(os.path.basename(path))[0] or "Opened"
        name = base
        i = 1
        while name in self._documents:
            i += 1
            name = f"{base}{i}"
        doc = FakeDocument(name=name, label=base, file_name=path)
        self._documents[name] = doc
        self._active_name = name
        return doc

    def closeDocument(self, name: str) -> None:
        self._documents.pop(name, None)
        if self._active_name == name:
            self._active_name = next(iter(self._documents), None)

    def setActiveDocument(self, name: str) -> None:
        if name in self._documents:
            self._active_name = name


def install() -> _AppNamespace:
    """Install fake `FreeCAD` and `FreeCADGui` modules into sys.modules.

    Returns the namespace so tests can mutate it (add docs, set params, etc.).
    Idempotent: returns the existing namespace if already installed.
    """
    import sys
    import types

    existing = sys.modules.get("FreeCAD")
    if isinstance(existing, _AppNamespace):
        return existing

    app = _AppNamespace()
    # Expose as a module-like object (FreeCAD is imported as `App`).
    mod = types.ModuleType("FreeCAD")
    for attr in (
        "getUserAppDataDir",
        "ParamGet",
        "listDocuments",
        "newDocument",
        "openDocument",
        "closeDocument",
        "setActiveDocument",
        "Console",
    ):
        setattr(mod, attr, getattr(app, attr))
    # ActiveDocument is a property; expose as a descriptor via module __getattr__.
    mod.__dict__["_app"] = app

    def __getattr__(name: str) -> Any:
        if name == "ActiveDocument":
            return app.ActiveDocument
        raise AttributeError(name)

    mod.__getattr__ = __getattr__  # type: ignore[attr-defined]
    sys.modules["FreeCAD"] = mod

    # Minimal FreeCADGui shim — agent code rarely imports it directly, but
    # safe to provide so `import FreeCADGui` doesn't ImportError.
    gui = types.ModuleType("FreeCADGui")
    gui.ActiveDocument = None
    sys.modules["FreeCADGui"] = gui

    return app
