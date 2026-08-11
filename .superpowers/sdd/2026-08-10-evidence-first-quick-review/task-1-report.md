# Task 1: Outcome and Review-Draft Domain Model

## Status

DONE

## Commit

`d7e2c4567db357b74009881c1a39c47886c23037 feat: add outcome review domain model`

## Implementation

- Added shared `DetailLevel` and `ReportType` enums in `iiwi.models.report_options`.
- Added outcome, evidence-reference, source-group, synthesis-result, and mutable review-draft models.
- Enforced evidence for synthesized outcomes and preserved source evidence when splitting merged outcomes.
- Added outcome review mutations for inclusion, ordering, editing, splitting, user-added outcomes, report type, and explicit detail selection.
- Re-exported `DetailLevel` from `iiwi.renderers.markdown` and migrated the interactive draft to the shared options model.
- Added `ReportDraft.report_type`, `ReportDraft.detail_overridden`, type/detail mutation rules, and `Screen.OUTCOME_REVIEW`.

## RED evidence

The exact required focused command was first run:

```text
uv run pytest tests/unit/models/test_outcome.py tests/unit/interactive/test_models.py -q
```

It could not initialize because this execution environment mounts `/root/.cache/uv` read-only. Re-running the same command with `UV_CACHE_DIR=/tmp/iiwi-uv-cache` reached collection and failed as intended before implementation:

```text
ModuleNotFoundError: No module named 'iiwi.models.outcome'
ModuleNotFoundError: No module named 'iiwi.models.report_options'
```

## GREEN evidence

```text
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/models/test_outcome.py tests/unit/interactive/test_models.py -q
12 passed in 0.11s
```

Additional focused quality checks:

```text
git diff --check
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run ruff check <seven task files>
All checks passed!
```

## Files changed

- `src/iiwi/models/report_options.py`
- `src/iiwi/models/outcome.py`
- `src/iiwi/models/__init__.py`
- `src/iiwi/renderers/markdown.py`
- `src/iiwi/interactive/models.py`
- `tests/unit/models/test_outcome.py`
- `tests/unit/interactive/test_models.py`

## Self-review

- Confirmed the change is limited to the brief's seven task files.
- Confirmed existing `from iiwi.renderers.markdown import DetailLevel` imports remain valid.
- Confirmed synthesized outcomes reject missing evidence while user-added outcomes carry no invented evidence.
- Confirmed move rank normalization preserves every candidate and source-group splitting creates stable child ids while retaining group evidence.
- Confirmed no persistence or later synthesis/rendering/TUI task behavior was added.

## Concerns

The default uv cache path is read-only in this environment, so verification used the writable temporary cache override shown above. There are no implementation concerns.

---

## Review Fix Report

### Commit

`cb7b608285d5a4f8e9092395120572d04c78340a fix: preserve review draft detail selections`

### Findings resolved

- P1: Constructor-supplied `DetailLevel` now marks both review-draft types as explicitly overridden. `set_report_type()` therefore retains a supplied detail, while omitted detail continues to use the Manager/Engineering default.
- P2: `OutcomeReviewDraft.split()` now raises `ValueError("cannot split outcome without source groups")` before mutating the outcome list, preserving ungrouped or malformed candidates.

### Regression coverage

- `ReportDraft(detail=DetailLevel.BRIEF)` followed by `set_report_type(ReportType.ENGINEERING)` retains brief detail and marks the override.
- `OutcomeReviewDraft(detail=DetailLevel.FULL)` followed by `set_report_type(ReportType.MANAGER)` retains full detail and marks the override.
- Splitting an outcome with no source groups raises the clear error and leaves the parent intact.

### RED evidence

Before the production fix, the new focused regressions failed as expected:

```text
3 failed, 12 passed in 0.12s
```

The failures showed both constructor-provided details being replaced by `set_report_type()` and `split()` not raising for an empty source-group list.

### GREEN evidence

Exact covering focused command and output:

```text
$ UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/models/test_outcome.py tests/unit/interactive/test_models.py -q
...............                                                          [100%]
15 passed in 2.59s
```

Focused Ruff and whitespace checks also passed:

```text
All checks passed!
```

### Self-review

- Confirmed the ReportDraft sentinel distinguishes an omitted detail from either explicitly supplied enum value without changing default Manager/Engineering behavior.
- Confirmed the Pydantic draft uses `model_fields_set`, so only a supplied non-null detail becomes an override.
- Confirmed the split guard runs before slice replacement, preventing data loss.
- Confirmed no later-task files were modified.

### Concerns

None beyond the pre-existing writable uv cache override required by this environment.
