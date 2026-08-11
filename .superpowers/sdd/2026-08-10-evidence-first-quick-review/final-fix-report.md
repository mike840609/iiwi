# Final fix wave report

Branch: `feat/evidence-first-quick-review`
Base reviewed commit: `f38ebee`
Final fix commit: pending at report-write time
Date: 2026-08-11

## Outcome

All Important final-review findings were addressed in one coherent fix wave. The fixes keep the approved design intact: Quick Review still synthesizes an editable outcome draft from selected sessions, but model output is now treated as a proposal and all rendered evidence, supported Impact, completion status, source refs, split children, and merge authorization are reconstructed from local extracted evidence.

No Important finding was blocked by or contradicted the approved spec.

## TDD evidence

### Initial RED

Command:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py tests/unit/models/test_outcome.py tests/unit/interactive/test_outcome_review_controller.py tests/unit/interactive/test_outcome_review_failures.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_render.py tests/unit/renderers/test_outcome_markdown.py tests/unit/renderers/test_narrative.py tests/unit/summarizers/test_outcome_prompt.py tests/unit/summarizers/test_opencode_run.py tests/unit/security/test_secure_files.py -q
```

Result before implementation: exited non-zero with 24 intended focused failures after one test-fixture correction. The failures covered unsupported model claims, local file refs, omitted extracted sessions, duplicate ids, unobserved linkage values, child evidence/Impact leakage, setup bypass, unchanged re-entry, fallback notice loss, Quick Review period/Impact continuation, Manager/Engineering parity, Brief narrative leakage, temp cleanup, temp I/O translation, and atomic no-overwrite conflicts.

Late minor RED:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py::test_ungrouped_failed_session_references_are_redacted -q
```

Result before fix:

```text
1 failed
AssertionError: assert 'secret-session' not in 'token=secret-session'
```

### Final GREEN / verification

Focused suite:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py tests/unit/models/test_outcome.py tests/unit/interactive/test_outcome_review_controller.py tests/unit/interactive/test_outcome_review_failures.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_render.py tests/unit/renderers/test_outcome_markdown.py tests/unit/renderers/test_narrative.py tests/unit/summarizers/test_outcome_prompt.py tests/unit/summarizers/test_opencode_run.py tests/unit/security/test_secure_files.py -q
```

Result:

```text
112 passed in 0.49s
```

Integration report/CLI:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/integration/test_report_service.py tests/integration/test_cli.py -q
```

Result:

```text
82 passed, 2 skipped in 1.02s
```

Interactive CLI integration:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/integration/test_interactive_cli.py -q
```

Result:

```text
9 passed in 0.31s
```

Documentation/config:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/test_documentation.py tests/unit/test_interactive_documentation.py tests/unit/test_config.py -q
```

Result:

```text
47 passed in 0.26s
```

Ruff:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run ruff check .
```

Result:

```text
All checks passed!
```

Pyright:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pyright
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Diff whitespace:

```bash
git diff --check
```

Result: no output, exit 0.

Full pytest:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest -q
```

Result:

```text
5 failed, 772 passed, 4 skipped in 3.47s
```

The five failures are the exact known baseline failures documented at `f38ebee`:

- `tests/unit/interactive/test_render.py::test_session_review_gives_the_three_repository_glyphs_three_styles`
- `tests/unit/interactive/test_render.py::test_session_review_colors_selection_markers_by_state`
- `tests/unit/interactive/test_render.py::test_session_browser_separates_the_cursor_from_the_expansion_glyph`
- `tests/unit/interactive/test_render.py::test_report_setup_gives_the_generate_action_its_own_colour`
- `tests/unit/test_logging.py::test_settings_table_shows_values_sources_and_defaults`

## Per-finding mapping

| Finding | Fix summary | Main tests |
| --- | --- | --- |
| 1. Evidence trust boundary accepts ungrounded claims and merge authorization | `OutcomeSynthesisService` now extracts and redacts local `SessionEvidence` first, sends only extracted evidence to the runner, and reconstructs output from local evidence. Unsupported model Impact remains blank. Completed status requires high-confidence completed evidence. Evidence refs are rebuilt locally, including files and commit-looking values. Cross-repo merges require observed signal values, not just model JSON. | `test_unsupported_model_claims_are_not_copied_from_activity_free_session`, `test_evidence_refs_include_locally_extracted_file_references`, `test_linkage_signal_values_must_be_observed_in_local_evidence`, `test_high_confidence_cross_repo_merge_requires_two_independent_signals` |
| 2. Candidate IDs and split recovery are unreliable | Synthesized ids now include a stable discriminator, so duplicate proposals with the same title/session set remain uniquely targetable. Source groups are built for supported cross-repo merges and same-repo multi-session merges. Split children get their own refs, child-supported Impact, and child-supported status instead of copying unsupported parent claims. | `test_duplicate_model_proposals_keep_stable_unique_candidate_ids`, `test_real_cross_repo_merge_splits_into_named_repository_outcomes`, `test_split_children_do_not_inherit_unsupported_parent_impact` |
| 3. Setup Generate/Preview bypasses Quick Review and re-entry discards edits | Setup `g`, Enter, and preview routing now stop at `OUTCOME_REVIEW`; the user must explicitly preview or generate from Quick Review. Controller stores a selected-session key and reuses the in-memory review draft when the selection is unchanged. | `test_setup_generate_enters_quick_review_before_output`, `test_setup_preview_enters_quick_review_before_output`, `test_reentering_quick_review_with_unchanged_selection_preserves_existing_draft`, updated legacy flow tests |
| 4. More candidates cannot visibly become/reorder among primary outcomes | Including a `MORE` outcome now promotes it to `PRIMARY`, so visible Quick Review order and generated order stay aligned. | `test_including_more_candidate_promotes_it_to_primary_review_order`, `test_twenty_line_quick_review_expands_more_evidence_and_recovers_preview` |
| 5. Complete failure and fallback recovery are incomplete | All extraction failure raises `OutcomeSynthesisError` and reaches controller recovery instead of producing an Ungrouped-only success. Temp/file I/O errors from synthesis are translated for recovery. The session-fallback notice now survives an output conflict and is cleared only after a successful fallback write. | `test_all_extraction_failures_raise_complete_synthesis_error`, `test_synthesize_translates_temp_io_failure_for_controller_recovery`, `test_session_fallback_notice_survives_output_conflict_overwrite` |
| 6. Report type and Detail parity are incomplete | Outcome Markdown now has deterministic Manager vs Engineering differences beyond the heading via audience text, and existing report-type defaults continue to select Brief for Manager and Full for Engineering unless the user overrides Detail. Brief narrative rendering now filters full-depth sections, session ids, file paths, command/evidence-oriented sections, and Usage even if the model body contains them. The synthesis prompt is audience-neutral. | `test_report_type_changes_audience_text_beyond_the_heading`, `test_narrative_brief_filters_full_depth_sections_from_model_body`, `test_outcome_prompt_is_audience_neutral`, existing detail/default tests |
| 7. Quick Review omits required reporting period | `render_outcome_review` accepts the period and the controller passes the draft period into the header. | `test_outcome_review_header_includes_the_reporting_period` |
| 8. Sensitive synthesis data persists indefinitely | `OpenCodeRunner.run()` now owns a secure temporary directory when no caller workdir is supplied and deletes it on both success and failure. Caller-supplied workdirs remain caller-owned. Tempfile setup/read/write `OSError`s are converted to `OpenCodeRunError`. | `test_run_removes_owned_tempdir_on_success_and_failure`, `test_run_translates_tempfile_io_failures` |
| 9. Reviewed no-overwrite guarantee is race-prone | `atomic_secure_write(force=False)` now writes to a temp file and finalizes with `os.link(temp, destination)`, so a destination created after the precheck raises `ReportAlreadyExistsError` instead of being overwritten. `force=True` still uses `os.replace`. | `test_atomic_write_rejects_file_created_after_initial_check`, existing write/conflict tests |

## Minor findings addressed

- Empty Impact is now rendered explicitly as `Unsupported by extracted evidence` in Quick Review and reviewed Markdown, while the model field remains blank when unsupported.
- Truncated focused Impact/evidence lines now end with an ellipsis continuation marker.
- Failed-session ungrouped titles and fallback evidence refs are redacted before rendering.
- `git diff --check` is clean.

Live terminal resize coverage was not expanded in this final wave because the existing viewport tests already cover width/height combinations and the final review marked live SIGWINCH as a baseline unverified environment item, not an Important blocker.

## Design decisions

- The model may choose grouping and propose wording, but local extraction owns authorization. Title text is accepted only when its significant words appear in the local extracted corpus; otherwise the fallback title is derived from session/repository facts. Impact is stricter: it must appear as an exact normalized local text substring or it remains blank.
- Completion status is not accepted from the model alone. A proposed completed outcome becomes completed only when at least one selected session has a high-confidence completed evidence item, currently from observed successful verification evidence.
- Linkage signal kinds and values are both checked. Unsupported kinds, blank values, and values not present in the local corpus cannot authorize a cross-repository merge.
- Omitted extracted sessions are not treated as errors because a model can legitimately rank only the strongest outcomes, but they are preserved as excluded Ungrouped candidates so the reviewer can recover them.
- Source-group split children intentionally preserve only child evidence refs plus child-supported Impact/status. Unsupported parent Impact is not copied to children.
- Setup actions intentionally changed from one-step output to two-step review: setup `g`/preview enters Quick Review, then Quick Review `g`/`p` writes/previews.
- The no-overwrite race fix uses POSIX hard-link finalization for `force=False`, keeping the existing replace behavior only for `force=True`.

## Residual concerns

- The only failing tests are the exact five known baseline failures from `f38ebee`.
- Physical TTY behavior, live SIGWINCH resize, Windows/non-root chmod behavior, real model quality, and a real concurrent writer process were not newly verified in this wave; they remain the same baseline environmental gaps called out in the final review.
