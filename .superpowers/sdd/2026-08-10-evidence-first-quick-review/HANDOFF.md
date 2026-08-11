# Evidence-first Quick Review handoff

## Repository state

- Branch: `feat/evidence-first-quick-review`
- Base: `2a85f797e450e9213ca2de52d3a9084eb1103681`
- Product HEAD before this artifact-only handoff commit: `89e447577a28c61b596a90c808555450423a1ebd`
- Product status: `BLOCKED`; do not open or merge a pull request yet.
- Working implementation and all earlier task commits are intentionally preserved.

Read these files in order when resuming:

1. `design.md`
2. `implementation-plan.md`
3. `progress.md`
4. `final-review-findings.md`
5. `second-wave-plan.md`
6. `second-wave-fix-report.md`
7. This handoff

The `task-*-brief.md`, `task-*-report.md`, and `review-*.diff` files retain the detailed implementation and review history.

## Remaining load-bearing failure

The second-wave scoped review passed three of four residual findings and found no new Critical or Important issue. One Important finding remains in `src/iiwi/renderers/markdown.py::_brief_narrative_body`:

1. Heading detection understands only ATX headings beginning with `#`. Setext headings such as the following are treated as ordinary prose, so content in an unexpected technical section can pass through Brief output:

   ```markdown
   Deployment Trace
   ----------------
   Internal deployment evidence.
   ```

2. Evidence-line filtering requires a colon after evidence keys. Technical lines such as these can pass through:

   ```text
   Commit deadbeef
   Branch feature/internal-rollout
   ```

This violates the deterministic Brief evidence-depth boundary. The branch must remain blocked until both forms are rejected without removing safe, unheaded reader-facing summaries.

## Expected third-wave repair

Use test-driven development and keep the change scoped to the Brief narrative boundary.

Add RED coverage in `tests/unit/renderers/test_narrative.py` for:

- an unexpected setext technical heading and its body;
- allowed setext reader-facing headings, if setext syntax is supported generally;
- `Commit deadbeef` without a colon;
- `Branch feature/internal-rollout` without a colon;
- preservation of the existing plain safe summary behavior.

Then update `_brief_narrative_body` so that:

- ATX and setext headings share the same allowlist semantics;
- evidence labels are rejected with either a colon or whitespace delimiter;
- fenced code and existing technical evidence filters remain enforced;
- Full narrative rendering is unchanged.

Run a fresh scoped review after the tests are green. Do not rely only on the existing second-wave report.

## Last fresh verification

- Focused suite: `70 passed`
- Ruff: passed
- Pyright: passed with zero errors and warnings
- Diff check: passed
- Full suite: `779 passed, 5 failed, 4 skipped`

The five failures were present at the branch baseline:

1. `tests/unit/interactive/test_render.py::test_session_review_gives_the_three_repository_glyphs_three_styles`
2. `tests/unit/interactive/test_render.py::test_session_review_colors_selection_markers_by_state`
3. `tests/unit/interactive/test_render.py::test_session_browser_separates_the_cursor_from_the_expansion_glyph`
4. `tests/unit/interactive/test_render.py::test_report_setup_gives_the_generate_action_its_own_colour`
5. `tests/unit/test_logging.py::test_settings_table_shows_values_sources_and_defaults`

## Suggested resume commands

```bash
git switch feat/evidence-first-quick-review
git status --short --branch
sed -n '1,260p' .superpowers/sdd/2026-08-10-evidence-first-quick-review/HANDOFF.md
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/renderers/test_narrative.py -q
```

After the third-wave repair, rerun the focused suite, Ruff, Pyright, `git diff --check`, and the full suite before requesting final review.
