# Task 7 Report: End-to-end Compatibility, Documentation, and Final Verification

## Status

DONE_WITH_CONCERNS. Task 7 behavior, documentation, static checks, integration
coverage, and acceptance-focused verification are complete. The full suite has
the same five known failures as the pre-feature baseline; no new regression is
present. A real interactive terminal was not available in this execution
environment, so viewport verification used deterministic Rich `Console`
width/height coverage and the attempted bare command documented below.

## Changes

- Added an end-to-end Quick Review flow using a deterministic synthesis runner,
  real reviewed-report rendering, and a temporary output directory.
- Added a 20-row six-candidate flow covering More candidates, candidate
  replacement, expanded evidence, preview failure, return, and successful retry.
- Preserved the legacy `run` wizard and added its required explicit
  `--detail brief|full` compatibility option without entering outcome synthesis.
- Fixed candidate defaults so only the first five synthesized outcomes are
  selected; More and Ungrouped candidates remain retained but unselected.
- Documented the shipped Quick Review flow, key map, recovery behavior,
  report-mode responsibilities, configuration key, environment variable, and
  version-one exclusions.

## Red-green evidence

### `run --detail` compatibility

RED:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/integration/test_interactive_cli.py tests/integration/test_cli.py -q
2 failed, 65 passed, 2 skipped
```

The new compatibility test failed because `runner.invoke(app, ["run",
"--detail", "brief"])` exited 2. The other failure showed an older integration
fixture had not been updated for the already-shipped `InteractiveActions`
interface.

GREEN after adding the optional run detail flag, forwarding `None` from the
prompt menu, and updating the integration fixture:

```text
67 passed, 2 skipped
```

The final fresh integration result, after all acceptance fixes, is:

```text
68 passed, 2 skipped in 0.67s
```

### Candidate selection cap

RED for the six-candidate replacement flow:

```text
assert sum(item.included for item in reviewed) == 5
E assert 4 == 5
```

The sixth More candidate had started selected, so replacing a primary outcome
actually removed one. GREEN after selecting only ranks 0–4: `1 passed`.

RED for partial synthesis:

```text
assert sum(outcome.included for outcome in result.outcomes) == 5
E assert 6 == 5
```

The Ungrouped extraction failure had also started selected. GREEN after retaining
Ungrouped candidates unselected: `1 passed`.

### Documentation

RED:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/test_documentation.py tests/unit/test_interactive_documentation.py -q
4 failed, 27 passed
```

Failures named the absent exact config key, missing environment variable, missing
guide, and missing `p Preview` / `g Generate` distinction.

GREEN:

```text
31 passed in 0.11s
```

The primary Tasks 1–6 end-to-end review path passed when first characterized;
the candidate-default extensions above supplied the failing regression evidence
for behavior that still missed the final acceptance gate.

## Requirements mapping

| Requirement | Evidence |
|---|---|
| New report → Review sessions → outcomes → exclude/edit/reorder/add/gaps → Preview → Back → Generate → Result | `test_quick_review_writes_the_exact_reviewed_draft` drives the key sequence and reads the real temporary Markdown output. |
| Reviewed order, edits, exclusion, User-added label, gaps, no unsupported Impact | The end-to-end output assertions cover all fields, preserve session evidence for edited outcomes, and verify excluded/unsupported text is absent. |
| 20-row, six candidates, More candidates, evidence expansion, preview recovery | `test_twenty_line_quick_review_expands_more_evidence_and_recovers_preview`. |
| Up to five preselected; More and Ungrouped retained | The six-candidate replacement assertion and `test_partial_synthesis_retains_failures_without_preselecting_over_five`. |
| Legacy `run --detail brief|full` remains session based | `test_run_detail_flags_keep_session_reports_and_bypass_outcome_synthesis`; both exact `runner.invoke` shapes exit 0, bypass Quick Review, and retain narrative/structured detail distinctions. |
| Manager/Engineering and Brief/Full | Outcome renderer parameter coverage plus the reviewed report integration tests; the responsibility table documents ownership and defaults. |
| Retry and explicit session fallback | Existing controller failure tests plus acceptance-focused deterministic verification below. |
| Exact configuration surface | Documentation test pins `report.quick_review_report_type`, `IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE`, and a real `config set` command; the existing resolver tests validate documented keys/variables. |
| Version-one exclusions | New guide explicitly documents No persistent drafts and No manual merge. |

## Verification commands and results

### Integration

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/integration/test_interactive_cli.py tests/integration/test_cli.py -q
68 passed, 2 skipped in 0.67s
```

The two skips are the existing chmod permission-denial checks skipped when
running as root.

### Documentation

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/test_documentation.py tests/unit/test_interactive_documentation.py -q
31 passed in 0.11s
```

### Static checks

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pyright
0 errors, 0 warnings, 0 informations
```

### Full suite

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest -q
743 passed, 5 failed, 4 skipped in 3.48s
```

The five failures exactly match the binding pre-feature baseline:

1. `tests/unit/interactive/test_render.py::test_session_review_gives_the_three_repository_glyphs_three_styles`
2. `tests/unit/interactive/test_render.py::test_session_review_colors_selection_markers_by_state`
3. `tests/unit/interactive/test_render.py::test_session_browser_separates_the_cursor_from_the_expansion_glyph`
4. `tests/unit/interactive/test_render.py::test_report_setup_gives_the_generate_action_its_own_colour`
5. `tests/unit/test_logging.py::test_settings_table_shows_values_sources_and_defaults`

Baseline before feature work was 662 passed, 5 failed, 4 skipped. The final run
adds 81 passing tests and preserves the same failure/skip counts and identities.
No baseline failure was hidden, weakened, or rewritten.

## Viewport and fallback verification

Attempting the requested real command showed the environment limitation
precisely:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run iiwi
exit code 3
Error: iiwi needs a terminal to show the menu; run a subcommand directly instead
```

The deterministic substitute used Rich consoles at 20, 24, and 30 rows, long
Impact/evidence values, multiple widths and focus positions, and the complete
20-row recovery flow:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest \
  tests/unit/interactive/test_viewport_wrapping_regressions.py::test_outcome_review_fits_width_height_and_focus_matrix \
  tests/integration/test_interactive_cli.py::test_twenty_line_quick_review_expands_more_evidence_and_recovers_preview \
  tests/integration/test_interactive_cli.py::test_quick_review_writes_the_exact_reviewed_draft \
  tests/integration/test_interactive_cli.py::test_partial_synthesis_retains_failures_without_preselecting_over_five \
  tests/unit/interactive/test_outcome_review_failures.py::test_complete_synthesis_failure_can_generate_labeled_session_fallback \
  tests/unit/interactive/test_outcome_review_failures.py::test_preview_error_back_restores_the_complete_in_memory_review \
  tests/unit/renderers/test_outcome_markdown.py::test_report_type_controls_heading_and_sections \
  tests/unit/renderers/test_outcome_markdown.py::test_brief_hides_session_file_and_commit_evidence \
  tests/unit/renderers/test_outcome_markdown.py::test_full_groups_evidence_by_repository -q
10 passed in 0.41s
```

This covers focus/action-help visibility; truncation of long Impact/evidence;
More candidate replacement; Preview Back preserving edits; forced preview
failure and successful retry; complete-synthesis session fallback; and final
Report type/Detail rendering. It is deterministic integration coverage, not a
claim that a physical terminal was manually inspected.

## Diff self-review

- `git diff --check`: clean.
- Reviewed every changed production, test, and documentation file.
- Production changes are limited to the two acceptance gaps proven by red tests:
  optional legacy `run --detail` and selection defaults for More/Ungrouped.
- The new end-to-end helper uses a deterministic synthesis runner and the real
  synthesis service, controller, renderer, secure write path, and temporary
  output directory; external model execution is the only substituted boundary.
- No unrelated baseline failure or user change was modified.
- Documentation describes only reachable keys, recovery choices, configuration,
  and report behavior verified in the implementation/tests.

## Commit

`6c68d99 docs: document evidence-first quick review`

## Concerns

1. The repository full suite remains non-green because of the five explicitly
   pre-existing ANSI/wrapping failures listed above; Task 7 adds no regression.
2. A physical 20/24/30-row interactive TTY was unavailable. Deterministic Rich
   Console integration coverage replaced manual terminal inspection, as allowed
   by the Task 7 brief.

---

## Fix round 1/5 — reviewer findings

### Scope and root causes

1. Interactive synthesis used `OpenCodeRunner` directly. Its missing executable,
   timeout, non-zero exit, and missing-output paths raise `OpenCodeRunError`, but
   the controller recovery boundary catches `OutcomeSynthesisError`. The adapter
   did not translate between those two contracts.
2. Cross-repository synthesis created `OutcomeSourceGroup` values with ids and
   evidence but left `title` at `""`. The documented `s Split` action uses the
   group title verbatim, so real synthesized splits rendered blank outcome names.
3. The legacy `run` command rejected every report whose `repositories` list was
   empty. A successful narrative report intentionally stores its prose in
   `narrative_text` and has no structured repositories, so it wrote the file and
   then exited 4 before history recording. The `report` command already used the
   correct `not repositories and not narrative_text` guard.
4. README conflated transcript-source CLI requirements with Quick Review
   synthesis requirements for Claude Code and Codex.

### Critical: real OpenCode failure reaches recovery

RED, using the real `OutcomeSynthesisService` with an `OpenCodeRunner` boundary
that raises the production exception type:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_cli_actions.py::test_synthesize_translates_real_opencode_failure_for_controller_recovery -q
1 failed in 0.23s
E iiwi.summarizers.opencode_run.OpenCodeRunError: missing-opencode: executable not found
```

The minimal adapter fix catches `OpenCodeRunError` and raises
`OutcomeSynthesisError` with exception chaining, which is the controller's
recoverable contract. GREEN, including Retry and explicit session fallback:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_cli_actions.py::test_synthesize_translates_real_opencode_failure_for_controller_recovery tests/unit/interactive/test_outcome_review_failures.py::test_synthesis_retry_reuses_filtered_scan_and_opens_quick_review tests/unit/interactive/test_outcome_review_failures.py::test_complete_synthesis_failure_can_generate_labeled_session_fallback -q
3 passed in 0.22s
```

### Important: real merged outcomes split into named groups

RED:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py::test_real_cross_repo_merge_splits_into_named_repository_outcomes -q
1 failed in 0.09s
E AssertionError: assert ['', ''] == ['repo-a', 'repo-b']
```

The minimal fix sets each synthesized source group's title to its traceable
repository id. GREEN across merge, real split, and the model split contract:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py::test_high_confidence_cross_repo_merge_requires_two_independent_signals tests/unit/services/test_outcomes.py::test_real_cross_repo_merge_splits_into_named_repository_outcomes tests/unit/models/test_outcome.py::test_split_restores_source_groups_and_preserves_evidence -q
3 passed in 0.08s
```

The integration test `test_quick_review_splits_a_real_cross_repository_merge`
now drives `New report → Review sessions → synthesis → s Split → Generate` and
asserts named `repo-a`/`repo-b` outcomes with the correct session evidence in the
written report.

### Important: real narrative run succeeds and records history

The earlier compatibility proof used a fake report model that populated
`repositories`, which could not exercise the narrative invariant. It was
replaced with real `ScanService`, `ReportService`, rule-based summarization,
Markdown rendering, secure output writing, narrative prompt construction, and
history persistence. Only the external narrative runner is deterministic.

RED:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/integration/test_cli.py::test_run_detail_flags_keep_session_reports_and_bypass_outcome_synthesis -q
1 failed in 0.30s
E assert 4 == 0
Error: no opencode activity found in the requested period
```

The minimal fix makes `run` use the same report-content guard as `report`.
GREEN also keeps the structured legitimate no-session generation error:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/integration/test_cli.py::test_run_detail_flags_keep_session_reports_and_bypass_outcome_synthesis tests/integration/test_cli.py::test_run_generation_says_sessions_were_excluded_when_configuration_drops_them -q
2 passed in 0.25s
```

The real-boundary test asserts both exact invocations, Brief narrative prompt and
output, Full structured session detail, no Quick Review dispatch, and two history
entries with `(narrative, detail)` values `(True, "brief")` and
`(False, "full")`.

### README dependency correction

RED:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/test_interactive_documentation.py::test_readme_distinguishes_transcript_reading_from_quick_review_synthesis -q
1 failed in 0.03s
E AssertionError: assert 'Claude Code / Codex (no CLI' not in README.md
```

GREEN after distinguishing direct transcript reading from local outcome
synthesis:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/test_interactive_documentation.py::test_readme_distinguishes_transcript_reading_from_quick_review_synthesis -q
1 passed in 0.01s
```

README now states that Claude Code and Codex CLIs are not needed to read their
stores, while Quick Review synthesis still requires local `opencode run` and
offers Retry/session fallback when unavailable.

### Amended verification

Focused unit coverage:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_failures.py tests/unit/services/test_outcomes.py tests/unit/models/test_outcome.py -q
47 passed in 0.27s
```

Integration:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/integration/test_interactive_cli.py tests/integration/test_cli.py -q
69 passed, 2 skipped in 0.71s
```

Documentation:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/test_documentation.py tests/unit/test_interactive_documentation.py -q
32 passed in 0.12s
```

Static checks:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pyright
0 errors, 0 warnings, 0 informations
```

Full suite:

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest -q
747 passed, 5 failed, 4 skipped in 3.40s
```

The five failures are still exactly the binding baseline failures: four ANSI
style assertions in `tests/unit/interactive/test_render.py` and the settings
table wrapping assertion in `tests/unit/test_logging.py`. No baseline failure was
changed or hidden, and this fix round adds no new failure.

### Fix-round self-review

- `git diff --check`: clean.
- Production changes are one exception translation, one source-group title, and
  one narrative-aware no-session predicate; no unrelated refactoring.
- The synthesis translation preserves the original `OpenCodeRunError` as the
  chained cause and leaves existing `OutcomeSynthesisError` validation paths
  unchanged.
- The narrative fix mirrors the already-shipped `report` command guard and keeps
  the structured empty-result error test green.
- The real merge/split integration path verifies the documented key rather than
  only model mutation.
- The reviewer's minor unsupported-Impact point was not expanded into a separate
  fix loop; the existing syntactic assertion remains unchanged.

### Fix-round commit

`f38ebee fix: close quick review recovery gaps`
