# Task 6 Recovery Report — Retry, Partial Failure, and Session-report Fallback

## Scope inspected

Recovered commit: `2b9af4553e9f0bf8362449c86a87df641d6081fd` (`feat: add quick review recovery paths`)

Baseline parent: `35609dc` (`fix: constrain quick review hard breaks`)

The worktree is on `feat/evidence-first-quick-review`, clean after inspection.  `35609dc` is an ancestor of `HEAD`; `git diff --check` is clean for both the worktree and `35609dc..HEAD`.

## Requirements mapping

| Brief requirement | Implementation / evidence |
| --- | --- |
| Synthesis failure Retry reuses the filtered selection without a rescan | `controller._begin_outcome_review()` catches `OutcomeSynthesisError` and records retry discriminator `outcome-synthesis`; Retry calls it again against the existing `SelectionState`. `test_synthesis_retry_reuses_filtered_scan_and_opens_quick_review` asserts two attempts and one scan. |
| Complete failure supports the session-based fallback | `_error_options()` returns `Retry`, `Use session-based report`, `Back`; `_error_key()` temporarily sets the exact notice, calls existing `_generate(..., force=False)`, and clears it in `finally`. `test_complete_synthesis_failure_can_generate_labeled_session_fallback` verifies the route and reset. |
| Fallback warning reaches output and ordinary drafts are unmarked | `ReportDraft.generation_notice` is transient and defaults to `None`; `cli_actions._generate()` passes `[notice]` to `_build_report_service(initial_warnings=...)` only when set; `cli._build_report_service()` forwards the warnings to `ReportService`. `test_session_generation_threads_only_an_explicit_fallback_notice` verifies this boundary. `ReportService.generate()` incorporates initial warnings into rendered content and written reports. |
| Partial synthesis opens the editable review with ungrouped candidates | The pre-existing synthesis result's outcomes (including `UNGROUPED` extraction failures) are passed through `cli_actions._synthesize()` into `OutcomeReviewDraft`; the existing review renderer/controller preserves that bucket. `test_partial_synthesis_opens_review_with_primary_and_ungrouped_candidates` verifies primary and `Ungrouped candidates` output. |
| Preview failures preserve review state and retry the same draft | `_generate_outcome_review()` leaves `state.outcome_review` unchanged on error, marks preview errors with `outcome-preview`, and Retry calls reviewed generation with `preview=True`. The two preview tests verify inclusion/order/edits/user-added outcome/gaps and object identity across retry. |
| Reviewed-write errors keep quick-review navigation; conflict can overwrite once | `_error_options()` distinguishes `outcome-write` conflict (`retry == "outcome-write"`) from ordinary write failure. `Overwrite once` calls `_generate_outcome_review(..., preview=False, force=True)`, not session generation. `test_reviewed_write_conflict_overwrites_with_reviewed_generation` verifies the calls. |
| Error state stores a discriminator rather than a closure | `_ErrorState.retry: str | None` stores `outcome-synthesis`, `outcome-preview`, or `outcome-write`; dispatch uses those strings. |

## Files and behavior

- `src/iiwi/interactive/controller.py`: adds outcome-specific error kinds/options, synthesis and reviewed-generation recovery routes, fallback dispatch, and reviewed overwrite handling.
- `src/iiwi/interactive/models.py`: adds transient `ReportDraft.generation_notice` defaulting to `None`.
- `src/iiwi/interactive/cli_actions.py` and `src/iiwi/cli.py`: thread the explicit fallback warning into `ReportService`.
- `tests/unit/interactive/test_outcome_review_failures.py`: adds seven focused path tests covering all six brief scripts plus the report-service warning boundary.

`src/iiwi/errors.py` and `src/iiwi/interactive/render.py` require no Task 6 modification: `OutcomeSynthesisError` already exists and the generic recoverable-error renderer renders the supplied options. The existing `OutcomeSynthesisResult.failed_session_ids` contract remains produced by `OutcomeSynthesisService`; its corresponding ungrouped candidates flow through the result outcomes into Quick Review.

## TDD evidence

Git history provides the recoverable record:

- `git show 35609dc:tests/unit/interactive/test_outcome_review_failures.py` exits `128`: the test file did not exist in the parent.
- Commit `2b9af45` adds the seven failure-path tests and the minimal production changes together. The historical commit does not preserve a pre-green pytest transcript, so a prior red run cannot be independently reconstructed; the test addition and parent absence establish that these are new regression cases rather than inherited passing coverage.

Fresh verification (the exact pytest argument lists from the brief):

```text
$ UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_outcome_review_failures.py -q
.......                                                                  [100%]
7 passed in 0.21s
EXIT=0

$ UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_outcome_review_failures.py tests/unit/interactive/test_interactive_regressions.py tests/unit/interactive/test_controller_generation.py -q
.........................                                                [100%]
25 passed in 0.31s
EXIT=0
```

The initially requested literal `uv run ...` command was attempted first but could not initialize `/root/.cache/uv` because that filesystem is read-only. Redirecting only uv's cache to the writable temporary directory allowed the identical test invocations to run; no project behavior or test selection changed.

## Self-review

- Confirmed each required option list and its order exactly matches the brief.
- Confirmed Retry targets use the existing filtered selection/review instead of a rescan or a captured callback.
- Confirmed every preview/write exception route retains `state.outcome_review` and resets `draft.dry_run` in `finally`.
- Confirmed fallback notice is exact, visible to the session report builder, and cleared on both success and expected generation failures via `finally`.
- Confirmed conflict overwrite invokes reviewed generation with `force=True` and never calls `actions.generate()`.
- Confirmed no formatting errors (`git diff --check` clean) and no uncommitted source changes.

## Concerns

None for the Task 6 implementation. The only verification-environment issue was uv's default read-only cache location, resolved by the per-command cache directory override described above.
