# Interactive History View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `History` entry to the interactive main menu that lists past reports (newest first) and shows a selected report's recorded output path.

**Architecture:** A fifth main-menu option opens a new `Screen.HISTORY`. The screen reuses `read_history()` for data, the existing RECOVERABLE_ERROR screen for path display (new error kind `history-path`), and the existing viewport-scroll pattern. No history logging changes.

**Tech Stack:** Python, Typer, Rich, pathlib, existing `iiwi.history` module.

## Global Constraints

- Menu order is fixed: `["Review Activity", "Generate Report", "History", "Check Setup", "Settings"]` — History sits before the two non-functional rows.
- Entries render newest first (`list(reversed(read_history()))`), matching the CLI history table.
- Empty history renders `No reports generated yet.` and Enter does nothing.
- Path rows truncate with an ellipsis (never wrap), like every other TUI row; the full path shows on the path screen one Enter away.
- No changes to `iiwi.history` read/write logic; `read_history` and `append_history` are used as-is.
- No entry point on the report result screen — the main menu is the only History entry.
- All work happens in `src/iiwi/interactive/` plus docs; no CLI command behavior changes.

Spec: `docs/2026-08-12-interactive-history-view-design.md`

---

### Task 1: Main menu gains the History option

**Files:**
- Modify: `src/iiwi/interactive/render.py:51-59` (`_MAIN_OPTIONS`, `_MAIN_DESCRIPTIONS`)
- Modify: `src/iiwi/interactive/render.py:940` (footer hint `"1-4"` → `"1-5"`)
- Test: `tests/unit/interactive/test_render.py` (append two tests near `test_main_menu_describes_each_option` at line 139)

**Interfaces:**
- Consumes: existing `_MAIN_OPTIONS`, `_MAIN_DESCRIPTIONS`, `_print_hints` (all already in render.py)
- Produces: `_MAIN_OPTIONS` now has 5 entries; `_MAIN_DESCRIPTIONS["History"]` exists. Task 2's controller wiring reads `main_menu_options()` which returns this list unchanged.

- [ ] **Step 1: Write the failing render tests**

Append to `tests/unit/interactive/test_render.py` (after `test_main_menu_describes_each_option`, line 156):

```python
def test_main_menu_orders_history_before_the_non_functional_rows() -> None:
    console, stream = _console()

    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert "1-5" in text
    assert text.index("History") < text.index("Check Setup")
    assert text.index("Check Setup") < text.index("Settings")


def test_main_menu_describes_history() -> None:
    console, stream = _console()

    render_main_menu(console, selected=0)

    history = next(
        line for line in stream.getvalue().splitlines() if "History" in line
    )
    assert "List past reports and their paths" in history
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_render.py -k "history" -v`
Expected: FAIL — `History` does not render (or `1-5` absent, or `text.index("History")` raises ValueError).

- [ ] **Step 3: Implement the menu change**

In `src/iiwi/interactive/render.py`:

```python
_MAIN_OPTIONS = ["Review Activity", "Generate Report", "History", "Check Setup", "Settings"]
# The main menu explains what each option does, the way mole's menu does: one
# dim clause per row, aligned under the widest label.
_MAIN_DESCRIPTIONS = {
    "Review Activity": "Explore sessions by repository",
    "Generate Report": "Configure and produce a report",
    "History": "List past reports and their paths",
    "Check Setup": "Diagnose the harness setup",
    "Settings": "Edit saved settings",
}
```

And at line 940 (the main menu's footer hints):

```python
        ["↑↓ jk", "Enter Select", "1-5", "? Help", "q Quit"],
```

No other change: `render_main_menu` iterates `_MAIN_OPTIONS` and reads `_MAIN_DESCRIPTIONS[label]`, and the description column is measured by `label_width = max(cell_len(label) for label in _MAIN_OPTIONS)` (line 925), which still widens to `Generate Report` (15 cells) — `History` does not shift the column.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_render.py -k "history" -v`
Expected: PASS (both new tests).

- [ ] **Step 5: Run the full render test module**

Run: `uv run pytest tests/unit/interactive/test_render.py -q`
Expected: PASS — no existing test asserts `1-4` or the menu item count.

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/interactive/render.py tests/unit/interactive/test_render.py
git commit -m "feat: add History to the interactive main menu"
```

---

### Task 2: History screen enum, state, and renderer

**Files:**
- Modify: `src/iiwi/interactive/models.py:17-28` (Screen enum)
- Modify: `src/iiwi/interactive/render.py` (new `history_capacity`, `render_history`, `_history_entry_line`; import `HistoryEntry` from `iiwi.history`)
- Test: `tests/unit/interactive/test_render.py` (new tests at end of file)

**Interfaces:**
- Consumes: `HistoryEntry` (src/iiwi/history.py:22-34), `_print_header`, `_print_viewport_line` (already in render.py)
- Produces:
  - `Screen.HISTORY` enum member — used by Task 3 controller wiring
  - `history_capacity(terminal_height: int) -> int` — viewport row count for one history screen
  - `render_history(console, *, entries: Sequence[HistoryEntry], selected: int, offset: int) -> None` — renders newest-first entries already ordered by the caller; `selected` is a global entry index, `offset` the first visible entry index
  - `_history_entry_line(entry: HistoryEntry, *, selected: bool) -> str` — one display row

- [ ] **Step 1: Write the failing renderer tests**

Append to `tests/unit/interactive/test_render.py`:

```python
def _history_entry(index: int, output_path: str) -> HistoryEntry:
    return HistoryEntry(
        generated_at=datetime(2026, 8, 12, 9, 30, tzinfo=ZoneInfo("Asia/Taipei")),
        harness="opencode",
        since=datetime(2026, 8, 3, tzinfo=ZoneInfo("Asia/Taipei")),
        until=datetime(2026, 8, 10, tzinfo=ZoneInfo("Asia/Taipei")),
        output_path=Path(output_path),
        repository_count=2,
        session_count=7,
        narrative=True,
        detail="full",
    )


def test_history_renders_entries_with_the_cursor_on_the_selected_row() -> None:
    console, stream = _console()

    render_history(
        console,
        entries=[_history_entry(0, "reports/a.md"), _history_entry(1, "reports/b.md")],
        selected=1,
        offset=0,
    )

    text = stream.getvalue()
    assert "Past Reports" in text
    assert "reports/a.md" in text
    assert "reports/b.md" in text
    assert "▶" in text


def test_history_renders_empty_state_when_there_are_no_entries() -> None:
    console, stream = _console()

    render_history(console, entries=[], selected=0, offset=0)

    text = stream.getvalue()
    assert "No reports generated yet." in text


def test_history_scrolls_its_viewport() -> None:
    console, stream = _console()
    entries = [_history_entry(i, f"reports/{i}.md") for i in range(20)]

    render_history(console, entries=entries, selected=19, offset=10)

    lines = stream.getvalue().splitlines()
    assert "reports/10.md" in lines[3]
    assert "reports/0.md" not in lines[3]


def test_history_capacity_reserves_the_footer() -> None:
    assert history_capacity(30) == 22
```

(The file's existing `_console()` helper (line 38) already returns
`(Console, StringIO)` with `width=100, height=None`, so reuse it as in the
tests above. Add `HistoryEntry` to the imports from `iiwi.history`, and
`Sequence` to the collections import if it is not already there.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_render.py -k "history" -v`
Expected: FAIL — `render_history`/`history_capacity` are not defined.

- [ ] **Step 3: Add the Screen enum member**

In `src/iiwi/interactive/models.py`, after `OUTCOME_REVIEW` (alphabetical-ish grouping with the other review screens is fine; the enum's existing order is MAIN, REPORT_SETUP, SESSION_REVIEW, SESSION_BROWSER, SESSION_PREVIEW, OUTCOME_REVIEW, REPORT_RESULT, REPORT_PREVIEW, RECOVERABLE_ERROR, HELP, EXIT):

```python
    HISTORY = "history"
```

Place it between `HELP` and `EXIT`, next to the other non-flow screens.

- [ ] **Step 4: Implement the renderer**

In `src/iiwi/interactive/render.py`, add to the imports:

```python
from iiwi.history import HistoryEntry
```

Add a capacity function next to `report_preview_capacity` (line 868) and the screen renderer near `render_report_result` (line 1449):

```python
def history_capacity(terminal_height: int) -> int:
    """History rows that fit while reserving the header, blanks, and hints."""

    return max(0, terminal_height - 8)


def _history_entry_line(entry: HistoryEntry, *, selected: bool) -> str:
    period = f"{entry.since:%Y-%m-%d} – {entry.until:%Y-%m-%d}"
    narrative = "narrative" if entry.narrative else "structure"
    return (
        f"{_CURSOR if selected else ' '} "
        f"{entry.generated_at:%Y-%m-%d %H:%M}  {period}  "
        f"{entry.harness:>10}  {entry.session_count:>3} sess  "
        f"{entry.repository_count:>2} repos  {narrative}  {entry.output_path}"
    )


def render_history(
    console: Console,
    *,
    entries: Sequence[HistoryEntry],
    selected: int,
    offset: int,
) -> None:
    """Render the generated-report log, newest first, as a scrollable list.

    The caller passes entries already ordered newest first. `selected` is the
    cursor's global entry index; `offset` is the first visible entry index.
    """

    _print_header(console, "Past Reports")
    console.print()
    capacity = history_capacity(console.size.height)
    if not entries:
        _print_viewport_line(console, "No reports generated yet.", style="dim")
        console.print()
        _print_hints(
            console,
            ["↑↓ jk Scroll", "? Help", "b Back"],
        )
        return
    end = min(len(entries), offset + capacity)
    for index in range(offset, end):
        _print_viewport_line(
            console,
            _history_entry_line(entries[index], selected=index == selected),
        )
    console.print()
    _print_hints(
        console,
        ["↑↓ jk Scroll", "Enter Path", "PgUp/PgDn", "g/G Top/Bottom", "? Help", "b Back"],
    )
```

`Sequence` is already imported in render.py (`from collections.abc import ...` — verify; if not, add `from collections.abc import Sequence`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_render.py -k "history" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/interactive/models.py src/iiwi/interactive/render.py tests/unit/interactive/test_render.py
git commit -m "feat: render the interactive history screen"
```

---

### Task 3: Controller wiring and navigation

**Files:**
- Modify: `src/iiwi/interactive/controller.py`
  - `_State` (add `history_cursor`, `history_offset` near line 123)
  - `_main_key` (lines 378-417: numeric set, History branch, doctor branch index)
  - new `_history_key` + `_history_entries` helpers (near `_result_key`, line 1226)
  - `_dispatch` (line 1471: HISTORY route)
  - `_idle_interrupt` (line 1438: HISTORY returns to MAIN)
  - `_render_screen` (line 1343: HISTORY renders via `render_history`)
  - `_error_options` (line 1094: `history-path` → `["Back"]`)
  - `_error_back_screen` (line 1113: `history-path` → `Screen.HISTORY`)
- Modify: `tests/unit/interactive/test_controller.py` (new navigation tests)
- Modify: `tests/unit/interactive/test_controller_results.py:151-177` (numeric shortcut indices: Check Setup `"3"`→`"4"`, Settings `"4"`→`"5"`)

**Interfaces:**
- Consumes: `Screen.HISTORY`, `render_history`, `history_capacity` (Task 2); `read_history` (src/iiwi/history.py:77); `_move`, `_exact_char`, `_char`, `Key`, `KeyPress`, `_ErrorState` (already in controller.py)
- Produces: history flow: main menu "History" (cursor 2, numeric `3`) → `Screen.HISTORY`; `j/k`/PgUp/PgDn/`g`/`G` move the cursor, viewport follows; Enter shows the recorded path on RECOVERABLE_ERROR (kind `history-path`); `b`/Esc/`q`/Ctrl-C return to MAIN; empty history ignores Enter.

- [ ] **Step 1: Write the failing controller tests**

Append to `tests/unit/interactive/test_controller.py` (the file already defines `char`, `ScriptedInput`, `_console`, `_actions`, `TZ`):

```python
def _history_entry(output_path: str) -> HistoryEntry:
    return HistoryEntry(
        generated_at=datetime(2026, 8, 12, 9, 30, tzinfo=TZ),
        harness="opencode",
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
        output_path=Path(output_path),
        repository_count=2,
        session_count=7,
        narrative=True,
        detail="full",
    )


def test_main_menu_history_opens_and_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/worklog.md"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput([char("3"), char("b"), char("q")]),
        console=console,
    )

    text = console.file.getvalue()
    assert "Past Reports" in text
    assert "reports/worklog.md" in text


def test_history_enter_shows_the_recorded_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/worklog.md"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [char("3"), KeyPress(key=Key.ENTER), char("b"), char("b"), char("q")]
        ),
        console=console,
    )

    text = console.file.getvalue()
    assert "Report path" in text
    assert "reports/worklog.md" in text


def test_history_enter_shows_the_cursor_row_not_the_first_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/first.md"))
    append_history(_history_entry("reports/second.md"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [char("3"), char("j"), KeyPress(key=Key.ENTER), char("b"), char("b"), char("q")]
        ),
        console=console,
    )

    text = console.file.getvalue()
    # The history screen lists both paths; the path screen must show the
    # cursor's row. Newest first: index 0 is second.md, cursor moves to
    # index 1 = first.md. The last occurrence of each path after the first
    # "Report path" title is the error screen's detail, so rindex ordering
    # pins which path the error screen displayed.
    first_title = text.index("Report path")
    assert text.rindex("reports/first.md") > first_title
    assert text.rindex("reports/second.md") < first_title


def test_history_g_and_G_jump_follow_the_viewport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    for index in range(20):
        append_history(_history_entry(f"reports/{index}.md"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [char("3"), char("G"), KeyPress(key=Key.ENTER), char("b"),
             char("g"), KeyPress(key=Key.ENTER), char("b"), char("b"), char("q")]
        ),
        console=console,
    )

    text = console.file.getvalue()
    # 20 entries exceed the test console's ~17-row viewport, so G clamps the
    # offset; Enter on the bottom row shows the oldest entry, then g jumps
    # back to the top and Enter shows the newest.
    assert text.rindex("reports/0.md") > text.index("Report path")
    assert text.rindex("reports/19.md") > text.rindex("reports/0.md")


def test_history_empty_state_ignores_enter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput([char("3"), KeyPress(key=Key.ENTER), char("b"), char("q")]),
        console=console,
    )

    text = console.file.getvalue()
    assert "No reports generated yet." in text
    assert "Report path" not in text


def test_ctrl_c_on_history_returns_to_the_main_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/worklog.md"))

    class ScriptedWithInterrupt(ScriptedInput):
        """Interrupt the read after the first key, then resume the script."""

        def __init__(self, keys: list[KeyPress]) -> None:
            super().__init__(keys)
            self.pending_interrupt = True

        def read_key(self) -> KeyPress:
            if self.pending_interrupt:
                self.pending_interrupt = False
                raise KeyboardInterrupt
            return super().read_key()

    input_source = ScriptedWithInterrupt([char("3"), char("b"), char("q")])
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=input_source,
        console=console,
    )

    text = console.file.getvalue()
    # The interrupt lands on the second read (cursor on HISTORY after `3`).
    # The idle-interrupt handler must return to MAIN, so the final frame is
    # the main menu: "Past Reports" appears exactly once (the HISTORY screen
    # never re-renders) and the output ends with the main menu's footer
    # (`q Quit`), not the history screen's (`b Back`).
    assert text.count("Past Reports") == 1
    assert text.rstrip().endswith("q Quit")
```

The interrupt lands on the second read (cursor on HISTORY after `3`); the
idle-interrupt handler must send the flow to MAIN, after which `b` is a
no-op on MAIN and `q` exits. `run_interactive` returning at all is the core
assertion — a Ctrl-C that exited the app would raise Typer.Abort and fail
the test.
```

Add imports to `tests/unit/interactive/test_controller.py`:

```python
import pytest

from iiwi.history import HistoryEntry, append_history
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_controller.py -k "history" -v`
Expected: FAIL — numeric `3` opens Check Setup today, so `Past Reports` never renders.

- [ ] **Step 3: Update the two numeric-shortcut tests**

In `tests/unit/interactive/test_controller_results.py`:
- `test_doctor_result_uses_a_persistent_result_screen` (line 156): change `char("3")` to `char("4")`.
- `test_settings_completion_returns_through_a_visible_result_screen` (line 171): change `char("4")` to `char("5")`.

- [ ] **Step 4: Implement the controller wiring**

In `src/iiwi/interactive/controller.py`:

1. Add to imports:

```python
from iiwi.history import HistoryEntry, read_history
```

2. `_State` fields, after `result_cursor: int = 0` (line 123):

```python
    history_cursor: int = 0
    history_offset: int = 0
```

3. `_main_key` (lines 378-417): extend the numeric set and reorder branches:

```python
    if key.char in {"1", "2", "3", "4", "5"}:
        state.main_cursor = int(key.char) - 1
        activate = True
    else:
        activate = key.key is Key.ENTER
    if not activate:
        return

    if state.main_cursor == 0:
        _begin_browse(state, actions)
    elif state.main_cursor == 1:
        _new_report(state, actions)
    elif state.main_cursor == 2:
        state.history_cursor = 0
        state.history_offset = 0
        state.screen = Screen.HISTORY
    elif state.main_cursor == 3:
        draft = actions.new_draft()
        try:
            lines = actions.doctor(draft.harness)
        except IiwiError as exc:
            detail = f"ERROR: {exc}"
        else:
            detail = "\n".join(lines)
        state.error = _ErrorState(
            kind="doctor-result",
            title="Check Setup",
            detail=detail,
        )
        state.screen = Screen.RECOVERABLE_ERROR
    else:
        actions.edit_settings()
        state.error = _ErrorState(
            kind="settings-result",
            title="Settings",
            detail="Settings editor finished.",
        )
        state.screen = Screen.RECOVERABLE_ERROR
```

4. New helpers next to `_result_key` (before line 1226):

```python
def _history_entries() -> list[HistoryEntry]:
    """The generated-report log, newest first, as the history screen shows it."""

    return list(reversed(read_history()))


def _history_key(state: _State, key: KeyPress, console: Console) -> None:
    if key.key is Key.ESCAPE or _char(key, "q") or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    entries = _history_entries()
    count = len(entries)
    if not count:
        return
    capacity = history_capacity(console.size.height)
    page = max(1, capacity)
    state.history_cursor = _move(state.history_cursor, key, count)
    if key.key is Key.PAGE_UP:
        state.history_cursor = max(0, state.history_cursor - page)
    elif key.key is Key.PAGE_DOWN:
        state.history_cursor = min(count - 1, state.history_cursor + page)
    elif key.key is Key.HOME or _exact_char(key, "g"):
        state.history_cursor = 0
    elif key.key is Key.END or _exact_char(key, "G"):
        state.history_cursor = count - 1
    state.history_offset = min(state.history_offset, max(0, count - capacity))
    if state.history_cursor < state.history_offset:
        state.history_offset = state.history_cursor
    if state.history_cursor >= state.history_offset + capacity:
        state.history_offset = max(0, state.history_cursor - capacity + 1)
    if key.key is not Key.ENTER:
        return

    entry = entries[state.history_cursor]
    state.error = _ErrorState(
        kind="history-path",
        title="Report path",
        detail=str(entry.output_path),
    )
    state.screen = Screen.RECOVERABLE_ERROR
```

Note: `_exact_char(key, "g")` (lowercase only) for top and `_exact_char(key, "G")`
for bottom, mirroring `_preview_key` (lines 1289-1291). Do NOT use `_char`,
whose casefold matches both cases and would make `G` jump to top too. The
offset clamp uses `max(0, count - capacity)` because `count < capacity` must
leave the offset at 0, never negative.

5. `_dispatch` (after the `Screen.REPORT_RESULT` route, line 1472):

```python
    elif state.screen is Screen.HISTORY:
        _history_key(state, key, console)
```

6. `_idle_interrupt` (after the `REPORT_RESULT` branch, line 1439):

```python
    elif state.screen is Screen.HISTORY:
        state.screen = Screen.MAIN
```

7. `_render_screen` (after the `REPORT_RESULT` branch, line 1403):

```python
    elif state.screen is Screen.HISTORY:
        render_history(
            console,
            entries=_history_entries(),
            selected=state.history_cursor,
            offset=state.history_offset,
        )
```

8. Add `render_history` and `history_capacity` to the imports from `iiwi.interactive.render` (lines 23-49), alongside `render_report_result`.

9. `_error_options` (after the `report-path` branch, line 1095):

```python
    if error.kind == "history-path":
        return ["Back"]
```

10. `_error_back_screen` (after the `report-path` branch, line 1115):

```python
    if error.kind == "history-path":
        return Screen.HISTORY
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_controller.py -k "history" -v`
Expected: PASS (all four new tests).

- [ ] **Step 6: Run the affected modules**

Run: `uv run pytest tests/unit/interactive/ -q`
Expected: PASS — includes the two updated numeric-shortcut tests.

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_controller.py tests/unit/interactive/test_controller_results.py
git commit -m "feat: navigate the interactive history screen"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md:48-73` (menu block + hint)
- Modify: `README.zh-TW.md:48-73` (mirror block)
- Modify: `docs/cli-reference.md:85-95` (interactive behavior paragraph)

**Interfaces:**
- Consumes: final menu order from Task 1: `Review Activity / Generate Report / History / Check Setup / Settings`, hint `1-5`.

- [ ] **Step 1: Update README.md**

In the `## The interactive menu` section, update the menu block (README.md lines 62-68). The block currently shows the stale pre-rework list; replace the four rows and the hint with the current menu:

```text
▶ Review Activity
  Generate Report
  History
  Check Setup
  Settings

↑↓ jk │ Enter Select │ 1-5 │ ? Help │ q Quit
```

Then add one sentence after the "Choosing **Generate a report**" paragraph (line 70-73) describing the History entry:

```markdown
Choosing **History** lists every report the tool has written, newest first.
`↑↓` moves; Enter shows the row's full output path.
```

- [ ] **Step 2: Mirror in README.zh-TW.md**

Apply the same menu block and the History sentence in Traditional Chinese. Read the existing zh-TW menu section first and keep the surrounding wording; the menu rows keep their English labels (they are what the TUI prints), the explanatory sentence is translated, e.g.:

```markdown
選擇 **History** 會列出工具產生過的所有報告，最新的在前。
`↑↓` 移動，Enter 顯示該筆的完整輸出路徑。
```

- [ ] **Step 3: Update docs/cli-reference.md**

Read the interactive paragraph at lines 85-95 and add the History entry to the description of the main menu, e.g. extend the sentence about the main menu's actions with: the main menu also lists past reports under **History**, where Enter shows a report's recorded output path.

- [ ] **Step 4: Verify docs consistency**

Run: `uv run pytest tests/unit/test_interactive_documentation.py -q`
Expected: PASS — this module checks README wording against the CLI help; if it now fails on the changed menu wording, update the assertions to the new copy (read the failure first; do not weaken an assertion that still holds).

- [ ] **Step 5: Commit**

```bash
git add README.md README.zh-TW.md docs/cli-reference.md
git commit -m "docs: document the interactive History screen"
```

---

### Task 5: Full-suite verification

**Files:** none (verification only)

**Interfaces:** consumes all prior tasks

- [ ] **Step 1: Run the complete test suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 2: Run the linters**

Run: `uv run ruff check src tests`
Expected: clean.

- [ ] **Step 3: Typecheck**

Run: `uv run pyright src` (pyright is the configured type checker, `[tool.pyright]` in pyproject.toml)
Expected: clean.

- [ ] **Step 4: Manual smoke test**

Run: `iiwi` in a terminal, press `3` to open History, `↓`/`Enter` to show a path, `b` twice to return, `q` to quit. With no reports yet, History must show the empty-state line.
Expected: screen renders without flicker or crash.
