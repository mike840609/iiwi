# Task 4 Report: Quick Review Actions, Configuration, and Draft Editing

Status: DONE_WITH_CONCERNS

Commit: `c6fe165ca36de97ab4e03146c0e88ed492d8bd39` (`feat: add quick review controller flow`)

## Summary

Implemented the Task 4 configuration, action adapters, controller state, Quick Review mutations, reviewed preview/write routing, and fixture integration. The Task 5 viewport renderer and Task 6 retry/session-report fallback UX remain out of scope; Task 4 adds only the required outcome-review dispatch/render hook and preserves the in-memory review state for those later tasks.

## RED evidence

Command:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/test_config.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_controller.py -q
```

Result:

```text
20 failed, 21 passed
```

The failures were the expected missing Task 4 contracts:

- `ReportSettings.quick_review_report_type` did not exist and was absent from config list/set/unset.
- `_new_draft()` did not apply the saved report type.
- `_synthesize()`, `_generate_reviewed()`, prompt adapters, and `_save_report_type()` did not exist.
- `InteractiveActions` rejected the new callbacks.
- The controller did not dispatch `Screen.OUTCOME_REVIEW` or any review mutation keys.

The initial worktree baseline was also recorded before edits:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive -q
188 passed, 4 failed
```

All four failures were pre-existing ANSI style assertions in `tests/unit/interactive/test_render.py`.

## GREEN evidence

Focused Task 4 command:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/test_config.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_controller.py -q
41 passed in 0.41s
```

Full interactive command required by the brief:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive -q
205 passed, 4 failed in 1.20s
```

The only failures are the same four baseline ANSI style assertions:

- `test_session_review_gives_the_three_repository_glyphs_three_styles`
- `test_session_review_colors_selection_markers_by_state`
- `test_session_browser_separates_the_cursor_from_the_expansion_glyph`
- `test_report_setup_gives_the_generate_action_its_own_colour`

Task 4 interactive regressions with those known baseline cases deselected:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive -q \
  --deselect=tests/unit/interactive/test_render.py::test_session_review_gives_the_three_repository_glyphs_three_styles \
  --deselect=tests/unit/interactive/test_render.py::test_session_review_colors_selection_markers_by_state \
  --deselect=tests/unit/interactive/test_render.py::test_session_browser_separates_the_cursor_from_the_expansion_glyph \
  --deselect=tests/unit/interactive/test_render.py::test_report_setup_gives_the_generate_action_its_own_colour
205 passed, 4 deselected in 1.11s
```

Static verification:

```text
uv run ruff check <Task 4 source and interactive tests>
All checks passed!

uv run pyright src/iiwi/config.py src/iiwi/interactive/cli_actions.py src/iiwi/interactive/controller.py
0 errors, 0 warnings, 0 informations

git diff --check
exit 0
```

## Files changed

Production:

- `src/iiwi/config.py`
  - Added `report.quick_review_report_type` with the verbatim Manager default.
- `src/iiwi/interactive/cli_actions.py`
  - Applied the saved report type to new drafts.
  - Added synthesis and reviewed-generation adapters.
  - Added explicit edit/add/gap prompts and report-type persistence.
- `src/iiwi/interactive/controller.py`
  - Extended `InteractiveActions`.
  - Added outcome review state, targets, mutations, preview/write transitions, and dispatch/render hooks.
  - Preserved reviewed state across preview and recoverable errors.
  - Cleared reviewed state for new report, generate another, rescan, setup invalidation, and activity reload.

Tests:

- `tests/unit/test_config.py`
- `tests/unit/interactive/test_cli_actions.py`
- `tests/unit/interactive/test_outcome_review_controller.py`
- `tests/unit/interactive/test_activity_first_home.py`
- `tests/unit/interactive/test_collapsed_advanced_settings.py`
- `tests/unit/interactive/test_controller.py`
- `tests/unit/interactive/test_controller_generation.py`
- `tests/unit/interactive/test_controller_results.py`
- `tests/unit/interactive/test_interactive_regressions.py`
- `tests/unit/interactive/test_review_regressions.py`
- `tests/unit/interactive/test_selection_memory.py`
- `tests/unit/interactive/test_unified_activity_review.py`

## Self-review

- Verified `_synthesize()` constructs exactly one `OpenCodeRunner` using the narrative executable, model, and run timeout and receives the already-filtered scan.
- Verified default detail is derived from report type without falsely marking it overridden; explicit detail state is carried when present.
- Verified `_generate_reviewed()` passes the identical `OutcomeReviewDraft` object into `ReportService.generate_reviewed()`.
- Verified typed prompts occur only after explicit review actions. Blank add titles cancel; blank or case-insensitive `none` gaps normalize to `None`.
- Verified editing applies only title, status, and Impact, preserving synthesized identifiers and evidence.
- Verified uppercase `J/K` reorder before case-insensitive navigation handling, while lowercase `j/k` remain navigation.
- Verified setup Generate/Preview remain one-action flows but use synthesis plus reviewed generation. Explicit Session Review `g` opens Quick Review before reviewed generation.
- Verified setup Preview returns to Report Setup, while Quick Review `p` and `b` return to the same review object.
- Verified existing scan-count, selection filtering, overwrite-once, generate-another, preview, result-path, and terminal fixture assertions remain active.
- Verified direct session-based generation has no ordinary key binding and remains available for Task 6's explicit complete-synthesis fallback.
- Reviewed the diff for Task 5/6 scope leakage. No viewport rendering, synthesis retry menu, partial-failure UI, or fallback warning implementation was added.

## Concerns

- The exact full interactive command remains non-green because of four pre-existing Rich ANSI encoding/style assertion failures. Task 4 does not modify `render.py` or those assertions, and the same four failures were present in the baseline.
- The `OUTCOME_REVIEW` render hook is intentionally empty until Task 5 supplies the rendered-line-aware viewport.
- Task 6 still owns synthesis failure, reviewed preview/write retry routes, and the explicit session-report fallback. Task 4 only preserves the state and existing overwrite seam needed by those routes.

## Fix round 1: Review findings

Status: DONE_WITH_CONCERNS

Commit: `6014cd5` (`fix: clear quick review gaps on blank input`)

### Findings addressed

Major — blank input could not clear an existing Blockers or Next week value:

- Root cause: `_edit_gap()` passed the current value as Typer's default, so Enter returned that value before the blank-to-`None` normalization branch.
- Fix: the current value is now embedded in the prompt label as context, while the hidden prompt default is always empty. Enter therefore returns blank and normalizes to `None`; literal `none` remains case-insensitively normalized to `None`.
- Regression: a real `CliRunner` prompt sends Enter with an existing value, verifies that the existing text is displayed, and verifies the result is `None`.

Minor — navigation/reordering coverage omitted lowercase `k` and uppercase `J`:

- Fix: the controller test is parameterized across `jjk` + `J` and `jj` + `K`. The first case requires lowercase `k` to focus the item that uppercase `J` moves; together the cases cover lowercase `j/k` navigation and uppercase `J/K` reordering.

### RED evidence

Command:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive/test_cli_actions.py::test_edit_gap_enter_clears_an_existing_value_with_the_real_prompt -q
```

Output:

```text
F                                                                        [100%]
FAILED tests/unit/interactive/test_cli_actions.py::test_edit_gap_enter_clears_an_existing_value_with_the_real_prompt
AssertionError: assert '<none>' in 'Blockers [Waiting on review]: \nWaiting on review\n'
1 failed in 0.22s
```

The key-coverage-only change passed immediately against the existing correct controller behavior:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive/test_outcome_review_controller.py -q -k 'uppercase_j_and_k'
2 passed, 8 deselected in 0.13s
```

### GREEN evidence

Direct gap regressions:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive/test_cli_actions.py::test_edit_gap_enter_clears_an_existing_value_with_the_real_prompt tests/unit/interactive/test_cli_actions.py::test_edit_gap_normalizes_blank_and_none_to_none -q
....                                                                     [100%]
4 passed in 0.19s
```

Task 4 focused command:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/test_config.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_controller.py -q
...........................................                              [100%]
43 passed in 0.29s
```

Relevant interactive command:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_controller.py tests/unit/interactive/test_controller_generation.py tests/unit/interactive/test_collapsed_advanced_settings.py -q
........................................                                 [100%]
40 passed in 0.31s
```

Full interactive command:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive -q
4 failed, 207 passed in 0.98s
```

The failures are exactly the four unchanged, pre-existing ANSI style assertions listed earlier in this report. With those baseline cases deselected:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pytest tests/unit/interactive -q --deselect=tests/unit/interactive/test_render.py::test_session_review_gives_the_three_repository_glyphs_three_styles --deselect=tests/unit/interactive/test_render.py::test_session_review_colors_selection_markers_by_state --deselect=tests/unit/interactive/test_render.py::test_session_browser_separates_the_cursor_from_the_expansion_glyph --deselect=tests/unit/interactive/test_render.py::test_report_setup_gives_the_generate_action_its_own_colour
207 passed, 4 deselected in 0.87s
```

Static checks:

```text
UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run ruff check src/iiwi/interactive/cli_actions.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_controller.py
All checks passed!

UV_CACHE_DIR=/tmp/iiwi-task4-uv-cache uv run pyright src/iiwi/interactive/cli_actions.py
0 errors, 0 warnings, 0 informations

git diff --check
exit 0
```

### Fix self-review

- Existing values remain visible as non-default context, so users can retype or replace them.
- Enter is now the explicit clear action for both Blockers and Next week because both use `_edit_gap()`.
- Literal `none`, including mixed case, remains supported.
- The controller implementation was not changed; only the missing key coverage was added.
- No renderer, viewport, synthesis recovery, fallback, or unrelated ANSI behavior changed.
