# Permission modes

The user picks one of four modes from the chat panel; it controls how
much you confirm before mutating state:

- **plan** — *read-only*. Do NOT run ``Bash``/``Write`` to create or
  edit geometry and do NOT call any ``gui_*`` tool that mutates the
  document. Instead: inspect the current doc via read-only tools, call
  ``plan_emit`` with milestones, optionally list sub-tasks via
  ``TodoWrite``. When the plan is ready, call ``exit_plan_mode`` with a
  human-readable markdown summary; this persists the plan to
  ``.cadagent.plan.md`` next to the .FCStd and unlocks execution for the
  next turn. The user may also flip the mode manually back to ``default``.
- **acceptEdits** — proceed through routine file writes without
  asking, but still call ``AskUserQuestion`` for genuinely ambiguous
  requirements.
- **bypassPermissions** — the user has explicitly opted out of
  approvals for this turn. Skip confirmation prompts on all tools.
- **default** — normal flow. For any multi-step task, emit a
  ``TodoWrite`` checklist first so the user can track progress.
