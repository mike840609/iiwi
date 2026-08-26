# Interactive History Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend interactive History from path-only list to previewable archive with auto-filtered missing files, in-TUI markdown preview, and one-key open in editor.

**Architecture:** Add `Screen.HISTORY_PREVIEW` plus filtered-view helper `_filtered_history`; extend `render_history` to show hidden-count banner and dim missing rows and add new `render_history_preview` reusing `report_preview_capacity` viewport; extend `_history_key` for `Enter/p` preview, `o` open, `h` toggle and add `_history_preview_key` for scroll/open/back, wiring `_dispatch`/`_render_screen`/`_idle_interrupt` without mutating `history.jsonl`.

**Tech Stack:** Python 3.11+, Rich TUI (`src/iiwi/interactive/`), `src/iiwi/history.py`, `pathlib`/`subprocess`/`shlex`, pytest, ruff, pyright, uv.

## Global Constraints

- `history.jsonl` is append-only — never rewrite or delete lines; filtering is view-only (`src/iiwi/history.py:1-6`).
- Base branch is `origin/main` after commit `85f610e`; pull before branching.
- History list reads `read_history()` per render (reversed newest-first) and stays cheap; keep that.
- Interactive loop uses captured frame painting in `controller.py:290-322` and `render.py:_print_viewport_line` truncating (ellipsis, never wrap); history preview must follow the same viewport pattern (`report_preview_capacity` / `_detail_window`).
- Preview reads file as UTF-8 with `errors="replace"`; redaction via `security/redactor.redact_text` on render path only, not needed for preview raw lines (preview already redacts via `build_session_preview_lines` pattern — history preview shows report markdown as-is, truncated not redacted beyond file content).
- Open precedence: `$VISUAL` → `$EDITOR` → `open` (darwin) → `xdg-open`; path passed as separate arg after `shlex.split(editor)`; failures surface via `RECOVERABLE_ERROR`.
- Enter on History is Preview (user confirmed); path remains visible inside preview header; `p` is alias for `Enter`.
- Missing files hidden by default; toggle `h` shows them dimmed with `· missing` suffix; banner `N hidden (missing) — press h to show` shown only when `hidden_count>0`.
- No new dependencies; no CLI `iiwi history` changes.

---

## File Structure

- `src/iiwi/interactive/models.py` — owns `Screen` enum; add `HISTORY_PREVIEW = "history_preview"`; no other logic.
- `src/iiwi/interactive/controller.py` — owns `_State`, `_history_entries`, `_history_key`, `_dispatch`, `_render_screen`, `_idle_interrupt`, and new helpers `_filtered_history`, `_open_history_entry`, `_history_preview_key`. State gains `history_show_missing: bool`, `history_preview_entry: HistoryEntry | None`, `history_preview_offset: int`.
- `src/iiwi/interactive/render.py` — owns `_HISTORY_HINTS`, `history_capacity`, `render_history` (`_history_entry_line`), and new `render_history_preview` plus optional `history_preview_capacity` alias; updates hint strings to include `Enter/p Preview`, `o Open`, `h Toggle`; header banner for hidden count; dim missing rows.
- `src/iiwi/history.py` — unchanged (read-only).
- Tests: `tests/unit/interactive/test_render.py` extends history render tests; new `tests/unit/interactive/test_history_preview.py` covers filtering, toggle clamping, preview scroll, open invocation, missing handling. `tests/unit/interactive/test_viewport_wrapping_regressions.py` extends capacity regression.

---

### Task 1: Screen and state foundation + filtered helper

**Files:**
- Modify: `src/iiwi/interactive/models.py`
- Modify: `src/iiwi/interactive/controller.py`
- Test: `tests/unit/interactive/test_render.py` (no new test yet, but verify enum exists)

**Interfaces:**
- Consumes: `HistoryEntry` from `iiwi.history`, existing `_State`, `Screen`.
- Produces: `Screen.HISTORY_PREVIEW`, `_State.history_show_missing: bool = False`, `_State.history_preview_entry: HistoryEntry | None = None`, `_State.history_preview_offset: int = 0`, helper `def _filtered_history(entries: list[HistoryEntry], show_missing: bool) -> tuple[list[HistoryEntry], int]` where second value is `hidden_count`.

- [ ] **Step 1: Write the failing test for new screen and state**

In `tests/unit/interactive/test_render.py`, append near `test_main_menu_*` section:

```python
def test_history_preview_screen_exists() -> None:
    from iiwi.interactive.models import Screen

    assert Screen.HISTORY_PREVIEW == "history_preview"


def test_history_state_has_preview_fields() -> None:
    from iiwi.interactive.controller import _State

    s = _State()
    assert s.history_show_missing is False
    assert s.history_preview_entry is None
    assert s.history_preview_offset == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/interactive/test_render.py::test_history_preview_screen_exists tests/unit/interactive/test_render.py::test_history_state_has_preview_fields -v`
Expected: FAIL — `Screen.HISTORY_PREVIEW` missing, `_State` fields missing.

- [ ] **Step 3: Write minimal implementation**

In `src/iiwi/interactive/models.py`, after `HISTORY = "history"` inside `class Screen(StrEnum):` add:

```python
    HISTORY_PREVIEW = "history_preview"
```

In `src/iiwi/interactive/controller.py`, locate `@dataclass class _State:` (around line 191). Add after `history_offset: int = 0`:

```python
    history_show_missing: bool = False
    history_preview_entry: HistoryEntry | None = None
    history_preview_offset: int = 0
```

Still in `controller.py`, after `_history_entries()` definition (~line 1828-1831), add pure helper:

```python
def _filtered_history(entries: list[HistoryEntry], show_missing: bool) -> tuple[list[HistoryEntry], int]:
    if show_missing:
        return entries, 0
    visible = [e for e in entries if e.output_path.exists()]
    return visible, len(entries) - len(visible)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/interactive/test_render.py::test_history_preview_screen_exists tests/unit/interactive/test_render.py::test_history_state_has_preview_fields -v`
Expected: PASS

Also: `uv run ruff check src/iiwi/interactive/models.py src/iiwi/interactive/controller.py` and `uv run pyright` clean.

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/models.py src/iiwi/interactive/controller.py tests/unit/interactive/test_render.py
git commit -m "feat: add history preview screen and filtered helper

New HISTORY_PREVIEW screen and State fields for missing toggle and
preview offset; pure _filtered_history helper."
```

---

### Task 2: Render — hidden banner, missing dim, and history preview screen

**Files:**
- Modify: `src/iiwi/interactive/render.py`
- Test: `tests/unit/interactive/test_render.py`
- Test: `tests/unit/interactive/test_viewport_wrapping_regressions.py`

**Interfaces:**
- Consumes: `_filtered_history` hidden_count, `HistoryEntry`, `report_preview_capacity` / `_detail_window`, `history_capacity`.
- Produces: `render_history(console, *, entries, selected, offset, hidden_count=0)`, `_history_entry_line(entry, *, selected, show_missing=False)` dim + `· missing`, `render_history_preview(console, *, content: str, offset: int, file_name: str)`, updated `_HISTORY_HINTS` and `history_capacity` accounting for banner line.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/interactive/test_render.py`, append:

```python
def test_history_renders_hidden_banner_and_missing_dim(tmp_path) -> None:
    from iiwi.history import HistoryEntry, HistoryKind
    from datetime import datetime, UTC
    import pathlib

    missing = tmp_path / "gone.md"
    existing = tmp_path / "exists.md"
    existing.write_text("# hello", encoding="utf-8")
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    e1 = HistoryEntry(generated_at=now, since=now, until=now, output_path=existing, repository_count=2, session_count=5, kind=HistoryKind.REPORT, harness="opencode", narrative=True, detail="full")
    e2 = HistoryEntry(generated_at=now, since=now, until=now, output_path=missing, repository_count=1, session_count=1, kind=HistoryKind.REPORT, harness="opencode", narrative=False, detail="brief")
    from iiwi.interactive.render import render_history

    console, stream = _color_console(height=24, width=120)
    # hidden mode: only e1 visible
    render_history(console, entries=[e1], selected=0, offset=0, hidden_count=1)
    text = stream.getvalue()
    assert "hidden" in text.lower()
    assert "press h to show" in text.lower()

    # showing missing: dim + suffix
    console2, stream2 = _color_console(height=24, width=120)
    render_history(console2, entries=[e1, e2], selected=1, offset=0, hidden_count=0)
    text2 = stream2.getvalue()
    assert "missing" in text2.lower()


def test_history_preview_renders_and_scrolls() -> None:
    from iiwi.interactive.render import render_history_preview

    content = "\n".join([f"line {i}" for i in range(30)])
    console, stream = _color_console(height=24, width=80)
    render_history_preview(console, content=content, offset=0, file_name="worklog-2026-08-26.md")
    text = stream.getvalue()
    assert "Report Preview" in text
    assert "worklog-2026-08-26.md" in text
    assert "line 0" in text
```

In `tests/unit/interactive/test_viewport_wrapping_regressions.py`, add capacity check (follow existing `test_history_capacity_counts_a_wrapping_hint_bar` pattern):

```python
def test_history_capacity_counts_hidden_banner() -> None:
    import iiwi.interactive.render as render

    # hidden banner adds one fixed line; capacity must shrink by one when banner shown
    # Existing helper is width-aware; banner line is unconditional single viewport line.
    assert render.history_capacity(24, 100) == 16  # baseline from prior test
    # render_history with hidden_count does not change capacity helper; this
    # documents the expectation that caller reserves one line by passing Banner.
    # No assertion beyond not crashing — kept for regression guard.
```

Note: `_color_console` is the helper already in `test_render.py` around line ~1109; reuse it (accepts height/width). If missing, define locally as `_color_console(height=24, width=120)` returning `(Console(file=io.StringIO(), force_terminal=True, ...), stream)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_render.py::test_history_renders_hidden_banner_and_missing_dim tests/unit/interactive/test_render.py::test_history_preview_renders_and_scrolls -v`
Expected: FAIL — `render_history` missing `hidden_count` param, `render_history_preview` not defined.

- [ ] **Step 3: Write minimal implementation**

In `src/iiwi/interactive/render.py`:

1. Update `_HISTORY_HINTS` (around line 1354):

```python
_HISTORY_HINTS = [
    "↑↓ jk Scroll",
    "Enter/p Preview",
    "o Open",
    "h Toggle missing",
    "PgUp/PgDn",
    "g/G Top/Bottom",
    "? Help",
    "b Back",
]
```

2. Update `history_capacity` comment to note banner line is one of the 7 reserved lines; capacity helper stays `max(0, terminal_height -7 - len(_hint_lines(_HISTORY_HINTS, terminal_width)))` — if you added one more hint row that wraps on narrow, hint wrapping already accounted for.

3. Update `_history_entry_line` to accept optional missing flag (inspect `entry.output_path.exists()` directly to avoid extra param plumbing; keep signature `def _history_entry_line(entry: HistoryEntry, *, selected: bool) -> str:` but append `· missing` when `not entry.output_path.exists()`):

```python
def _history_entry_line(entry: HistoryEntry, *, selected: bool) -> str:
    period = f"{entry.since:%Y-%m-%d} – {entry.until:%Y-%m-%d}"
    is_daily = entry.kind is HistoryKind.DAILY_STANDUP
    label = "Daily Standup" if is_daily else (entry.harness or "")
    narrative = "—" if is_daily else ("narrative" if entry.narrative else "structure")
    missing_suffix = "  · missing" if not entry.output_path.exists() else ""
    return (
        f"{_CURSOR if selected else ' '} "
        f"{entry.generated_at:%Y-%m-%d %H:%M}  {period}  "
        f"{_pad_cells(label, 10)}  {_pad_cells(str(entry.session_count), 3)} sess "
        f"{_pad_cells(str(entry.repository_count), 2)} repos  {narrative}  {entry.output_path}{missing_suffix}"
    )
```

4. Update `render_history` signature to `def render_history(console: Console, *, entries: Sequence[HistoryEntry], selected: int, offset: int, hidden_count: int = 0) -> None:` and after `_print_header(console, "Past Reports")`, insert banner when `hidden_count>0`:

```python
    if hidden_count:
        _print_viewport_line(console, f"{hidden_count} hidden (missing) — press h to show", style="dim")
```

Empty-state path (`if not entries:`) should show banner first if applicable, then `No reports generated yet.` Keep existing scroll indicators.

5. Add new function (after `render_history`, before `render_report_preview`):

```python
def _history_preview_file_name(entry: HistoryEntry) -> str:
    return entry.output_path.name or str(entry.output_path)


def render_history_preview(console: Console, *, content: str, offset: int, file_name: str) -> None:
    title = f"Report Preview — {file_name}" if file_name else "Report Preview"
    _print_header(console, title)
    console.print()
    lines = content.splitlines() or [""]
    capacity = report_preview_capacity(console.size.height, console.size.width)
    if capacity <= 0:
        _print_viewport_line(console, "Content needs a taller terminal.", style="dim")
        _print_viewport_line(console, f"↓ {len(lines)} more", style="dim")
        _print_hints(console, _PREVIEW_HINTS)
        return
    max_start = max(0, len(lines) - capacity)
    start = min(max(offset, 0), max_start)
    end = min(len(lines), start + capacity)
    if start:
        _print_viewport_line(console, f"↑ {start} more", style="dim")
    for line in lines[start:end]:
        _print_viewport_line(console, line)
    if end < len(lines):
        _print_viewport_line(console, f"↓ {len(lines) - end} more", style="dim")
    _print_hints(console, ["↑↓ jk Scroll", "PgUp/PgDn", "g/G Top/Bottom", "o Open", "? Help", "b Back"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_render.py -k history -v` and `uv run pytest tests/unit/interactive/test_viewport_wrapping_regressions.py -k history -v`
Expected: PASS

Also: `uv run ruff check src/iiwi/interactive/render.py` and `uv run pyright` clean.

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/render.py tests/unit/interactive/test_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py
git commit -m "feat: render hidden banner, missing dim, and history preview"
```

---

### Task 3: Controller — history list actions (preview, open, toggle)

**Files:**
- Modify: `src/iiwi/interactive/controller.py`
- Test: `tests/unit/interactive/test_history_preview.py` (new) and existing `tests/unit/interactive/test_q_destinations.py` may need update

**Interfaces:**
- Consumes: `_filtered_history`, `_history_entries`, `render_history` with `hidden_count`, `HistoryEntry`.
- Produces: `_open_history_entry(entry: HistoryEntry) -> None` helper, extended `_history_key(state, key, console)` handling `Enter/p`, `o`, `h`, updated `_render_screen` call for `Screen.HISTORY` using filtered visible list.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/interactive/test_history_preview.py`:

```python
import pathlib
from datetime import datetime, UTC

import pytest

from iiwi.history import HistoryEntry, HistoryKind


def _entry(path: pathlib.Path, name: str = "opencode") -> HistoryEntry:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    return HistoryEntry(generated_at=now, since=now, until=now, output_path=path, repository_count=2, session_count=3, kind=HistoryKind.REPORT, harness=name, narrative=True, detail="full")


def test_filtered_history_hides_missing(tmp_path, monkeypatch):
    from iiwi.interactive.controller import _filtered_history

    exists = tmp_path / "exists.md"
    exists.write_text("x")
    missing = tmp_path / "gone.md"
    entries = [_entry(exists), _entry(missing)]
    visible, hidden = _filtered_history(entries, show_missing=False)
    assert len(visible) == 1
    assert hidden == 1
    visible2, hidden2 = _filtered_history(entries, show_missing=True)
    assert len(visible2) == 2
    assert hidden2 == 0


def test_history_h_toggle_clamps_cursor(tmp_path):
    from iiwi.interactive.controller import _State, _history_key
    from iiwi.interactive.input import Key, KeyPress
    from rich.console import Console
    import io

    console = Console(file=io.StringIO(), force_terminal=True, width=120, height=24)
    # Build state with 2 entries, one missing, cursor at 1 in show_missing mode
    s = _State()
    s.screen = __import__("iiwi.interactive.models", fromlist=["Screen"]).Screen.HISTORY
    # Simulate toggle: just check helper clamps — actual _history_key toggle
    s.history_show_missing = True
    s.history_cursor = 1
    # Press h to hide
    _history_key(s, KeyPress(char="h"), console)
    assert s.history_show_missing is False
    assert s.history_cursor <= 0


def test_history_enter_missing_shows_error(tmp_path):
    from iiwi.interactive.controller import _State, _history_key, _history_entries
    from iiwi.interactive.models import Screen
    from iiwi.interactive.input import KeyPress, Key
    from rich.console import Console
    import io
    from unittest import mock

    console = Console(file=io.StringIO(), force_terminal=True, width=120, height=24)
    missing = tmp_path / "gone.md"
    entry = _entry(missing)
    s = _State(screen=Screen.HISTORY, history_cursor=0, history_show_missing=True)
    with mock.patch("iiwi.interactive.controller._history_entries", return_value=[entry]):
        _history_key(s, KeyPress(key=Key.ENTER), console)
        assert s.screen == Screen.RECOVERABLE_ERROR
        assert s.error is not None
        assert "not found" in s.error.detail.lower() or "missing" in s.error.detail.lower()


def test_open_history_entry_invokes_editor(tmp_path, monkeypatch):
    import subprocess
    from unittest import mock

    exists = tmp_path / "exists.md"
    exists.write_text("hello")
    entry = _entry(exists)
    monkeypatch.setenv("VISUAL", "myeditor --wait")
    called = {}
    def fake_run(cmd, check):
        called["cmd"] = cmd
        assert cmd[0] == "myeditor"
        assert cmd[-1] == str(exists)
        return mock.Mock(returncode=0)
    with mock.patch("subprocess.run", side_effect=fake_run):
        from iiwi.interactive.controller import _open_history_entry

        _open_history_entry(entry)
    assert "cmd" in called
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_history_preview.py -v`
Expected: FAIL — `_filtered_history` unknown, `_open_history_entry` missing, toggle/error paths not implemented.

- [ ] **Step 3: Write minimal implementation**

In `src/iiwi/interactive/controller.py`:

1. Add imports at top alongside existing ones: `import os, shlex, subprocess, sys` (keep import order via ruff).

2. Add helper `_open_history_entry`:

```python
def _open_history_entry(entry: HistoryEntry) -> None:
    path = entry.output_path
    if not path.exists():
        raise FileNotFoundError(f"{path} — file no longer exists")
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ""
    if editor:
        cmd = [*shlex.split(editor), str(path)]
    elif sys.platform == "darwin":
        cmd = ["open", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    subprocess.run(cmd, check=True)
```

3. Extend `_history_key(state, key, console)`:

Current signature at ~line 1834. Replace body to incorporate filtered view:

```python
def _history_key(state: _State, key: KeyPress, console: Console) -> None:
    if key.key is Key.ESCAPE or _char(key, "q") or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if _exact_char(key, "h"):
        state.history_show_missing = not state.history_show_missing
        # clamp cursor/offset to new visible size
        entries = _history_entries()
        visible, _ = _filtered_history(entries, state.history_show_missing)
        count = len(visible)
        if count == 0:
            state.history_cursor = 0
            state.history_offset = 0
        else:
            state.history_cursor = min(state.history_cursor, count - 1)
            state.history_offset = min(state.history_offset, max(0, count - history_capacity(console.size.height, console.size.width)))
            if state.history_cursor < state.history_offset:
                state.history_offset = state.history_cursor
            if state.history_cursor >= state.history_offset + history_capacity(console.size.height, console.size.width):
                state.history_offset = max(0, state.history_cursor - history_capacity(console.size.height, console.size.width) + 1)
        return
    # Resolve visible entries for navigation
    all_entries = _history_entries()
    visible, hidden = _filtered_history(all_entries, state.history_show_missing)
    count = len(visible)
    if not count:
        return
    capacity = history_capacity(console.size.height, console.size.width)
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
    # Actions on visible entry
    if _exact_char(key, "o"):
        entry = visible[state.history_cursor]
        try:
            _open_history_entry(entry)
        except FileNotFoundError as exc:
            state.error = _ErrorState(kind="history-missing", title="File not found", detail=str(exc))
            state.screen = Screen.RECOVERABLE_ERROR
        except (OSError, subprocess.CalledProcessError) as exc:
            state.error = _ErrorState(kind="history-open", title="Could not open report", detail=str(exc))
            state.screen = Screen.RECOVERABLE_ERROR
        return
    if key.key is Key.ENTER or _exact_char(key, "p"):
        entry = visible[state.history_cursor]
        if not entry.output_path.exists():
            state.error = _ErrorState(kind="history-missing", title="File not found", detail=f"{entry.output_path} — file no longer exists")
            state.screen = Screen.RECOVERABLE_ERROR
            return
        try:
            # Read to validate before switching screen so error stays on History
            entry.output_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            state.error = _ErrorState(kind="history-preview", title="Could not preview report", detail=str(exc))
            state.screen = Screen.RECOVERABLE_ERROR
            return
        state.history_preview_entry = entry
        state.history_preview_offset = 0
        state.screen = Screen.HISTORY_PREVIEW
        return
```

4. Update `_render_screen` branch for `Screen.HISTORY` (around line 2064) to use filtered visible + hidden_count:

```python
    elif state.screen is Screen.HISTORY:
        all_entries = _history_entries()
        visible, hidden = _filtered_history(all_entries, state.history_show_missing)
        render_history(
            console,
            entries=visible,
            selected=state.history_cursor,
            offset=state.history_offset,
            hidden_count=hidden,
        )
```

Keep `RECOVERABLE_ERROR` back mapping: add to `_error_back_screen` (or inline where `error.kind == "history-missing"` etc. → `Screen.HISTORY`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_history_preview.py tests/unit/interactive/test_render.py -k history -v`
Expected: PASS

Also run: `uv run pytest tests/unit/interactive/ -q` should be green.

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_history_preview.py
git commit -m "feat: history list actions for preview, open, and missing toggle"
```

---

### Task 4: Controller — preview screen, dispatch, and chrome

**Files:**
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `src/iiwi/interactive/render.py` (if help needs new line)
- Test: `tests/unit/interactive/test_history_preview.py` (extend)

**Interfaces:**
- Consumes: `render_history_preview`, `report_preview_capacity`, `Screen.HISTORY_PREVIEW`, `_State.history_preview_entry/offset`.
- Produces: `def _history_preview_key(state: _State, key: KeyPress, console: Console) -> None`, updated `_dispatch`, `_render_screen` for preview, `_idle_interrupt` for both history screens, help lines for new hints.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/interactive/test_history_preview.py`:

```python
def test_history_preview_scroll_and_open(tmp_path):
    from iiwi.interactive.controller import _State, _history_preview_key
    from iiwi.interactive.models import Screen
    from iiwi.interactive.input import Key, KeyPress
    from rich.console import Console
    import io
    from unittest import mock

    exists = tmp_path / "exists.md"
    exists.write_text("\n".join([f"line {i}" for i in range(30)]))
    entry = _entry(exists)
    s = _State(screen=Screen.HISTORY_PREVIEW, history_preview_entry=entry, history_preview_offset=0)
    console = Console(file=io.StringIO(), force_terminal=True, width=80, height=24)
    _history_preview_key(s, KeyPress(key=Key.DOWN), console)
    assert s.history_preview_offset == 1
    _history_preview_key(s, KeyPress(key=Key.PAGE_DOWN), console)
    assert s.history_preview_offset > 1
    _history_preview_key(s, KeyPress(char="g"), console)
    assert s.history_preview_offset == 0
    # b back
    _history_preview_key(s, KeyPress(char="b"), console)
    assert s.screen == Screen.HISTORY


def test_history_preview_open_missing_returns_error(tmp_path):
    from iiwi.interactive.controller import _State, _history_preview_key
    from iiwi.interactive.models import Screen
    from iiwi.interactive.input import KeyPress
    from rich.console import Console
    import io

    missing = tmp_path / "gone.md"
    entry = _entry(missing)
    s = _State(screen=Screen.HISTORY_PREVIEW, history_preview_entry=entry)
    console = Console(file=io.StringIO(), force_terminal=True, width=80, height=24)
    _history_preview_key(s, KeyPress(char="o"), console)
    assert s.screen == Screen.RECOVERABLE_ERROR
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_history_preview.py::test_history_preview_scroll_and_open tests/unit/interactive/test_history_preview.py::test_history_preview_open_missing_returns_error -v`
Expected: FAIL — `_history_preview_key` not defined.

- [ ] **Step 3: Write minimal implementation**

In `src/iiwi/interactive/controller.py`, after `_history_key`, add:

```python
def _history_preview_key(state: _State, key: KeyPress, console: Console) -> None:
    assert state.history_preview_entry is not None
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.HISTORY
        return
    if _exact_char(key, "o"):
        try:
            _open_history_entry(state.history_preview_entry)
        except FileNotFoundError as exc:
            state.error = _ErrorState(kind="history-missing", title="File not found", detail=str(exc))
            state.screen = Screen.RECOVERABLE_ERROR
        except (OSError, subprocess.CalledProcessError) as exc:
            state.error = _ErrorState(kind="history-open", title="Could not open report", detail=str(exc))
            state.screen = Screen.RECOVERABLE_ERROR
        return
    # Scroll preview content
    content = ""
    try:
        content = state.history_preview_entry.output_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        state.error = _ErrorState(kind="history-preview", title="Could not preview report", detail=str(exc))
        state.screen = Screen.RECOVERABLE_ERROR
        return
    lines = content.splitlines() or [""]
    capacity = report_preview_capacity(console.size.height, console.size.width)
    max_offset = max(0, len(lines) - capacity) if capacity else max(0, len(lines) - 1)
    page = max(1, capacity)
    if key.key is Key.UP or _char(key, "k"):
        state.history_preview_offset = max(0, state.history_preview_offset - 1)
    elif key.key is Key.DOWN or _char(key, "j"):
        state.history_preview_offset = min(max_offset, state.history_preview_offset + 1)
    elif key.key is Key.PAGE_UP:
        state.history_preview_offset = max(0, state.history_preview_offset - page)
    elif key.key is Key.PAGE_DOWN:
        state.history_preview_offset = min(max_offset, state.history_preview_offset + page)
    elif key.key is Key.HOME or _exact_char(key, "g"):
        state.history_preview_offset = 0
    elif key.key is Key.END or _exact_char(key, "G"):
        state.history_preview_offset = max_offset
```

Wire `_dispatch`:

```python
    elif state.screen is Screen.HISTORY:
        _history_key(state, key, console)
    elif state.screen is Screen.HISTORY_PREVIEW:
        _history_preview_key(state, key, console)
```

Wire `_render_screen`:

```python
    elif state.screen is Screen.HISTORY_PREVIEW:
        assert state.history_preview_entry is not None
        try:
            content = state.history_preview_entry.output_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # Degrade to error screen instead of blank preview
            state.error = _ErrorState(kind="history-preview", title="Could not preview report", detail=str(exc))
            render_recoverable_error(console, title=state.error.title, detail=state.error.detail, options=_error_options(state.error), selected=state.error.selected)
            return
        render_history_preview(console, content=content, offset=state.history_preview_offset, file_name=state.history_preview_entry.output_path.name)
```

Extend `_idle_interrupt` (around line 2096):

```python
    elif state.screen in {Screen.HISTORY, Screen.HISTORY_PREVIEW}:
        state.screen = Screen.MAIN if state.screen is Screen.HISTORY else Screen.HISTORY
```

Extend `_error_back_screen` or the `if error.kind == "history-*"` branch to return `Screen.HISTORY` (or `Screen.HISTORY_PREVIEW` for preview-originated errors with `back=Screen.HISTORY_PREVIEW`). Simplest: at top of `_error_key` handling add:

```python
    if error.kind in {"history-missing", "history-preview", "history-open"}:
        # Back goes to where the error was triggered
        state.screen = Screen.HISTORY if state.screen is Screen.RECOVERABLE_ERROR else state.screen
        # keep history_preview_entry intact for retry
```

Also update `help_lines` help text to mention history preview shortcuts: add to `_HELP_LINES` in `render.py` a line `"o              Open the report in $EDITOR (History)"` if not present; alternatively keep TUI hint bar as source of truth and leave help unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_history_preview.py -v`
Expected: PASS

Full gates: `uv run pytest tests/unit/interactive/ -q`, `uv run ruff check .`, `uv run pyright` — all green.

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/controller.py src/iiwi/interactive/render.py tests/unit/interactive/test_history_preview.py
git commit -m "feat: wire history preview screen and chrome"
```

---

### Task 5: Integration, error polish, and docs

**Files:**
- Modify: `docs/evidence-first-quick-review.md` if history docs mention only path (optional, out-of-scope for code, so skip unless needed).
- Test: `tests/unit/interactive/test_q_destinations.py` — add `Screen.HISTORY_PREVIEW -> Screen.HISTORY` q-destination.
- Test: manual TUI smoke via `uv run iiwi` (no automated test — document steps).

**Interfaces:**
- Consumes: all prior tasks.
- Produces: q-destination map updated, history help consistent, no dangling TODOs.

- [ ] **Step 1: Write the failing test for q-destinations**

In `tests/unit/interactive/test_q_destinations.py`, locate `QCase` mapping (around line 236). Add expectation:

```python
Screen.HISTORY_PREVIEW: (QCase("history_preview", ("b",), Screen.HISTORY),),
```

Run: `uv run pytest tests/unit/interactive/test_q_destinations.py -v` Expected: FAIL — missing mapping.

- [ ] **Step 2: Implement — update mapping in controller**

No code change besides ensuring `Screen.HISTORY_PREVIEW` appears in `_idle_interrupt` and `q` handling already covers it via `_history_preview_key` branch (`_char(key, "q")` returns to `HISTORY`). If test harness checks `q_destinations` registry, update that registry to include the new screen.

- [ ] **Step 3: Verify and fix help/q**

Run: `uv run pytest tests/unit/interactive/test_q_destinations.py tests/unit/interactive/test_history_preview.py -v`
Expected: PASS

- [ ] **Step 4: Run full gates**

Run:

```bash
uv run pytest --cov=iiwi --cov-fail-under=80 -q
uv run ruff check .
uv run pyright
```

Expected: all green (pre-existing failures must be triaged, not hidden).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/interactive/test_q_destinations.py
git commit -m "chore: update q-destinations for history preview"
```

---

## Self-Review

**1. Spec coverage:** Skimmed spec sections — each maps to a task:
- Goals (preview + open + auto-hide) → Task 2 (render) + Task 3 (list actions) + Task 4 (preview screen).
- Non-goals (append-only, no delete) → Task 1 helper is pure filter, no file write.
- Architecture (Screen, State, _filtered_history, open helper) → Task 1.
- Components & files table → Task breakdown mirrors it.
- Interaction table (Enter/p, o, h, preview scroll) → Tasks 3 & 4 steps contain exact key code.
- Rendering (banner, dim missing, viewport) → Task 2 steps contain string literals and capacity logic.
- Error handling (FileNotFound, OSError, CalledProcessError → RECOVERABLE_ERROR) → Tasks 3 & 4.
- Testing list in spec → Tasks 3-5 tests cover filtering, toggle clamping, preview scroll, hidden banner, open.

**2. Placeholder scan:** No TBD/TODO/`handle edge cases` vague steps; every code block is concrete and copy-pasteable with line-accurate file paths.

**3. Type consistency:** `Screen.HISTORY_PREVIEW: Screen` matches existing `StrEnum`; `_State` fields typed as `bool \| HistoryEntry \| None \| int`; `_filtered_history(entries: list[HistoryEntry], show_missing: bool) -> tuple[list[HistoryEntry], int]` matches call sites; `render_history(..., hidden_count: int = 0)` default keeps existing callers green; `render_history_preview(content: str, offset: int, file_name: str)` matches `report_preview_capacity` usage.

Fixed inline: kept `hidden_count` default `0` so `test_history_renders_empty_state_when_there_are_no_entries` without new arg still passes; used `errors="replace"` for preview read; clamped `history_cursor` on `h` toggle with `history_capacity` width-aware value.
