# Keyboard Semantics and Exclusion Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `q` mean "back one level" on every interactive screen (matching `b`, except the main menu where it quits), and make the review screen's `e` (exclude repository) filter the current scan in memory instead of rescanning the disk.

**Architecture:** Two independent changes to `src/iiwi/interactive/controller.py` and `src/iiwi/interactive/selection.py`. The exclusion change adds a pure helper `without_repository(scan, repository_id) -> ScanResult` to `selection.py` (mirroring the existing `SelectionState.filtered_scan`), a `SelectionState.exclude_repository` method, and rewires the controller's `e` branch to use it. The `q` change merges the `q` key handler into the existing `b`/`Esc` handler on each screen so both keys share one code path.

**Tech Stack:** Python 3.11+, Typer/Rich TUI, pytest, ruff, pyright. No new dependencies.

## Global Constraints

- Python >= 3.11; keep type annotations as in the surrounding code.
- Line length 100 (`ruff`); ruff lint select `E,F,I,UP,B,SIM` must pass on `src` and `tests`.
- pyright `standard` mode must report 0 errors.
- No new dependencies.
- Run everything with `uv run --extra dev ...`.
- Commit messages use the repo's conventional style (`refactor:`, `fix:`, `feat:`, `docs:`, `test:`).
- Design doc: `docs/2026-08-13-keyboard-semantics-and-exclusion-filter-design.md` (already committed).

---

### Task 1: `without_repository` pure helper

**Files:**
- Modify: `src/iiwi/interactive/selection.py` (add function near `filtered_scan`; import `ScanResult` is already imported)
- Test: `tests/unit/interactive/test_selection.py`

**Interfaces:**
- Produces: `without_repository(scan: ScanResult, repository_id: str) -> ScanResult` — a new `ScanResult` with the repository's sessions removed from both `resolved_sessions` and `sessions_by_repository`; `loaded_session_count` shrinks by the removed count; `period`, `candidate_session_count`, `failed_session_count`, `warnings`, `excluded_session_count` carry over unchanged. Raises `KeyError` for an unknown `repository_id` (same convention as `SelectionState._repository_session_ids`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/interactive/test_selection.py`. The file already has `_scan()` (repo-a × 2 sessions, repo-b × 1 session, `candidate_session_count=5`, `failed_session_count=2`, `warnings=["one warning"]`, `excluded_session_count=2`) — reuse it. Add `without_repository` to the existing import on line 8:

```python
from iiwi.interactive.selection import SelectionMark, SelectionState, noise_reason, without_repository
```

```python
def test_without_repository_removes_only_that_repository() -> None:
    filtered = without_repository(_scan(), "repo-a")
    assert "repo-a" not in filtered.sessions_by_repository
    assert "repo-b" in filtered.sessions_by_repository
    assert all(item.session.session_id != "ses-a1" for item in filtered.resolved_sessions)
    assert all(item.session.session_id != "ses-a2" for item in filtered.resolved_sessions)
    assert filtered.loaded_session_count == 1


def test_without_repository_keeps_scan_metadata() -> None:
    scan = _scan()
    filtered = without_repository(scan, "repo-a")
    assert filtered.period is scan.period
    assert filtered.candidate_session_count == 5
    assert filtered.failed_session_count == 2
    assert filtered.excluded_session_count == 2
    assert filtered.warnings == ["one warning"]


def test_without_repository_unknown_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        without_repository(_scan(), "repo-nope")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/interactive/test_selection.py -q`
Expected: FAIL with `ImportError`/`NameError` for `without_repository` (and the missing builder).

- [ ] **Step 3: Implement `without_repository`**

Add to `src/iiwi/interactive/selection.py` (above `SelectionState`, near the other helpers):

```python
def without_repository(scan: ScanResult, repository_id: str) -> ScanResult:
    """Return a scan with one repository's sessions removed, metadata intact.

    The in-memory exclusion keeps the current view honest without re-reading
    the disk; the persisted configuration still applies to future scans.
    """

    try:
        removed = scan.sessions_by_repository[repository_id]
    except KeyError:
        raise KeyError(repository_id) from None
    removed_ids = {item.session.session_id for item in removed}
    return ScanResult(
        period=scan.period,
        candidate_session_count=scan.candidate_session_count,
        loaded_session_count=scan.loaded_session_count - len(removed_ids),
        failed_session_count=scan.failed_session_count,
        resolved_sessions=[
            item
            for item in scan.resolved_sessions
            if item.session.session_id not in removed_ids
        ],
        sessions_by_repository={
            key: value
            for key, value in scan.sessions_by_repository.items()
            if key != repository_id
        },
        warnings=list(scan.warnings),
        excluded_session_count=scan.excluded_session_count,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/interactive/test_selection.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run --extra dev ruff check src tests
git add src/iiwi/interactive/selection.py tests/unit/interactive/test_selection.py
git commit -m "feat: add in-memory scan exclusion helper"
```

---

### Task 2: `SelectionState.exclude_repository`

**Files:**
- Modify: `src/iiwi/interactive/selection.py` (inside `SelectionState`)
- Test: `tests/unit/interactive/test_selection.py`

**Interfaces:**
- Consumes: `without_repository(scan, repository_id) -> ScanResult` (Task 1).
- Produces: `SelectionState.exclude_repository(repository_id: str) -> None` — replaces `self.scan` with the filtered scan and removes the repository's session ids from `self.selected_session_ids`. Unknown id raises `KeyError`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/interactive/test_selection.py`:

```python
def test_exclude_repository_prunes_scan_and_selection() -> None:
    state = SelectionState.from_scan(_scan())
    state.exclude_repository("repo-a")
    assert "repo-a" not in state.scan.sessions_by_repository
    assert state.total_count == 1
    assert state.selected_count == 1
    assert state.selected_session_ids == {"ses-b1"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/unit/interactive/test_selection.py::test_exclude_repository_prunes_scan_and_selection -q`
Expected: FAIL with `AttributeError: 'SelectionState' object has no attribute 'exclude_repository'`.

- [ ] **Step 3: Implement**

Add to `SelectionState` (next to `toggle_repository`):

```python
    def exclude_repository(self, repository_id: str) -> None:
        removed = {
            item.session.session_id
            for item in self.scan.sessions_by_repository[repository_id]
        }
        self.scan = without_repository(self.scan, repository_id)
        self.selected_session_ids.difference_update(removed)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/unit/interactive/test_selection.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run --extra dev ruff check src tests
git add src/iiwi/interactive/selection.py tests/unit/interactive/test_selection.py
git commit -m "feat: prune the selection when excluding a repository"
```

---

### Task 3: `e` on the review screen filters in memory

**Files:**
- Modify: `src/iiwi/interactive/controller.py:722-742` (the `_review_key` `e` branch)
- Modify: `tests/unit/interactive/test_selection_memory.py:307-321` (`test_exclude_key_on_a_repository_row_excludes_and_rescans`)
- Test: `tests/unit/interactive/test_selection_memory.py`

**Interfaces:**
- Consumes: `SelectionState.exclude_repository(repository_id)` (Task 2).
- Behavior: after `actions.exclude_repository` succeeds, the repository vanishes from the current review WITHOUT a new scan; `review_message` shows the returned message; the cursor stays valid; a cached Quick Review is cleared (so stale evidence cannot survive). `R` rescan keeps its full re-read.

- [ ] **Step 1: Write the failing test**

Replace the body of `test_exclude_key_on_a_repository_row_excludes_and_rescans` in `tests/unit/interactive/test_selection_memory.py`:

```python
def test_exclude_key_on_a_repository_row_excludes_without_rescan() -> None:
    recorder = Recorder()
    console, stream = _console()

    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [char("2"), char("r"), char("e"), char("b"), char("b"), char("q")]
        ),
        console=console,
    )

    assert recorder.exclude_calls == [("repo-a", "repo-a")]
    assert recorder.scan_calls == 1
    assert "future scans will skip it" in stream.getvalue()
```

(The key sequence: `2` Generate Report, `r` Review, `e` exclude on the repository row, `b` to setup, `b` to main, `q` quit. The old sequence `[..., "b", "b", "q", "q"]` also still works — both end at EXIT — but the shorter one pins the new semantics.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/unit/interactive/test_selection_memory.py::test_exclude_key_on_a_repository_row_excludes_without_rescan -q`
Expected: FAIL — `assert recorder.scan_calls == 1` fails because the current code rescans (`scan_calls == 2`).

- [ ] **Step 3: Implement**

In `_review_key` (`src/iiwi/interactive/controller.py`), replace the `_rescan_review(state, actions)` call in the `e` branch (currently lines 739-741):

```python
            state.selection.exclude_repository(row.repository_id)
            state.draft.scan = state.selection.scan
            _clear_outcome_review(state)
            _sync_selection(state, actions)
            rows = _tree_rows(state.selection.scan, state)
            state.review_cursor = min(
                state.review_cursor, max(0, len(rows) - 1)
            )
            state.review_message = message
```

Note: `state.draft.scan = state.selection.scan` keeps the draft and the selection on the same filtered scan, so re-entering review from setup (`_review`) does not resurrect the excluded repository.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/interactive/test_selection_memory.py -q`
Expected: PASS (the renamed test and the untouched `test_exclude_key_on_a_session_row_does_not_exclude`).

- [ ] **Step 5: Full suite + lint + commit**

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_selection_memory.py
git commit -m "fix: exclude a repository from the review without rescanning"
```

---

### Task 4: `q` means back on every screen

**Files:**
- Modify: `src/iiwi/interactive/controller.py` (six key handlers)
- Modify: `src/iiwi/interactive/render.py` (help line + result-screen hint)
- Modify: tests with `q`-driven sequences (audit list in Step 5)
- Test: `tests/unit/interactive/test_controller.py`, `tests/unit/interactive/test_outcome_review_controller.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: the `q` key behaves exactly like `b`/`Esc` on every screen; the main menu `q`/`Esc` still exits.

- [ ] **Step 1: Implement the six handler changes**

In `src/iiwi/interactive/controller.py`:

1. `_review_key` — merge `q` into the existing back branch (keep the ESC-clears-search branch above it, currently lines 687-689):

```python
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        _sync_selection(state, actions)
        state.screen = Screen.MAIN if state.review_from_main else Screen.REPORT_SETUP
        return
```

   Delete the old standalone `q` branch (currently lines 683-686).

2. `_outcome_review_key` — the existing `q` branch (currently `state.screen = Screen.MAIN`) becomes `state.screen = Screen.SESSION_REVIEW`; delete the old `b`/`Esc` branch below it:

```python
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.SESSION_REVIEW
        return
```

3. `_preview_key` — merge `q` into the existing `b` branch:

```python
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = state.preview_return_screen or Screen.REPORT_RESULT
        state.preview_return_screen = None
        return
```

4. `_session_preview_key` — merge `q` into the existing `b` branch, and clear `preview_return_screen` on the way out (the design makes `q` and `b` identical here):

```python
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = state.preview_return_screen or Screen.MAIN
        state.preview_return_screen = None
        return
```

5. `_help_key` — merge `q` into the existing return branch:

```python
    if _char(key, "q") or key.key in {Key.ESCAPE, Key.ENTER} or _char(key, "b") or _exact_char(key, "?"):
        state.screen = state.help_return_screen or Screen.MAIN
        state.help_return_screen = None
        return
```

6. `_error_key` — merge `q` into the existing `b` branch (the error screen keeps its explicit "Main menu" option):

```python
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = _error_back_screen(error)
        return
```

In `src/iiwi/interactive/render.py`:

7. `_HELP_LINES` — `"q              Main menu / quit from main menu"` becomes `"q              Back / quit from the main menu"`.

8. `render_report_result` hints — `"q Menu"` becomes `"q Back"` (the list at the bottom of that function; main menu's `"q Quit"` stays).

- [ ] **Step 2: Add tests for the new `q` destinations**

Append to `tests/unit/interactive/test_controller.py` (reuse the file's `char`, `ScriptedInput`, `_actions`, `_console` helpers; `_open_review_keys`-style helpers already exist in `test_outcome_review_controller.py` if needed):

```python
def test_q_on_quick_review_returns_to_review_screen() -> None:
    console, stream = _console()
    keys = ScriptedInput(
        [
            char("2"),
            char("g"),
            char("q"),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(),
        input_source=keys,
        console=console,
    )

    assert "Review Sessions" in stream.getvalue()


def test_q_on_session_preview_returns_to_review_screen() -> None:
    console, stream = _console()
    keys = ScriptedInput(
        [
            char("2"),
            char("r"),
            KeyPress(key=Key.RIGHT),
            char("p"),
            char("q"),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(),
        input_source=keys,
        console=console,
    )

    assert "Review Sessions" in stream.getvalue()


def test_q_on_report_preview_returns_to_quick_review() -> None:
    console, stream = _console()
    keys = ScriptedInput(
        [
            char("2"),
            char("g"),
            char("p"),
            char("q"),
            char("q"),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(),
        input_source=keys,
        console=console,
    )

    assert "Quick Review" in stream.getvalue()
```

If `_actions()` in `test_controller.py` does not already wire `synthesize`/`generate_reviewed`, copy the wiring from `test_interactive_regressions.py:122-170` (the `_actions` builder with `_synthesized_outcomes()`).

- [ ] **Step 3: Run the new tests**

Run: `uv run --extra dev pytest tests/unit/interactive/test_controller.py -k "q_on" -q`
Expected: PASS. If a sequence does not reach its screen (e.g. `g` needs a scan first), adjust the keys using the existing tests in `test_outcome_review_controller.py` as reference — do not weaken the assertions.

- [ ] **Step 4: Audit and fix every existing `q`-driven test sequence**

The semantic rule: `q` now means the same as `b` on the screen it is pressed on; only on MAIN does `q` exit. Run the suite and fix every failure:

```bash
uv run --extra dev pytest -q
```

For each failing test, trace the key sequence (a sequence that used `..., q, q` to reach EXIT from a child screen now stops one level up — extend it with `b`/`q` presses so it reaches EXIT, or change intermediate `q`s to `b` where the test only meant "leave this screen"). Known spots to check first:

- `tests/unit/interactive/test_outcome_review_controller.py:519` (`[..., j, e, b, q, q]`)
- `tests/unit/interactive/test_controller.py:201` (the review-from-main `q` sequence — unchanged behavior, verify only)
- Any sequence ending in `q` right after `p` (preview) or `g` (Quick Review) or `?` (help)
- `tests/unit/interactive/test_interactive_regressions.py` — `?`-help sequences end `?, b, q` (unchanged), verify only

Do NOT weaken assertions to make tests pass; change only the key sequences (and test names if the old name describes the old `q` behavior).

- [ ] **Step 5: Full verification**

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
uv run --extra dev pyright
```

All must pass (883 tests + new ones).

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/interactive/controller.py src/iiwi/interactive/render.py tests/unit/interactive/
git commit -m "fix: make q go back one level on every screen"
```

---

## Out of scope

- History view (PR #96, design only).
- Report-type cycling and setup label changes (separate design).
- `R` rescan stays a full disk re-read by design.
