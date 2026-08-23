# Interactive Menu Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three UX bugs in the interactive menu: `?` key hijacking text input modes, wrong back-screen after repository-exclusion failure, and `g`/`G` key semantic conflicts across screens.

**Architecture:** Three targeted changes to `src/iiwi/interactive/controller.py` and one to `src/iiwi/interactive/render.py`. Each fix is independent and testable in isolation. No new files or modules needed.

**Tech Stack:** Python 3.12, pytest, Rich terminal rendering.

**Spec:** Derived from the interactive-menu flow analysis (this session's findings).

## Global Constraints

- Python 3.12+, StrEnum for enums
- Tests use `ScriptedInput`, `char()`, `_console()` helpers already defined in test files
- All tests must pass with `pytest tests/unit/interactive/ -v`

---

### Task 1: Fix `?` key hijacking search input

**Files:**
- Modify: `src/iiwi/interactive/controller.py:1991` (`_dispatch`)
- Test: `tests/unit/interactive/test_controller.py`

**Interfaces:**
- Consumes: `state.searching` (bool), `_exact_char(key, "?")`, `_dispatch(state, key, actions, console)`
- Produces: No new interfaces; modifies existing guard condition only

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/interactive/test_controller.py`:

```python
def test_question_mark_types_into_search_input() -> None:
    stream = StringIO()
    console = Console(
        file=stream, color_system=None, force_terminal=False, width=100,
    )
    input_source = ScriptedInput(
        [
            char("3"),
            char("r"),
            char("/"),
            char("?"),
            char("0"),
            KeyPress(key=Key.ENTER),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(scan_callback=_setup_populated_scan),
        input_source=input_source,
        console=console,
    )

    text = stream.getvalue()
    assert "Search: ?0" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/interactive/test_controller.py::test_question_mark_types_into_search_input -v`
Expected: FAIL — `"Search: ?0"` not found because the current code opens Help instead of typing into the search field.

- [ ] **Step 3: Write minimal implementation**

In `src/iiwi/interactive/controller.py`, change line 1991 from:

```python
if _exact_char(key, "?") and state.screen is not Screen.HELP:
    _open_help(state)
    return
```

to:

```python
if (
    _exact_char(key, "?")
    and state.screen is not Screen.HELP
    and not state.searching
):
    _open_help(state)
    return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/interactive/test_controller.py::test_question_mark_types_into_search_input -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_controller.py
git commit -m "fix: allow ? to type into search input"
```

---

### Task 2: Fix `?` key hijacking settings inline editor

**Files:**
- Modify: `src/iiwi/interactive/controller.py:1991` (`_dispatch`)
- Test: `tests/unit/interactive/test_settings_controller.py`

**Interfaces:**
- Consumes: `state.settings_editing` (bool), same guard as Task 1
- Produces: Combined guard condition on the `?` interception

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/interactive/test_settings_controller.py`:

```python
def test_question_mark_types_into_inline_editor() -> None:
    stream = StringIO()
    console = Console(
        file=stream, color_system=None, force_terminal=False, width=110,
    )
    state = _State(screen=Screen.SETTINGS)
    state.settings_rows = build_settings_rows()
    state.settings_cursor = next(
        index
        for index, row in enumerate(state.settings_rows)
        if row.editable and not row.locked
    )
    state.settings_editing = True
    state.settings_edit_value = ""

    question_key = KeyPress(char="?")
    controller._dispatch(state, question_key, _actions(), console)

    assert state.screen is Screen.SETTINGS
    assert "?" in state.settings_edit_value
```

Note: import `controller` at the top of the file if not already imported:
`from iiwi.interactive import controller`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/interactive/test_settings_controller.py::test_question_mark_types_into_inline_editor -v`
Expected: FAIL — screen becomes HELP because the current code intercepts `?` before `_settings_edit_key` sees it.

- [ ] **Step 3: Update the guard from Task 1**

Change the guard added in Task 1 from:

```python
if (
    _exact_char(key, "?")
    and state.screen is not Screen.HELP
    and not state.searching
):
    _open_help(state)
    return
```

to:

```python
if (
    _exact_char(key, "?")
    and state.screen is not Screen.HELP
    and not state.searching
    and not state.settings_editing
):
    _open_help(state)
    return
```

- [ ] **Step 4: Run both Task 1 and Task 2 tests**

Run: `pytest tests/unit/interactive/test_controller.py::test_question_mark_types_into_search_input tests/unit/interactive/test_settings_controller.py::test_question_mark_types_into_inline_editor -v`
Expected: Both PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_settings_controller.py
git commit -m "fix: allow ? in settings inline editor"
```

---

### Task 3: Fix error-back-screen routing for repository-exclusion failure

**Files:**
- Modify: `src/iiwi/interactive/controller.py:930-936` (`_review_key` exclude-repository arm), `src/iiwi/interactive/controller.py:1553-1570` (`_error_back_screen`)
- Test: `tests/unit/interactive/test_review_regressions.py`

**Interfaces:**
- Consumes: `_ErrorState.kind` (string), `_error_back_screen(error)` → `Screen`
- Produces: New kind value `"exclude-source"` that routes back to `SESSION_REVIEW`; no function signature changes

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/interactive/test_review_regressions.py`:

```python
def test_exclude_failure_returns_to_session_review() -> None:
    stream = StringIO()
    console = Console(
        file=stream, color_system=None, force_terminal=False, width=110,
    )
    counters: dict[str, int] = {}
    actions = _actions(
        scan_callback=_setup_populated_scan,
        counters=counters,
        exclude_callback=None,
    )
    input_source = ScriptedInput(
        [
            char("3"),
            char("r"),
            char("e"),
            char("b"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=actions,
        input_source=input_source,
        console=console,
    )

    assert "Could not exclude repository" in stream.getvalue()
    # After pressing b from the error, we should be on Session Review, not Report Setup.
    assert "Review Sessions" in stream.getvalue()
```

This requires updating `_actions()` in `test_review_regressions.py` to accept an `exclude_callback` parameter. If the helper does not have one, add it:

```python
def _actions(*, scan_callback=None, counters=None, exclude_callback=None) -> InteractiveActions:
    ...
    def exclude_repository(repository_id: str, display_name: str) -> str:
        if exclude_callback is None:
            raise IiwiError("exclusion failed")
        return exclude_callback(repository_id, display_name)
    ...
```

Import `IiwiError` from `iiwi.errors`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/interactive/test_review_regressions.py::test_exclude_failure_returns_to_session_review -v`
Expected: FAIL — after pressing `b` from the error screen, the rendered output shows "Generate Report" (Report Setup) instead of "Review Sessions" (Session Review), because `_error_back_screen("report-source")` returns `REPORT_SETUP`.

- [ ] **Step 3: Change the kind and add a routing arm**

In `src/iiwi/interactive/controller.py`, change line 936 from:

```python
                    kind="report-source",
```

to:

```python
                    kind="exclude-source",
```

In `_error_back_screen` (line 1553), add before the `startswith("report")` fallback:

```python
    if error.kind == "exclude-source":
        return Screen.SESSION_REVIEW
```

In `_error_options` (line ~1520), add an entry for the new kind so Back appears:

```python
    if error.kind == "exclude-source":
        return ["Back"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/interactive/test_review_regressions.py::test_exclude_failure_returns_to_session_review -v`
Expected: PASS

- [ ] **Step 5: Verify no other tests reference `report-source` in the exclusion path**

Run: `rg -n "report-source" src/iiwi/interactive/controller.py`
Expected: Only line 450 (the `_load_activity` source-read failure), which correctly returns REPORT_SETUP via the `startswith("report")` fallback.

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_review_regressions.py
git commit -m "fix: route exclude-failure errors back to Session Review"
```

---

### Task 4: Clarify `g`/`G` semantics in hint bar

**Files:**
- Modify: `src/iiwi/interactive/render.py:1918-1927` (session-review hints list)
- Test: `tests/unit/interactive/test_simplified_footer.py`

**Interfaces:**
- Consumes: The hints list literal in `render_session_review()`
- Produces: Updated hint labels visible in the footer; no API change

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/interactive/test_simplified_footer.py`:

```python
def test_review_hints_distinguish_g_generate_from_g_top() -> None:
    lines = help_lines()
    review_hints_text = " ".join(lines)
    # The general help must clarify that g/G mean Generate/Force on Review,
    # not Jump-to-top/bottom like they do on previews.
    assert "g              Generate the report" in lines or any(
        "g" in line and "Generate" in line for line in lines
    )
    assert any("G" in line and "Group" in line for line in lines)
```

Also add a render-level test that checks the hint bar itself:

```python
def test_review_hint_bar_shows_force_shortcut() -> None:
    stream = StringIO()
    console = Console(file=stream, color_system=None, force_terminal=False, width=120)
    selection = SelectionState.from_scan(_scan())

    render_session_review(
        console,
        selection,
        expanded_repositories=set(),
        cursor=0,
    )

    assert "g Report" in stream.getvalue()
    assert "G Force" in stream.getvalue()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/interactive/test_simplified_footer.py::test_review_hints_distinguish_g_generate_from_g_top tests/unit/interactive/test_simplified_footer.py::test_review_hint_bar_shows_generate_not_jump -v`
Expected: FAIL — current hints show `"g Report"` but do not show `"G Force"`, and the help text doesn't clearly distinguish `g`'s dual meaning.

- [ ] **Step 3: Update the hints list and help lines**

In `src/iiwi/interactive/render.py`, change the session-review hints list (~line 1918) from:

```python
    hints = [
        "↑↓ jk",
        "Space Select",
        "p Inspect",
        "/ Search",
        "g Report",
        "? More",
        "b Back",
    ]
```

to:

```python
    hints = [
        "↑↓ jk",
        "Space Select",
        "p Inspect",
        "/ Search",
        "g Report",
        "G Force",
        "? More",
        "b Back",
    ]
```

In `_HELP_LINES`, add after the `"G              Group..."` line:

```python
    "g * / G        Generate report / force grouping (Review)",
```

(Replaces the existing `"g * / G        Jump to top / bottom in report preview"` line, which stays for previews.)

- [ ] **Step 4: Run all three tasks' tests plus the full suite**

Run: `pytest tests/unit/interactive/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/render.py tests/unit/interactive/test_simplified_footer.py
git commit -m "feat: clarify G Force shortcut and g semantic split in hints"
```

---

### Task 5: Final verification

**Files:** No modifications; validation only.

- [ ] **Step 1: Run the full interactive test suite**

Run: `pytest tests/unit/interactive/ -v`
Expected: All PASS

- [ ] **Step 2: Run linting**

Run: `ruff check src/iiwi/interactive/ tests/unit/interactive/`
Expected: No errors

- [ ] **Step 3: Run type checking**

Run: `mypy src/iiwi/interactive/`
Expected: No errors (or no new errors vs baseline)

- [ ] **Step 4: Run integration tests**

Run: `pytest tests/integration/test_interactive_cli.py -v`
Expected: All PASS
