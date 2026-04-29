# Hard limits — these prevent runaway cost

- **Max 2 retries per todo.** If a feature script fails its verify check
  twice in a row, mark the todo failed-with-note and continue to the next.
  Do not loop further on the same feature.
- **No full rebuilds.** When a feature is wrong, fix that feature only.
  Do not delete the document and start over — every rebuild accumulates
  geometry rather than replacing it (the auto-probe will show bbox or
  face_types growing in the wrong direction).
- **No ``AskUserQuestion`` in autonomous mode.** When ``CADAGENT_PERMS``
  is ``bypassPermissions`` (the default for this CLI), the user isn't at
  the keyboard. Make a defensible choice and surface the assumption in
  your final summary instead.

