# Task 2: Deterministic Outcome Synthesis Boundary

## Status

Completed in commit `f33e5b22960d73c7102463e9ed08aa226cfc8671`:

```
feat: synthesize evidence-backed outcomes
```

## RED evidence

The required focused command was run before implementation (with an isolated
UV cache):

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest \
  tests/unit/services/test_outcomes.py \
  tests/unit/summarizers/test_outcome_prompt.py -q
```

It failed at collection as expected because both Task 2 public boundaries were
absent:

- `OutcomeSynthesisError` could not be imported from `iiwi.errors`.
- `iiwi.summarizers.outcome_prompt` did not exist.

An additional evidence-boundary regression was then added after review: a model
payload containing `repository_id` failed because the initial Pydantic schemas
silently ignored the extra field. This confirmed the test guarded a real gap.

## GREEN evidence

After the minimal service, prompt, error, and strict response-schema changes:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest \
  tests/unit/services/test_outcomes.py \
  tests/unit/summarizers/test_outcome_prompt.py -q
```

Result: `12 passed`.

Required extraction regression:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest \
  tests/unit/extraction tests/unit/summarizers/test_opencode_run.py -q
```

Result: `30 passed`.

Additional static verification:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run ruff check \
  src/iiwi/services/outcomes.py src/iiwi/summarizers/outcome_prompt.py \
  src/iiwi/errors.py tests/unit/services/test_outcomes.py \
  tests/unit/summarizers/test_outcome_prompt.py
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pyright src/iiwi/services/outcomes.py
```

Result: Ruff reported all checks passed; Pyright reported `0 errors, 0 warnings,
0 informations`.

## Files changed

- `src/iiwi/services/outcomes.py`
  - Extracts and redacts evidence per session.
  - Calls the runner with indented JSON evidence and the fixed outcome prompt.
  - Strictly validates model JSON and reconstructs `EvidenceRef` values only
    from known session evidence.
  - Rejects unknown sessions and model-supplied repository references.
  - Applies deterministic IDs, merge confidence rules, primary/more ranking,
    and ungrouped extraction-failure candidates.
- `src/iiwi/summarizers/outcome_prompt.py`
  - Defines the constrained JSON response contract and evidence-first rules.
- `src/iiwi/errors.py`
  - Adds `OutcomeSynthesisError(IiwiError)`.
- `tests/unit/services/test_outcomes.py`
  - Covers the required ranking, cross-repository merge/split, unknown-session,
    impact, partial extraction-failure, and invalid-output behavior, plus strict
    rejection of model-supplied repository references.
- `tests/unit/summarizers/test_outcome_prompt.py`
  - Covers the response keys, ranking target, impact rule, unknown-session rule,
    and merge signals.

## Self-review

Reviewed the staged five-file diff and ran `git diff --cached --check` before
committing. Confirmed:

- No Task 1 model or report/TUI/controller file was modified.
- Model output has no usable repository, file, commit, or activity-reference
  fields; unknown or extra reference data is rejected.
- Cross-repository merging requires high confidence plus `shared_work_id`, or
  both distinct `branch_or_issue` and `direct_reference` signals.
- Unsupported merges are split by repository in model proposal order.
- Failed extraction is partial: successful proposals remain available and each
  failed session is returned as an `UNGROUPED` candidate with only its known
  session/repository reference.
- The extraction regression suite remains green, preserving conservative
  extraction behavior.

## Concerns

None.

## P1 review fix: blank linkage values cannot authorize a merge

Commit: `e1c35bd0c469945448a645904f02d02a4b5ddfac`
(`fix: reject blank outcome linkage signals`).

### Root cause

`_may_merge_cross_repository()` reduced every linkage signal to its `kind` and
therefore treated an empty or whitespace-only `value` as a valid
`shared_work_id`, `branch_or_issue`, or `direct_reference` signal.

### RED evidence

Added a parameterized regression covering an empty `shared_work_id`, a
whitespace-only `shared_work_id`, and a blank value for each member of the
two-signal allowed pair. Before the fix, all four proposals merged two
repositories into one outcome.

Exact command:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py -q
```

Exact result:

```text
.....FFFF.....                                                           [100%]
4 failed, 10 passed in 0.11s
```

### Fix

The merge predicate now includes a linkage kind only when its value remains
non-empty after `strip()`. Blank signals are ignored, so neither an empty
`shared_work_id` nor an incomplete allowed pair can authorize a
cross-repository merge; the proposal is deterministically split by repository.

### GREEN evidence

Exact covering command:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run pytest tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py -q
```

Exact output:

```text
................                                                         [100%]
16 passed in 0.09s
```

Additional check:

```bash
UV_CACHE_DIR=/tmp/iiwi-uv-cache uv run ruff check src/iiwi/services/outcomes.py tests/unit/services/test_outcomes.py
```

Output:

```text
All checks passed!
```

### Self-review

Reviewed the two-file diff with `git diff --check` and the staged diff with
`git diff --cached --check`. The change filters only merge authorization; it
does not alter proposal parsing, evidence reconstruction, ranking, or any
later-task file.
