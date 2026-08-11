### Task 6: Retry, Partial Failure, and Session-report Fallback

**Files:**
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `src/iiwi/interactive/render.py`
- Modify: `src/iiwi/errors.py`
- Create: `tests/unit/interactive/test_outcome_review_failures.py`

**Interfaces:**
- Consumes: `OutcomeSynthesisError`, `OutcomeSynthesisResult.failed_session_ids`, existing `_ErrorState`, and existing direct `actions.generate()` session-report path.
- Produces: recoverable error kinds `outcome-synthesis`, `outcome-preview`, and `outcome-write`, each with explicit retry/back/fallback behavior.

- [ ] **Step 1: Write failing failure-path tests**

Cover these scripts:

1. Synthesis raises once, user selects Retry, synthesis succeeds, and review opens.
2. Complete synthesis failure offers `Use session-based report`; selecting it calls existing `actions.generate()` and labels the result as fallback in the warning.
3. Partial synthesis result opens review with `Ungrouped candidates` and successful primary outcomes.
4. Preview raises once, `Back to Quick Review` restores inclusion, order, edits, user-added outcomes, Blockers, and Next week.
5. Preview Retry uses the same draft object and succeeds.
6. Write conflict still offers `Overwrite once`, but retries `generate_reviewed()` rather than session-based generation.

- [ ] **Step 2: Run failure tests and verify missing options**

Run: `uv run pytest tests/unit/interactive/test_outcome_review_failures.py -q`

Expected: FAIL because outcome-specific error options and retry targets do not exist.

- [ ] **Step 3: Implement explicit recoverable routes**

Store an error retry discriminator, not a closure, in `_ErrorState`. `_error_options()` must return:

- synthesis: `Retry`, `Use session-based report`, `Back`;
- preview: `Retry`, `Back to Quick Review`, `Main menu`;
- reviewed write conflict: `Overwrite once`, `Back to Quick Review`, `Main menu`;
- reviewed write failure: `Back to Quick Review`, `Main menu`.

Add transient `ReportDraft.generation_notice: str | None = None`. The session-based fallback sets it to `Outcome synthesis unavailable; generated the session-based report.`, calls the pre-existing `actions.generate(draft, filtered_scan, force)`, and clears it in `finally`. Thread the notice into `_build_report_service(..., initial_warnings=[notice] if notice else None)` so the warning is present in both the written file and preview/result content. It must never label the output as outcome-synthesized, and ordinary interactive/non-interactive generation leaves the notice unset.

All preview/write errors leave `state.outcome_review` untouched. A synthesis Retry reruns synthesis from the already filtered scan without rescanning. `Overwrite once` calls reviewed generation with `force=True`.

- [ ] **Step 4: Run failure and existing error tests**

Run: `uv run pytest tests/unit/interactive/test_outcome_review_failures.py tests/unit/interactive/test_interactive_regressions.py tests/unit/interactive/test_controller_generation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit degradation behavior**

```bash
git add src/iiwi/interactive/controller.py src/iiwi/interactive/render.py src/iiwi/errors.py tests/unit/interactive/test_outcome_review_failures.py
git commit -m "feat: add quick review recovery paths"
```

---
