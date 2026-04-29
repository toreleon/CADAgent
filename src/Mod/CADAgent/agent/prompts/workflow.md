# How to work through a task

The goal is the **coding-agent loop**: parameters first, todo list,
work-and-verify each item, integrate, final verify.

0. **Read the drawing (only if an image is attached).** Treat the image
   as the spec; do not start building until you have echoed back what
   you read. Output a single block before anything else:

   ```
   SPEC FROM DRAWING
   - units: mm | in
   - views: front / top / right / iso (whichever are present)
   - envelope: W × D × H  (sources: top→W,D · side→H)
   - features: <one bullet per labelled feature; for every numeric
     you copy, append `(view: top|side|iso, label: "<exact text>")`
     so the source is traceable>
   - datums / origin: <where 0,0,0 sits relative to the part>
   - illegible / inferred: <list anything you guessed at and why>
   ```

   **Provenance rule — every numeric in this block must cite a view
   AND the exact label text it came from**, e.g.
   ``boss_height = 2.00 in (view: side, label: "2.00")``.
   If you cannot point to which arrow on which view a number comes
   from, the number is inferred — list it under "illegible /
   inferred" with your guess and reasoning, do not promote it to a
   feature line. This is what separates *reading* the drawing from
   *guessing at* it.

   Side-view numerics in particular: the section view of a stepped
   part typically shows (a) the overall stack-up height (often the
   tallest dim, e.g. ``2.00`` for a boss above a flange), (b) per-step
   thicknesses (small dims like ``0.06``, ``0.09``, ``0.31``), and
   (c) optional radial dims that overlap from the top view. Match
   each numeric to its arrow before deciding what it represents —
   ``0.31`` next to a small step is a recess depth, not the boss
   height.

   **Required tool calls in this stage — in this order, no exceptions:**

   1. ``memory_note_write(doc, "design_intent", "spec_from_drawing",
      <full SPEC block>)`` — the source of truth.
   2. ``memory_note_write(doc, "open_questions", "spec_ambiguities",
      <bullet list>)`` — **mandatory whenever the SPEC has any
      "illegible / inferred" entries.** One bullet per ambiguity, in
      the form ``<param_name> → guessed <value> → <why this guess>``.
      If you skip this call, the user has no record of what you
      assumed. Skipping it is a defect, not a shortcut. If — and only
      if — every dimension on the drawing was unambiguous, write
      ``memory_note_write(doc, "open_questions", "spec_ambiguities",
      "none")`` to make the absence explicit.
   3. ``memory_parameter_set(...)`` per numeric in the SPEC (this
      continues into step 1 of the loop). For each parameter that
      came from an inferred dim, pass ``note="inferred from drawing
      — best guess"``.

   **Handling unreadable dimensions depends on the mode:**

   - ``bypassPermissions`` (the autonomous CLI default) — **never
     stop to ask.** The user is not at the keyboard. Pick a
     defensible best-guess for each unreadable dim, run the three
     tool calls above, build, and surface every guess in the final
     summary so the user can correct in the next turn.
   - ``default`` / ``acceptEdits`` — call ``AskUserQuestion`` once,
     batching every ambiguous dim into one multi-option question, before
     ``memory_parameter_set``. Still write ``open_questions/spec_ambiguities``
     so the answers have a place to land.
   - Photographic / hand-sketched inputs with no numbers at all: in
     bypass mode, build a placeholder bounding-box stand-in at a
     documented scale and record every dim in ``spec_ambiguities``;
     in interactive modes, ask for at least the envelope and primary
     feature dims first.

   **Prose questions with no tool call are never a valid stopping
   state** — either AskUserQuestion (when allowed) or persist + proceed.

1. **Parameters.** Pull every dimension out of the prompt (and any
   attached drawing) into ``memory_parameter_set`` — one call per
   named dim (``D_envelope=250``, ``h_total=70``, ``R_dome=250``,
   ``count_slots=12``, etc.). Magic numbers in scripts are a smell;
   read parameters back via ``memory_parameters_get`` at the top of
   every script.

   **Pass ``verify`` on every parameter you can.** ``verify`` is an
   inspect-DSL query string. The auto-probe runs every parameter's
   ``verify`` after every Bash mutation and surfaces the result. Hooking
   acceptance to parameters is how you avoid silent build failures.
   Examples:
   - ``memory_parameter_set(name="bbox_z", value=70, verify="bbox of Cruciform")``
     → probe each turn surfaces ``bbox_z `bbox of Cruciform` size=[X,Y,Z]``.
     **Always scope verify queries to your final feature's name** (``of NAME``)
     — otherwise scratch / intermediate geometry pollutes the answer.
   - ``memory_parameter_set(name="count_slots", value=12, verify="slots width=8 length=15")``
     → if you build slots and the count comes back wrong, you see it
     before declaring done.
   - ``memory_parameter_set(name="dome_r", value=250, verify="spheres radius=250")``
     → confirms the dome face exists at the expected radius.

2. **Decompose.** For any part with more than ~3 distinct features,
   emit a ``TodoWrite`` list with one todo per feature ("hub", "arms",
   "dome envelope", "central hole", "satellite bosses", "slot pattern",
   "outer fillets", …). 4–10 todos is the sweet spot. Each todo's
   content describes the *intent*, not the operations.

3. **Build.** Work the todo list **one item at a time**. For each:
   a. Mark it ``in_progress``.
   b. Write one Bash script that builds a ``Part::Feature`` named after
      the todo (e.g. ``Part::Feature("dome_envelope")``). Read parameters
      via the memory sidecar; assert ``isValid()``; ``saveAs(out)``.
   c. The auto-probe fires automatically. Read it.
   d. If the probe looks right, call richer ``inspect(...)`` queries to
      confirm the *specific* feature you just built (e.g. after dome:
      ``inspect(doc, "spheres radius=250")``). Then mark the todo done.
   e. If the probe shows the feature didn't materialize as expected,
      **revise**: write a corrective Bash and rerun. Cap at **two**
      retries per todo. On a third failure, mark the todo failed-with-note
      and continue — surface the failure in the final report.

4. **Integrate.** Once features exist as named ``Part::Feature``s,
   compose them with one Bash that runs the booleans in dependency
   order (e.g. ``body = Common(arms_extruded, dome_envelope)``). The
   auto-probe fires.

5. **Final verify.** Call ``inspect(doc, "solids")``,
   ``inspect(doc, "face_types")``, and one targeted query per
   ``count_*`` parameter (e.g. ``count_slots=12`` →
   ``inspect(doc, "slots width=8 length=20")``). Only declare success
   when each parameter's expectation is met. If anything is red,
   say so honestly in the summary.

6. **Completeness gate.** Call ``verify_spec(doc)`` before declaring
   done. It walks every parameter with a ``verify`` query, runs each
   against the live doc (inch→mm conversion automatic), and returns
   a structured PASS/FAIL table. **The harness also runs this same
   gate at Stop** — if any row fails, your stop is blocked and you
   get another turn with the failed rows attached. So: call it
   yourself first, fix any FAIL by emitting a rebuild Bash (with
   ``doc.removeObject`` cleanup of the prior attempt's named
   features), then declare done. Cap: 3 stop-blocks per session;
   beyond that the harness lets the stop through with the FAILs
   persisted to ``open_questions.completeness_gate``.

   The gate only checks parameters that have a ``verify`` query —
   so step 1's discipline (one ``memory_parameter_set`` per
   spec_from_drawing feature, each with ``verify=…``) is what makes
   the gate strong. A drawing feature without a parameter is
   un-gated and may silently disappear; do not skip the
   parameter set step.

   The harness also runs a **coverage check**: it scans
   ``spec_from_drawing`` for "N×" / "N places" patterns (e.g. the
   drawing's ``12×Ø0.14``, ``4×R0.50``, ``32×R0.09``) and fails the
   gate for every count that has no matching ``count_*=N`` parameter.
   So whenever the spec lists a feature count, set a
   ``count_<thing>=N`` parameter with a ``verify`` that the
   geometry can satisfy — e.g.
   ``memory_parameter_set(name="count_mounting_holes", value=12,
   verify="holes diameter=3.556 axis=z")``. Otherwise the gate will
   block your stop on a coverage row even if every other verify
   passes.

7. **Summarize.** One short paragraph + the table from
   ``verify_spec``: what you built, the FAIL rows still outstanding
   (if any — call them out by name, not as "simplified"), and
   where it saved.

