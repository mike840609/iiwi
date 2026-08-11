# Second-wave fix report: evidence-first Quick Review

## Status

`DONE_WITH_CONCERNS`

The authorized second-wave repair is committed as `89e4475` (`fix: harden quick review evidence boundaries`). The only remaining test failures are the five documented baseline failures listed below; none exercise this change set's evidence, Quick Review, or report-rendering boundaries.

## Changes delivered

1. Cross-repository synthesis now authorizes a merge only when a shared work id, or both allowed independent linkage values, are observed in the extracted evidence for every participating repository. High-confidence and allowed-kind restrictions remain unchanged.
2. Outcome rendering exposes a deterministic audience-specific status view. Brief narrative rendering now has an allowlist for reader-facing sections and removes session, file, command, branch, commit/revision, fenced-code, Usage, and unexpected-section details. Plain safe model summaries without headings remain available in Brief.
3. Quick Review reuse identity now includes effective Detail in addition to the selected session IDs, so changing Detail regenerates synthesis while unchanged identity preserves the in-memory draft.
4. Commit evidence extraction now requires explicit `commit`, `revision`, or `rev` context before accepting a 7–40-character hexadecimal value.
5. Removed the accidentally tracked `final-fix-report.md`; corrected the extra EOF blank line in `docs/evidence-first-quick-review.md`.

## Regression tests and TDD evidence

### 1. Repository-grounded cross-repository linkage

Test added: `test_cross_repo_merge_requires_each_linkage_signal_in_each_repository` in `tests/unit/services/test_outcomes.py`.

- RED: `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py::test_cross_repo_merge_requires_each_linkage_signal_in_each_repository -q` → failed as intended: aggregate linkage authorization produced 1 outcome where the test required 2.
- GREEN: same focused command → `1 passed`; covering file command `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py -q` → `26 passed` after all second-wave tests.

### 2. Deterministic Report type and Brief narrative boundary

Tests added or strengthened:

- `test_report_type_renders_audience_specific_status_view` in `tests/unit/renderers/test_outcome_markdown.py`.
- `test_narrative_brief_rejects_adversarial_technical_evidence` in `tests/unit/renderers/test_narrative.py`, covering session IDs, file paths, branches, commits, inline/fenced commands, Usage, and an unexpected technical section.
- `test_narrative_brief_retains_plain_safe_model_summary` in `tests/unit/renderers/test_narrative.py`.

- RED (status view): `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/renderers/test_outcome_markdown.py::test_report_type_renders_audience_specific_status_view -q` → failed because the required Manager status view was absent.
- GREEN (status view): same command → `1 passed`; covering renderer command `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/renderers/test_outcome_markdown.py -q` → `8 passed`.
- RED (narrative): `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/renderers/test_narrative.py::test_narrative_brief_rejects_adversarial_technical_evidence -q` → initially failed because branch/commit/code/technical details leaked; a later inline-command extension also failed as intended because `uv run deploy` leaked.
- GREEN (narrative): the same adversarial command → `1 passed`; covering narrative command `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/renderers/test_narrative.py -q` → `9 passed`.
- RED (plain summary compatibility): `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/renderers/test_narrative.py::test_narrative_brief_retains_plain_safe_model_summary -q` → failed because unheaded safe prose was dropped.
- GREEN (plain summary compatibility): focused command → `1 passed` alongside the adversarial test.

### 3. Detail-sensitive Quick Review reuse

Test added: `test_changing_detail_in_setup_regenerates_quick_review_draft` in `tests/unit/interactive/test_outcome_review_controller.py`.

- RED: `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_outcome_review_controller.py::test_changing_detail_in_setup_regenerates_quick_review_draft -q` → failed as intended: synthesis ran once instead of twice after Detail changed in setup.
- GREEN: same focused command → `1 passed`; covering file command `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_outcome_review_controller.py -q` → `14 passed`.

### 4. Contextual commit evidence

Tests added: `test_arbitrary_hex_identifier_is_not_commit_evidence` and `test_contextual_revision_is_commit_evidence` in `tests/unit/services/test_outcomes.py`.

- RED: false-positive command `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py::test_arbitrary_hex_identifier_is_not_commit_evidence -q` → failed because `8badf00d` was emitted as a commit. The paired command for both tests reported `1 failed, 1 passed`, preserving the valid contextual revision behavior.
- GREEN: paired command → `2 passed`; covering outcome-service command → `26 passed`.

## Verification

| Check | Command | Result |
| --- | --- | --- |
| Focused | `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py tests/unit/interactive/test_outcome_review_controller.py tests/unit/renderers/test_outcome_markdown.py tests/unit/renderers/test_narrative.py tests/unit/summarizers/test_outcome_prompt.py tests/unit/interactive/test_review_regressions.py -q` | `70 passed in 0.56s` |
| Ruff | `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run ruff check .` | `All checks passed!` |
| Pyright | `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pyright` | `0 errors, 0 warnings, 0 informations` |
| Full suite | `UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest -q` | `5 failed, 779 passed, 4 skipped in 5.27s` |
| Diff | `git diff --check` | exit 0, no output |

## Remaining concerns

The final full suite continues to fail on exactly these five documented baseline assertions:

1. `tests/unit/interactive/test_render.py::test_session_review_gives_the_three_repository_glyphs_three_styles`
2. `tests/unit/interactive/test_render.py::test_session_review_colors_selection_markers_by_state`
3. `tests/unit/interactive/test_render.py::test_session_browser_separates_the_cursor_from_the_expansion_glyph`
4. `tests/unit/interactive/test_render.py::test_report_setup_gives_the_generate_action_its_own_colour`
5. `tests/unit/test_logging.py::test_settings_table_shows_values_sources_and_defaults`

These are pre-existing rendering/logging baseline failures and are not load-bearing for the repaired evidence-first Quick Review paths. The initial full-suite run also exposed a sixth failure in `tests/integration/test_cli.py::test_run_detail_flags_keep_session_reports_and_bypass_outcome_synthesis`; it was caused by this wave's initial strict Brief filter and was fixed before final verification.
