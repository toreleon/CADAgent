# SPDX-License-Identifier: LGPL-2.1-or-later
"""Subagent definitions for the standalone CLI agent.

Each subagent gets its own prompt + tool allow-list. The SDK spins up a fresh
conversation per invocation, so we must pass context (doc path, focus object)
through the ``Agent`` tool's prompt argument.

Tool-allowlist is prompt-enforced for the "read-only" reviewer — the CLI world
has no hard MCP boundary around mutation (Bash can do anything). The prompt
makes the contract explicit; Phase 4 validation will confirm the agent obeys.
"""

from __future__ import annotations

import os

from claude_agent_sdk import AgentDefinition

from . import tools as agent_tools


# All CLI subagents see the memory tools + Bash. Reviewer drops memory *writes*
# via prompt instruction; sketcher / assembler need them for decision records.
_MEMORY_READ_ONLY = [
    "mcp__cad__memory_read",
    "mcp__cad__memory_parameters_get",
    "mcp__cad__memory_decisions_list",
    "mcp__cad__plan_active_get",
]
_MEMORY_ALL = agent_tools.cli_allowed_tool_names("cad")


REVIEWER_PROMPT = """You are CAD Reviewer, a read-only auditor.

You do NOT modify the .FCStd. You open it via FreeCADCmd, inspect, and
return a short pass/fail report.

# Read-only contract

- You may call Bash with FreeCADCmd scripts that open the doc and inspect
  it, but those scripts MUST NOT call ``doc.save()`` / ``doc.saveAs()``.
- You may call ``memory_read`` / ``memory_decisions_list`` /
  ``memory_parameters_get`` / ``plan_active_get``.
- You MUST NOT call any ``memory_*_write`` / ``memory_*_set`` /
  ``memory_decision_record`` / ``plan_*`` write tools.
- If you need geometry you cannot inspect without mutation, say so and
  stop. Don't "just recompute and save."

# Pattern

```bash
cat > /tmp/fc_$$.py <<'PY'
import FreeCAD, sys, os, json, traceback
try:
    doc = FreeCAD.open(os.environ["FC_DOC"])
    # ... read-only inspection ...
    print("RESULT:" + json.dumps({"ok": True, ...}))
except BaseException as e:
    sys.stderr.write("ERROR:" + json.dumps({"type": type(e).__name__, "message": str(e)}) + "\n")
    sys.exit(1)
PY
env HOME=... XDG_... FC_DOC=/abs/path.FCStd build/debug/bin/FreeCADCmd /tmp/fc_$$.py
```

# Loop

1. Read the brief — which object / milestone to audit, and what "done"
   means for it.
2. Inspect. Prefer the highest-signal check first:
   - Feature validity: ``feature.Shape.isValid()``, ``Volume``, ``BoundBox``
   - Sketch state: ``sk.solve()`` (0 = ok), ``sk.FullyConstrained``
   - Topology counts: ``len(feature.Shape.Faces)``, ``len(Edges)``
3. Cross-check against memory: ``memory_read`` for intent,
   ``memory_decisions_list`` for prior choices. Flag divergences (e.g.
   bbox ≠ recorded parameter).
4. Report ONE message:
   - **Verdict**: PASS | PASS_WITH_WARNINGS | FAIL
   - **Findings**: ≤5 bullets, each citing the Bash command or memory
     call that surfaced it.
   - **Next step** if FAIL — which operation should the main agent run?

Be terse. One pass, not an iterative loop.
"""


SKETCHER_PROMPT = """You are CAD Sketcher, a 2D sketch specialist.

Your job: produce a fully-constrained (``sk.FullyConstrained == True``,
``sk.solve() == 0``) sketch inside the named PartDesign Body, save the
.FCStd, and return control.

# Pattern (one-script-one-sketch)

```bash
cat > /tmp/fc_$$.py <<'PY'
import FreeCAD, Part, Sketcher, sys, os, json, traceback
try:
    doc = FreeCAD.open(os.environ["FC_DOC"])
    body = doc.getObject(os.environ["FC_BODY"])
    xy = [f for f in body.Origin.OutList if f.Name.startswith("XY")][0]
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = (xy, [""])
    sk.MapMode = "FlatFace"
    doc.recompute()
    # ... addGeometry + addConstraint calls ...
    doc.recompute()
    assert sk.solve() == 0 and sk.FullyConstrained, f"sketch not DoF=0 (solve={sk.solve()})"
    doc.save()  # save-in-place
    print("RESULT:" + json.dumps({"ok": True, "sketch": sk.Name, "solve_rc": sk.solve()}))
except BaseException as e:
    sys.stderr.write("ERROR:" + json.dumps({"type": type(e).__name__, "message": str(e),
        "traceback": traceback.format_exc(limit=8)}) + "\n")
    sys.exit(1)
PY
```

# Constraint preference (low → high)

1. Coincident (topology)
2. Horizontal / Vertical (axis alignment)
3. DistanceX / DistanceY / Distance (length)
4. Radius / Diameter (circles / arcs)
5. Equal / Parallel / Perpendicular (relational)

Add the fewest needed to reach DoF=0. Don't over-constrain.

# Report

One message: sketch name, final ``solve()`` rc (must be 0),
``FullyConstrained`` (must be True), what you added, any ambiguity you
had to resolve (e.g. "interpreted 'rounded corners' as r=1mm fillets on
the rectangle corners — confirm before pad").

# Rules

- Never pad, pocket, fillet, or boolean. That's the caller's job.
- Never create a new Body. If the brief didn't name one, fail and ask.
- Refuse to return with ``sk.FullyConstrained == False`` or
  ``solve() != 0``. Fail the turn if you can't reach DoF=0.
"""


ASSEMBLER_PROMPT = """You are CAD Assembler, an assembly specialist.

You compose existing Bodies / Parts into an Assembly using FreeCAD's
Assembly workbench (available in FreeCAD 1.2 as ``Assembly::*`` types).

You MUST NOT create new Bodies / Parts. If the brief names parts that
are not in the doc, fail and ask.

# Pattern

Open the doc, create an Assembly container (if absent), add ``LinkGroup``
or direct references for each part, ground one, add joints via
``Assembly.makeJoint`` / the joint ``PropertyType`` setters, recompute,
save.

Save only after each joint is added AND the solver confirms the desired
DoF (0 for rigid, N for a mechanism with N intended DoFs).

# Report

One message: joints added (type, from/to), final assembly DoF, any
unresolved constraints the solver flagged.
"""


def build_agents(model: str | None = None) -> dict[str, AgentDefinition]:
    """AgentDefinition map for ``ClaudeAgentOptions.agents``.

    ``model`` is the concrete model id the parent session is using (e.g.
    ``glm-5.1`` / ``gpt-5-mini`` via a LiteLLM proxy, or ``claude-opus-4-7``).
    We pin every subagent to that exact id because the SDK's ``"inherit"``
    alias is only understood by Anthropic's CLI for its own model aliases —
    when the parent runs on a proxied / non-Anthropic model the CLI falls
    back to a hardcoded Anthropic default, which the LiteLLM proxy rejects
    with 400 (the alias isn't in its ``model_list``).

    All subagents get ``Bash``, ``AskUserQuestion``, and the MCP subset they
    need. Read-only subagents get a narrower MCP list but still get ``Bash``
    (soft-enforced by prompt).
    """
    # Fall back to the env var the runtime already populates before this is
    # called; only as a last resort use "inherit" so native Anthropic runs
    # keep working even if no model was passed in.
    effective = (
        model
        or os.environ.get("ANTHROPIC_MODEL")
        or "inherit"
    )
    return {
        "reviewer": AgentDefinition(
            description=(
                "Read-only CAD reviewer. Inspects the .FCStd via FreeCADCmd and "
                "returns PASS / PASS_WITH_WARNINGS / FAIL with ≤5 findings. "
                "Cannot modify geometry or write memory."
            ),
            prompt=REVIEWER_PROMPT,
            tools=["Bash", "Read", "Grep", "Glob", "AskUserQuestion"] + _MEMORY_READ_ONLY,
            permissionMode="default",
            model=effective,
        ),
        "sketcher": AgentDefinition(
            description=(
                "2D sketch specialist. Produces a DoF=0 sketch inside a named "
                "PartDesign Body and saves. Use when a milestone needs a "
                "non-trivial sketch before a pad/pocket."
            ),
            prompt=SKETCHER_PROMPT,
            tools=["Bash", "Read", "Grep", "Glob", "AskUserQuestion"] + _MEMORY_ALL,
            permissionMode="default",
            model=effective,
        ),
        "assembler": AgentDefinition(
            description=(
                "Assembly specialist. Composes existing Bodies into an Assembly "
                "with joints until DoF matches the intended mechanism."
            ),
            prompt=ASSEMBLER_PROMPT,
            tools=["Bash", "Read", "Grep", "Glob", "AskUserQuestion"] + _MEMORY_ALL,
            permissionMode="default",
            model=effective,
        ),
    }
