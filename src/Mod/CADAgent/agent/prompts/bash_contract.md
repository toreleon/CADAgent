# The invocation rule (non-negotiable)

Use script files. **Never** ``FreeCADCmd -c "..."`` and **never** pass
script parameters as argv (FreeCADCmd interprets extra argv as files to
open, not as ``sys.argv``). Parameters travel via environment variables.

## Canonical one-shot (copy this, fill in the middle)

```bash
cat > /tmp/fc_$$.py <<'PY'
import sys, os, json, traceback
try:
    import FreeCAD
    # ---- your FreeCAD code here ----
    # Read inputs from os.environ; write results as RESULT: lines.
    print("RESULT:" + json.dumps({"ok": True}))
except BaseException as e:
    sys.stderr.write("ERROR:" + json.dumps({
        "type": type(e).__name__, "message": str(e),
        "traceback": traceback.format_exc(limit=8),
    }) + "\n")
    sys.stderr.flush()
    sys.exit(1)
PY

env HOME="$PWD/.fc-home" \
    XDG_DATA_HOME="$PWD/.fc-home/.local/share" \
    XDG_CONFIG_HOME="$PWD/.fc-home/.config" \
    FC_DOC="/abs/path/to/part.FCStd" \
    "$CADAGENT_FREECADCMD" /tmp/fc_$$.py
```

**Always use ``$CADAGENT_FREECADCMD``** (an env var the wrapper sets) — *never*
``build/debug/bin/FreeCADCmd`` or any other relative path. Worktrees and
non-default checkouts don't have a ``build/`` next to ``$PWD``; the wrapper
walks parent directories to find a working FreeCADCmd and exports the
absolute path so your scripts run from anywhere. ``$CADAGENT_DOC`` likewise
holds the absolute target ``.FCStd`` path you should save to.

**Env vars are for Bash only.** When you call MCP tools (``inspect``,
``memory_*``, etc.) the ``doc`` argument must be the **literal absolute
path** — never ``$CADAGENT_DOC`` or any other shell variable. MCP tool
args go straight to a Python function; nothing expands them. Resolve the
path once (you can ``echo "$CADAGENT_DOC"`` in a Bash call to read it)
then paste the literal value into subsequent MCP calls.
