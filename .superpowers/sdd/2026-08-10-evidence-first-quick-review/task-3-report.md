# Task 3 Report: Reviewed Report Rendering and Detail Parity

## Status

DONE

## RED evidence

1. `uv run pytest tests/unit/renderers/test_outcome_markdown.py tests/unit/renderers/test_narrative.py -q`
   initially could not start because this environment's default `/root/.cache/uv`
   is read-only.
2. The same command with `UV_CACHE_DIR=/tmp/iiwi-uv-cache` failed as expected:
   7 failed, 4 passed. The failures were the missing
   `MarkdownRenderer.render_outcomes()` method, missing `WorklogReport` reviewed
   fields, and missing `render_narrative(..., detail=...)` parameter.
3. `uv run pytest tests/unit/summarizers/test_opencode_run.py -q` with the
   writable cache failed as expected: `build_summary_prompt()` did not accept
   `detail`.

## GREEN evidence

1. Renderer, narrative, and prompt tests: 19 passed.
2. Reviewed service integration tests: 21 passed.
3. Final required report suite:

   ```text
   uv run pytest tests/unit/renderers tests/unit/summarizers/test_opencode_run.py tests/integration/test_report_service.py -q
   61 passed in 1.55s
   ```

4. `git diff --check`: passed.
5. Ruff on all Task 3 source and test files: passed.
6. Pyright on changed production modules: 0 errors, 0 warnings, 0 informations.

## Files changed

- `src/iiwi/models/report.py`
- `src/iiwi/renderers/markdown.py`
- `src/iiwi/templates/outcomes.md.j2`
- `src/iiwi/services/report.py`
- `src/iiwi/summarizers/opencode_run.py`
- `tests/unit/renderers/test_outcome_markdown.py`
- `tests/unit/renderers/test_narrative.py`
- `tests/unit/summarizers/test_opencode_run.py`
- `tests/integration/test_report_service.py`

## Self-review

- The reviewed path uses a deep copy of `OutcomeReviewDraft`, redacts all
  draft values before constructing the report, and does not invoke repository
  synthesis.
- `generate_reviewed()` follows existing conflict, dry-run, progress, secure
  write, warning, and `ScanResult` return behavior. It collects Usage only for
  Full review detail.
- The new template filters excluded outcomes, separates completed and
  in-progress statuses, only emits non-empty Impact, identifies user-added
  outcomes, and groups Full-detail evidence by repository while conditionally
  rendering commit and file fields.
- The existing repository template and renderer were not altered. Narrative
  detail now reaches both the OpenCode prompt and the wrapper renderer.
- Tests cover report type headings, optional section omission, Brief evidence
  suppression, Full evidence grouping, user edit preservation, redaction,
  output conflicts, dry runs, usage gating, and narrative prompt/wrapper parity.

## Concerns

None for the implementation. The default uv cache is read-only in this
environment, so verification used `UV_CACHE_DIR=/tmp/iiwi-uv-cache`.

## Follow-up Fix: Brief Narrative Usage Gating

### Finding and root cause

Brief narrative rendering already suppressed the Usage section, and the Brief
prompt already prohibited Usage. However, `_narrative_report()` still called
`_collect_usage()` unconditionally and retained the resulting `usage_text` on
the `WorklogReport`. The reviewed path correctly conditioned collection on
`DetailLevel.FULL`; narrative generation lacked that equivalent service-layer
gate.

### RED evidence

After extending `test_narrative_brief_detail_changes_the_prompt_and_wrapper`
to record provider calls and assert `result.report.usage_text is None`, the
focused command failed as expected:

```text
task_uv_cache=/tmp/iiwi-uv-cache UV_CACHE_DIR="$task_uv_cache" uv run pytest tests/integration/test_report_service.py::test_narrative_brief_detail_changes_the_prompt_and_wrapper -q
1 failed in 0.14s
AssertionError: assert 'gpt-5-mini  1234 tokens' is None
```

### Fix and GREEN evidence

Changed only `_narrative_report()` to call `_collect_usage()` when
`self._detail is DetailLevel.FULL`; structured repository reports and the
reviewed path remain unchanged. The covering test now verifies both that Brief
narrative results have no `usage_text` and that the provider is never called.

Focused regression command/output:

```text
task_uv_cache=/tmp/iiwi-uv-cache UV_CACHE_DIR="$task_uv_cache" uv run pytest tests/integration/test_report_service.py::test_narrative_brief_detail_changes_the_prompt_and_wrapper -q
1 passed in 0.11s
```

Exact covering command/output:

```text
task_uv_cache=/tmp/iiwi-uv-cache UV_CACHE_DIR="$task_uv_cache" uv run pytest tests/unit/renderers tests/unit/summarizers/test_opencode_run.py tests/integration/test_report_service.py -q
61 passed in 0.70s
```

### Fix commit

`fefe69c fix: skip usage collection for brief narratives`
