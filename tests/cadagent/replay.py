"""Test-side helpers: spawn FreeCADCmd + _driver.py, parse the JSON report."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
DRIVER = HERE / "_driver.py"


@dataclass
class Trace:
    prompt: str
    elapsed_s: float
    timed_out: bool
    trace: list[dict]
    errors: list[str]
    topology: dict | None = None
    doc_in: str | None = None
    doc_out: str | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    def tool_names(self) -> list[str]:
        """Ordered list of every mcp__cad__* tool the agent called."""
        return [e["name"] for e in self.trace if e.get("kind") == "tool_use"]

    def successful_tool_names(self) -> list[str]:
        """Tools whose result came back without is_error=True."""
        errored_ids: set = set()
        for e in self.trace:
            if e.get("kind") == "tool_result" and e.get("is_error"):
                errored_ids.add(e.get("id"))
        return [
            e["name"]
            for e in self.trace
            if e.get("kind") == "tool_use" and e.get("id") not in errored_ids
        ]

    @property
    def shape_objects(self) -> list[dict]:
        if not self.topology:
            return []
        return [o for o in self.topology.get("objects", []) if "bbox" in o]


def _freecadcmd() -> str:
    env_override = os.environ.get("FREECADCMD")
    if env_override:
        return env_override
    candidate = REPO_ROOT / "build" / "debug" / "bin" / "FreeCADCmd"
    if not candidate.exists():
        raise RuntimeError(
            f"FreeCADCmd not found at {candidate}. Build first "
            f"(pixi run build-debug) or set $FREECADCMD."
        )
    return str(candidate)


def _redirected_home(tmpdir: Path) -> dict[str, str]:
    """Match CLAUDE.md: HOME + XDG_* under a scratch dir so FreeCAD can write."""
    home = tmpdir / ".fc-home"
    (home / ".local" / "share").mkdir(parents=True, exist_ok=True)
    (home / ".config").mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }


def run_agent(
    prompt: str,
    *,
    tmpdir: Path,
    doc: Path | None = None,
    save_as: Path | None = None,
    timeout_s: float = 180.0,
    extra_env: dict[str, str] | None = None,
) -> Trace:
    """Spawn FreeCADCmd, run the driver on ``prompt``, return a parsed Trace.

    ``tmpdir`` must be a writable test-scoped dir (use pytest's ``tmp_path``).
    Credentials must be in the ambient env (ANTHROPIC_API_KEY / _BASE_URL /
    _MODEL) — the redirected FreeCAD home starts with an empty param store.
    """
    out_path = tmpdir / "trace.json"
    env = os.environ.copy()
    env.update(_redirected_home(tmpdir))
    env["CADAGENT_TEST_PROMPT"] = prompt
    env["CADAGENT_TEST_OUT"] = str(out_path)
    env["CADAGENT_TEST_TIMEOUT"] = str(timeout_s)
    if doc is not None:
        env["CADAGENT_TEST_DOC"] = str(doc)
    if save_as is not None:
        env["CADAGENT_TEST_SAVE_AS"] = str(save_as)
    if extra_env:
        env.update(extra_env)

    cmd = [
        _freecadcmd(),
        "-c",
        f"exec(open({str(DRIVER)!r}).read())",
    ]
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s + 60,  # outer hard kill
        check=False,
    )

    payload: dict = {}
    if out_path.exists():
        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

    return Trace(
        prompt=payload.get("prompt", prompt),
        elapsed_s=float(payload.get("elapsed_s", 0.0)),
        timed_out=bool(payload.get("timed_out", False)),
        trace=list(payload.get("trace", [])),
        errors=list(payload.get("errors", [])),
        topology=payload.get("topology"),
        doc_in=payload.get("doc_in"),
        doc_out=payload.get("doc_out"),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
    )
