# When to stop

- Sketch won't reach DoF=0 after three constraint passes: stop, show the
  user the current state, ask which dimension they want to fix.
- Pad/pocket yields invalid shape twice in a row: stop, surface the
  profile and the error, ask.
- The user rejects a mutation (if/when permission prompting is wired
  in): do NOT retry. Ask what they want instead.

