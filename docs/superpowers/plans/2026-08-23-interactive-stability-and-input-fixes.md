# Interactive Stability and Text Input Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix interactive CLI crash on `daily-start` error activation and enable Space key input in the Review search field (`/`) and Settings inline editor.

**Architecture:** Update `controller.py` error options and back-screen routing for the `daily-start` error kind; update `_search_input` and `_settings_edit_key` to recognize `Key.SPACE` alongside printable characters; update `render.py` inline-editing hints.

**Tech Stack:** Python 3.11+, pytest, Rich terminal rendering.

## Global Constraints

- Enforce TDD: Write failing tests before modifying implementation code.
- Use exact helper conventions (`ScriptedInput`, `char()`, `KeyPress`, `Key`) established in `tests/unit/interactive/`.
- Ensure all unit tests pass, with zero lint or pyright type checking regressions.

---

### Task 1: Fix `daily-start` error handling to prevent crash on Enter

**Files:**
- Modify: `src/iiwi/interactive/controller.py:1521, 1564`
- Test: `tests/unit/interactive/test_daily_review_failures.py`

**Interfaces:**
- Consumes: `_ErrorState(kind="daily-start", ...)`, `_error_options(error)` -> `list[str]`, `_error_back_screen(error)` -> `Screen`
- Produces: `_error_options` returns `["Back", "Main menu"]` for `daily-start`; `_error_back_screen` routes to `Screen.MAIN`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/interactive/test_daily_review_failures.py`:

```python
def test_daily_start_error_enter_returns_to_main_without_crash() -> None:
    log = ActionLog()
    actions = _replace_daily_actions(
        _actions(log),
        start_daily=lambda previous: (_ for _ in ()).throw(
            ConfigurationError("no harness is enabled")
        ),
    )
    state = _state()

    controller._begin_daily_review(state, actions)

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "daily-start"
    assert controller._error_options(state.error) == ["Back", "Main menu"]

    # Pressing Enter on option 0 ("Back") must not raise AssertionError on state.draft
    controller._error_key(state, KeyPress(key=Key.ENTER), actions, _console())

    assert state.screen is Screen.MAIN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/interactive/test_daily_review_failures.py::test_daily_start_error_enter_returns_to_main_without_crash -v`
Expected: FAIL with `AssertionError: assert ['Change harness', 'Back', 'Main menu'] == ['Back', 'Main menu']`

- [ ] **Step 3: Write minimal implementation**

In `src/iiwi/interactive/controller.py`, update `_error_options` (~line 1521):

```python
    if error.kind in {"new-report-start", "activity-start", "daily-start"}:
        # No "Change harness"/"Change period": both of those assume
        # state.draft is already set, but these three kinds fire when building
        # the draft itself is what failed, so state.draft is still None.
        return ["Back", "Main menu"]
```

And in `_error_back_screen` (~line 1564), ensure `daily-start` routes to `Screen.MAIN`:

```python
    if error.kind in {"daily-source", "daily-start"}:
        return Screen.MAIN
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/interactive/test_daily_review_failures.py::test_daily_start_error_enter_returns_to_main_without_crash -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_daily_review_failures.py
git commit -m "fix: route daily-start error to Back and Main menu without draft assertion"
```

---

### Task 2: Allow Space key in Session Review search input (`/`)

**Files:**
- Modify: `src/iiwi/interactive/controller.py:717-732` (`_search_input`)
- Test: `tests/unit/interactive/test_controller.py`

**Interfaces:**
- Consumes: `KeyPress(key=Key.SPACE, char=None)`, `state.search_query` (str), `state.searching` (bool)
- Produces: `_search_input` appends `" "` to `state.search_query` when `key.key is Key.SPACE`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/interactive/test_controller.py`:

```python
def test_space_key_types_into_search_input() -> None:
    stream = StringIO()
    console = Console(
        file=stream, color_system=None, force_terminal=False, width=100,
    )
    input_source = ScriptedInput(
        [
            char("3"),
            char("r"),
            char("/"),
            char("a"),
            KeyPress(key=Key.SPACE),
            char("b"),
            KeyPress(key=Key.ENTER),
            char("q"),
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
    assert "Search: a b" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/interactive/test_controller.py::test_space_key_types_into_search_input -v`
Expected: FAIL — `Search: a b` not found because Space is ignored and the query becomes `Search: ab`.

- [ ] **Step 3: Write minimal implementation**

In `src/iiwi/interactive/controller.py`, update `_search_input` (~line 720):

```python
def _search_input(state: _State, key: KeyPress, cursor_name: str) -> bool:
    if not state.searching:
        return False
    if key.key is Key.ESCAPE:
        _reset_search(state)
    elif key.key in {Key.BACKSPACE, Key.DELETE}:
        state.search_query = state.search_query[:-1]
    elif key.key is Key.ENTER:
        state.searching = False
    elif key.key is Key.SPACE:
        state.search_query += " "
    elif key.char is not None and key.char.isprintable():
        state.search_query += key.char
    else:
        return True
    setattr(state, cursor_name, 0)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/interactive/test_controller.py::test_space_key_types_into_search_input -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_controller.py
git commit -m "fix: allow typing space in search input"
```

---

### Task 3: Allow Space and Delete keys in Settings inline editor and update hint bar

**Files:**
- Modify: `src/iiwi/interactive/controller.py:628-650` (`_settings_edit_key`), `src/iiwi/interactive/render.py:1691-1697` (`render_settings`)
- Test: `tests/unit/interactive/test_settings_controller.py`

**Interfaces:**
- Consumes: `KeyPress(key=Key.SPACE, char=None)`, `KeyPress(key=Key.DELETE, char=None)`, `state.settings_edit_value` (str)
- Produces: `_settings_edit_key` appends `" "` on Space, trims on Delete; `render_settings` hints show `["Enter Keep", "Esc Cancel"]` when editing.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/interactive/test_settings_controller.py`:

```python
def test_space_and_delete_in_settings_inline_editor() -> None:
    state = _State(screen=Screen.SETTINGS)
    state.settings_rows = build_settings_rows()
    state.settings_cursor = next(
        index
        for index, row in enumerate(state.settings_rows)
        if row.editable and not row.locked
    )
    state.settings_editing = True
    state.settings_edit_value = "hello"

    # Test typing space
    _settings_edit_key(state, KeyPress(key=Key.SPACE))
    assert state.settings_edit_value == "hello "

    # Test typing character
    _settings_edit_key(state, KeyPress(char="world"))
    assert state.settings_edit_value == "hello world"

    # Test delete key
    _settings_edit_key(state, KeyPress(key=Key.DELETE))
    assert state.settings_edit_value == "hello worl"


def test_settings_editing_hint_does_not_advertise_help() -> None:
    rows = build_settings_rows()
    console, stream = _console()
    render_settings(
        console,
        rows=rows,
        cursor=0,
        editing=True,
        edit_value="test",
        error=None,
    )
    output = stream.getvalue()
    assert "Enter Keep" in output
    assert "Esc Cancel" in output
    assert "? Help" not in output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/interactive/test_settings_controller.py::test_space_and_delete_in_settings_inline_editor tests/unit/interactive/test_settings_controller.py::test_settings_editing_hint_does_not_advertise_help -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `src/iiwi/interactive/controller.py`, update `_settings_edit_key` (~line 628):

```python
def _settings_edit_key(state: _State, key: KeyPress) -> None:
    """The inline editor: type, backspace, Enter writes, Esc cancels."""

    assert state.settings_rows is not None
    if key.key is Key.ESCAPE:
        state.settings_editing = False
        state.settings_edit_value = ""
        state.settings_error = None
        return
    if key.key in {Key.BACKSPACE, Key.DELETE}:
        state.settings_edit_value = state.settings_edit_value[:-1]
        return
    if key.key is Key.ENTER:
        row = state.settings_rows[state.settings_cursor]
        _persist_setting(state, row.key, state.settings_edit_value.strip())
        if state.settings_error is None:
            state.settings_editing = False
            state.settings_edit_value = ""
        return
    if key.key is Key.SPACE:
        state.settings_edit_value += " "
        return
    if key.char is not None:
        state.settings_edit_value += key.char
```

In `src/iiwi/interactive/render.py`, update `render_settings` footer hint (~line 1691):

```python
    _print_hints(
        console,
        ["Enter Keep", "Esc Cancel"]
        if editing
        else ["↑↓ jk", "←→ Cycle", "Enter Edit", "? Help", "b Back"],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/interactive/test_settings_controller.py::test_space_and_delete_in_settings_inline_editor tests/unit/interactive/test_settings_controller.py::test_settings_editing_hint_does_not_advertise_help -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/controller.py src/iiwi/interactive/render.py tests/unit/interactive/test_settings_controller.py
git commit -m "fix: allow Space and Delete in settings inline editor and correct hints"
```

---

### Task 4: Full Test Suite and Quality Verification

**Files:** None (validation only)

- [ ] **Step 1: Run full interactive unit tests**

Run: `uv run pytest tests/unit/interactive/ -v`
Expected: All unit tests pass.

- [ ] **Step 2: Run complete test suite, linter, and type checker**

Run: `uv run ruff check . && uv run pyright && uv run pytest`
Expected: 0 ruff errors, 0 pyright errors, 1485+ pytest tests pass.
