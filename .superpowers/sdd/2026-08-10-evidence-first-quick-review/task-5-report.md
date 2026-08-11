# Task 5 Report: Rendered-line-aware Single-screen TUI

## Status

DONE_WITH_CONCERNS

Task 5 is implemented and committed as `8ddcae2` (`feat: render outcome quick review TUI`).
The focused Task 5 tests pass. The full interactive suite retains exactly the four known
baseline ANSI-style failures and introduces no new failures.

## RED evidence

Command (with a writable uv cache because `/root/.cache/uv` is read-only in this environment):

```bash
env UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest \
  tests/unit/interactive/test_outcome_review_render.py \
  tests/unit/interactive/test_viewport_wrapping_regressions.py -q
```

Result before production changes:

```text
FFFFF......F                                                             [100%]
6 failed, 6 passed in 0.41s
```

All six failures were the expected missing-feature failures:

- `outcome_review_rows` did not exist.
- `render_outcome_review` did not exist.
- Existing viewport regression tests continued to pass.

## GREEN evidence

Focused renderer and viewport command:

```bash
env UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest \
  tests/unit/interactive/test_outcome_review_render.py \
  tests/unit/interactive/test_viewport_wrapping_regressions.py -q
```

Result:

```text
............                                                             [100%]
12 passed in 0.41s
```

The terminal matrix covers 45 combinations: widths 40/60/80/100/140, heights
20/24/30, and first/middle/last focus. It uses long title, Impact, repository,
session, file, commit, and status-message strings.

Full interactive command:

```bash
env UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive -q
```

Pre-change baseline:

```text
4 failed, 207 passed in 0.94s
```

Post-change result:

```text
4 failed, 213 passed in 0.98s
```

The failure set is unchanged:

1. `test_session_review_gives_the_three_repository_glyphs_three_styles`
2. `test_session_review_colors_selection_markers_by_state`
3. `test_session_browser_separates_the_cursor_from_the_expansion_glyph`
4. `test_report_setup_gives_the_generate_action_its_own_colour`

All four compare exact ANSI style sequences. They are the known baseline failures
the brief requires Task 5 to preserve.

Additional verification:

```text
ruff:   All checks passed!
pyright: 0 errors, 0 warnings, 0 informations
git diff --check: clean
```

## Files changed

### `src/iiwi/interactive/render.py`

- Added frozen `OutcomeReviewRow(kind, outcome_id=None)`.
- Added `outcome_review_rows(draft)` with settings, primary outcomes, More candidates,
  ungrouped candidates, Blockers, Next week, Preview, and Generate in the required order.
- Added the Rich `render_outcome_review(...)` renderer.
- Added focused outcome blocks with Status, non-empty Impact, evidence summary, and
  optional repository/session/commit/file details.
- Added visible `User-added` and `Ungrouped` provenance labels.
- Added measured Rich wrapping, explicit `Text.truncate(..., overflow="ellipsis")`,
  fixed chrome reservations, packed hint reservations, scroll indicators, and a
  largest-contiguous-block window containing the focus.
- Added tight-space degradation in the required order: evidence detail first, then
  Impact continuation lines, while retaining the focused summary.
- Reused `_print_viewport_text()` and `_print_hints()`.

### `src/iiwi/interactive/controller.py`

- Connected Task 4's existing `Screen.OUTCOME_REVIEW` render hook to
  `render_outcome_review(...)`.
- Kept the existing Rich repaint architecture, controller event loop, state, targets,
  and key dispatch unchanged.

### `tests/unit/interactive/test_outcome_review_render.py`

- Added row-order and visual hierarchy coverage.
- Added focused versus unfocused display-line behavior.
- Added evidence expansion coverage.
- Added user-added and ungrouped provenance-label coverage.

### `tests/unit/interactive/test_viewport_wrapping_regressions.py`

- Added the required width/height/focus matrix with long rendered content and a long
  status message.
- Asserts terminal height budget, fixed Quick Review identity, visible focus, and
  visible Preview/Generate help at every matrix point.

## Self-review

- Scope: the commit contains exactly the four Task 5 files named in the brief.
- Architecture: no Textual dependency, second event loop, alternate repaint path, or
  change to existing interactive screens was introduced.
- Navigation alignment: renderer visibility follows Task 4's existing section sentinel
  values and target order, including collapsed/open More and Ungrouped sections.
- Display-line correctness: every outcome block is built from the Rich `Text` lines
  actually produced at the current width; the viewport budgets those measured lengths.
- Focus guarantee: the selected window is contiguous and must contain the focused block;
  matrix tests exercise settings, a middle outcome, and the final Generate control.
- Fixed chrome: title, rule, separators, optional message, indicators, and the exact
  packed hint lines are reserved before the content window is selected.
- Degradation: expanded evidence rows are removed before Impact is compacted to its first
  rendered line; title, Status, Impact, and evidence summary remain for focused outcomes
  at the supported 20-row floor.
- Mutation check: removing focused expansion, evidence details, provenance labels,
  truncation/budgeting, cursor inclusion, or any hierarchy/control label causes at least
  one new test to fail.
- Static quality: Ruff, Pyright, and whitespace checks are clean.

## Concerns

- The full interactive pytest command exits non-zero because of the four known baseline
  ANSI-style failures listed above. The failure names and assertion differences are
  unchanged from the pre-Task-5 baseline; Task 5 adds six passing tests and no failures.
- No Task 5 implementation concerns remain.

---

## Review fix round: hard-break budgeting and controller integration

Fix commit: `35609dc` (`fix: constrain quick review hard breaks`).

### Findings addressed

- Important: Outcome titles, Blockers, Next week, and status messages could carry hard
  line breaks through `Text.truncate()`. Rich then emitted additional physical rows that
  were absent from the viewport budget.
- Minor: Tests did not exercise the production controller `_render_screen()` dispatch
  into the Quick Review renderer.

### Root cause

`_truncated_text()` constrains cell width but intentionally preserves the `Text` object's
embedded newline characters. The affected values were each represented as a one-line
block or one-line fixed reservation, so their measured height remained one while Rich
printed every hard break. Impact already follows the correct contrasting pattern: it is
wrapped into rendered lines and every line contributes to the focused block height.

### RED evidence

Exact command:

```bash
env UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_outcome_review_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py -q
```

Exact output:

```text
............F                                                            [100%]
=================================== FAILURES ===================================
____________ test_outcome_review_fits_width_height_and_focus_matrix ____________

    def test_outcome_review_fits_width_height_and_focus_matrix() -> None:
        review = _long_outcome_review()
        rows = render.outcome_review_rows(review)
        focuses = (0, len(rows) // 2, len(rows) - 1)
        expanded = {outcome.id for outcome in review.outcomes}
        error = "Could not refresh review:\n\n\n" + "long-error-detail-" * 20

        for width in (40, 60, 80, 100, 140):
            for height in (20, 24, 30):
                for cursor in focuses:
                    console, stream = _console(width=width, height=height)
                    render.render_outcome_review(
                        console,
                        review,
                        cursor=cursor,
                        expanded_evidence=expanded,
                        message=error,
                    )

                    lines = stream.getvalue().splitlines()
>                   assert len(lines) <= height - 1, (width, height, cursor)
E                   AssertionError: (40, 20, 0)
E                   assert 46 <= (20 - 1)
E                    +  where 46 = len(['Quick Review  12 selected', '════════════════════════════════════════', '', 'Could not refresh review:', '', '', ...])

tests/unit/interactive/test_viewport_wrapping_regressions.py:255: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/interactive/test_viewport_wrapping_regressions.py::test_outcome_review_fits_width_height_and_focus_matrix
1 failed, 12 passed in 0.40s
```

The controller integration assertion passed in this RED run; the viewport matrix failed
for the intended hard-break invariant.

### Fix

- Added `_single_line()` to collapse all hard line separators to spaces for fields whose
  contract is intentionally one physical row.
- Applied it before Rich composition/truncation to outcome titles, Blockers, Next week,
  and optional status messages.
- Added hard breaks to matrix title, Impact, repository, file, Blockers, Next week, and
  message values. Impact remains measured as multiline content; intentionally one-line
  fields are normalized.
- Added a lightweight integration test that constructs `controller._State` on
  `Screen.OUTCOME_REVIEW`, calls the real `_render_screen()`, and asserts Quick Review
  identity, focus, and the focused outcome title.

### GREEN evidence

Exact command:

```bash
env UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/interactive/test_outcome_review_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py -q
```

Exact output:

```text
.............                                                            [100%]
13 passed in 0.46s
```

Full interactive verification:

```text
4 failed, 214 passed in 1.05s
```

The four failures are exactly the pre-existing ANSI-style baseline tests listed earlier
in this report. The fix adds one passing controller integration test and no failures.

Static verification:

```text
ruff: All checks passed!
pyright: 0 errors, 0 warnings, 0 informations
git diff --check: clean
```

### Fix self-review

- The normalization occurs at the source of each one-row render contract, before Rich
  can turn embedded separators into physical lines.
- Impact remains display-line-aware and continues contributing all wrapped lines to the
  focused block budget.
- The terminal matrix still covers every required width, height, and focus combination,
  now with newline-bearing values.
- The controller test exercises the production dispatch path without replacing
  `_render_screen` or mocking the renderer.
- Task 6 recovery routes and unrelated ANSI-style tests are unchanged.
