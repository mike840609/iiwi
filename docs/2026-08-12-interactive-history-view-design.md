# Interactive History View

**Date:** 2026-08-12

## Summary

The interactive mode writes every generated report to the append-only history
log (`iiwi.history.append_history`) but has no way to read it back. Finding a
past report's path forces the user to leave the TUI and run `iiwi history` on
the CLI. This design adds a read-only history list to the main menu, named
`History` to match the CLI command.

## Goals

- View all past report entries (and their output paths) from inside the TUI.
- Entry point lives on the main menu, always reachable — a user who has not
  just generated a report must still be able to find past reports.
- Name the menu item `History`, matching the CLI command `iiwi history`, so
  knowledge transfers between the two surfaces.
- Reuse existing history data (`read_history`) and existing screen mechanisms
  (RECOVERABLE_ERROR path display, viewport scrolling) rather than new
  infrastructure.

## Non-goals

- No changes to history logging, storage format, or CLI `iiwi history`.
- No report preview from the history list. The list only reveals paths.
- No path absolutization; recorded paths display as stored, matching the CLI.
- No editing, deleting, or retrying past reports from the list.
- No entry on the report result screen: one entry point keeps the navigation
  graph small, and the main menu is reachable from the result screen anyway.

## Design

### 1. Menu entry

`_MAIN_OPTIONS` (src/iiwi/interactive/render.py:51) gains a fifth option,
placed after the functional actions and before the two non-functional rows
(Check Setup, Settings), which close the menu:

```
["Review Activity", "Generate Report", "History", "Check Setup", "Settings"]
```

The main menu renders options automatically through
`main_menu_options()`, so no render change is needed for the menu itself.
`_MAIN_DESCRIPTIONS` gains a `History` row explaining what the screen shows.

### 2. New screen

- `Screen.HISTORY = "history"` added to the `Screen` enum
  (src/iiwi/interactive/models.py).
- `_State` gains `history_cursor: int = 0` (selected entry) and
  `history_offset: int = 0` (viewport scroll), both reset to 0 on entry.
- `_dispatch` routes `Screen.HISTORY` to a new `_history_key` handler; the
  Ctrl-C `_idle_interrupt` branch returns to `Screen.MAIN`.
- The main menu's Enter dispatch (`_main_key`) gains a branch: selecting
  "History" sets `state.screen = Screen.HISTORY` and
  `state.history_offset = state.history_cursor = 0`.

### 3. Data

Call the existing `read_history()` (src/iiwi/history.py:77), which already
skips unreadable lines. Entries render newest first, the same ordering as the
CLI history table.

### 4. Rendering

New `render_history(console, *, entries, selected, offset)` in
src/iiwi/interactive/render.py:

- Header `"Past Reports"` via the existing `_print_header`.
- One viewport line per entry with the CLI table's columns: Generated,
  Period, Harness, Sessions, Repos, Narrative, Path. Columns align manually
  with padded labels (matching the existing `_print_option_line` /
  `_print_viewport_line` style) rather than a Rich Table, so the screen
  paints inside the frame-capture viewport machinery like every other screen.
- The cursor row uses `_CURSOR_STYLE`; entry rows are dim, mirroring the
  option-list look.
- Scrolling reuses the same bounds logic as `render_report_preview`
  (capacity from `console.size.height`, `PgUp/PgDn`, `g/G` top/bottom,
  `j/k/↑/↓`).
- Hints: `↑↓ jk Scroll`, `Enter Path`, `? Help`, `b Back`.
- Empty state: when no entries exist, render a single dim line ("No reports
  generated yet.") and ignore Enter, so a fresh install or dry-run-only user
  never sees an empty table.

### 5. Path display

Enter on a history row opens the existing RECOVERABLE_ERROR mechanism (the
same one "Print report path" uses) with the entry's `output_path`, title
"Report path". Back/`b` returns to the history screen.

## Error handling

- Corrupt history lines are already skipped by `read_history`; no new failure
  path.
- History is read per entry into the screen, not cached in state, so a fresh
  read on each render keeps the list current if a report was just generated.
  (Entries are immutable dataclasses; re-reading is cheap at report scale.)
- Long paths fold instead of truncating, matching the CLI table's
  `overflow="fold"` behavior.

## Testing

- Main menu shows five options; Enter on "History" opens `Screen.HISTORY`
  with cursor at 0.
- History rows render newest first; cursor moves and wraps across entries.
- Enter on a row shows the entry's output path via RECOVERABLE_ERROR; Back
  returns to HISTORY; `q`/Esc/b return to MAIN.
- Empty history renders the empty-state line and Enter does nothing.
- Scroll bounds: offset clamps at both ends; `g`/`G` jump to top/bottom.
- Ctrl-C on HISTORY returns to MAIN.
