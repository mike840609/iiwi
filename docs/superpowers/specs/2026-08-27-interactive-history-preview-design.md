# Interactive History Preview — Design

**Date:** 2026-08-27
**Status:** Draft — pending spec review before implementation
**Related:** `docs/2026-08-12-interactive-history-view-design.md`, `plans/2026-08-12-interactive-history-view.md`
**Requested improvement:** History page read-only list only shows paths; user wants in-TUI preview + one-click open, with missing files auto-filtered.

## Summary

Extend the existing interactive `History` screen (main menu → `Screen.HISTORY`) from a path-only list to a previewable archive. History remains append-only (`iiwi.history.append_history` / `read_history`); all new behavior is view-layer filtering and file-reading. A new `Screen.HISTORY_PREVIEW` reuses the existing viewport/preview machinery to render the actual Markdown file. Missing reports are hidden by default with a count hint and a toggle to show them.

## Goals

- Preview any past report's Markdown inside the TUI without leaving `iiwi` (scrollable, same viewport guarantees as `Report Preview`).
- One-key open the selected report in the user's editor (`$VISUAL` → `$EDITOR` → `xdg-open`/`open`).
- Auto-hide entries whose `output_path` no longer exists; surface how many are hidden and allow toggling.
- Keep `Enter` as the primary "see content" action (user confirmed: `Enter = Preview`, path shown inside preview).

## Non-goals

- No writes to `history.jsonl` (no delete/clear, no rewrite, no lock). Filtering is view-only, preserving the append-only contract noted in `src/iiwi/history.py:1-6`.
- No copy-path clipboard (OSC 52), no search/filter by harness/date, no history editing.
- No change to `iiwi history` CLI command or `history.jsonl` storage format.
- No change to history logging in `src/iiwi/interactive/cli_actions.py` (append calls remain suppressed on `OSError`).

## Architecture

### Screen and state

```python
# src/iiwi/interactive/models.py
class Screen(StrEnum):
    HISTORY = "history"
    HISTORY_PREVIEW = "history_preview"  # new

# src/iiwi/interactive/controller.py :: _State
@dataclass
class _State:
    history_cursor: int = 0
    history_offset: int = 0
    history_show_missing: bool = False       # new — default hide missing
    history_preview_entry: HistoryEntry | None = None  # new
    history_preview_offset: int = 0          # new
```

`history_show_missing=False` is reset to `False` on entry via main menu (same as `history_cursor/offset` today at `controller.py:590-591`). `Ctrl-C` / `b` / `q` behavior follows existing `_idle_interrupt` pattern.

### Data flow

```
_history_entries() = list(reversed(read_history()))   # controller.py:1828 — unchanged
visible, hidden_count = _filtered_history(entries, show_missing)
render_history(console, entries=visible, hidden_count=hidden_count, ...)
# Preview reads the file on demand, not on list render:
content = entry.output_path.read_text(encoding="utf-8", errors="replace")
render_history_preview(console, content=content, offset=state.history_preview_offset)
# Open delegates to OS/editor, result shown via RECOVERABLE_ERROR on failure
```

`_filtered_history` is a pure helper:

```python
def _filtered_history(entries: list[HistoryEntry], show_missing: bool):
    if show_missing:
        return entries, 0
    visible = [e for e in entries if e.output_path.exists()]
    return visible, len(entries) - len(visible)
```

Re-reading `read_history()` per key/render is retained (cheap at report scale, keeps list current after a just-generated report, as noted in the original design's Error handling).

### File open

```python
def _open_with_editor(path: Path) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ""
    if editor:
        cmd = shlex.split(editor) + [str(path)]
    elif sys.platform == "darwin":
        cmd = ["open", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    subprocess.run(cmd, check=True)
```

Failure raises to `RECOVERABLE_ERROR` (`kind="history-open"`). No shell injection: `shlex.split` only on the env var, path passed as separate arg.

## Components & Files

| File | Change |
|------|--------|
| `src/iiwi/interactive/models.py` | Add `HISTORY_PREVIEW` to `Screen` |
| `src/iiwi/interactive/controller.py` | New state fields; new `_filtered_history`, `_history_preview_key`, `_open_history_entry`; extend `_history_key` for `p`/`Enter`→preview, `o`→open, `h`→toggle; new `_history_preview_key` for scrolling/open/back; wire `_dispatch`, `_render_screen`, `_idle_interrupt`; update `history_capacity` usage to include hidden banner in fixed-line count |
| `src/iiwi/interactive/render.py` | `render_history` signature adds `hidden_count: int = 0`; header area prints `↑ N hidden (missing) — press h to show` when `hidden_count>0`; `_history_entry_line` dim + `· missing` suffix when `not path.exists()` and `show_missing` is true; new `render_history_preview` (header `Report Preview — <filename>`, uses `report_preview_capacity` / `_detail_window`); update `history_capacity` / `_HISTORY_HINTS` to include `p Preview`, `o Open`, `h Toggle` |
| `src/iiwi/history.py` | No change |
| `src/iiwi/interactive/cli_actions.py` | No change |

## Interaction & Key Bindings

### History list (`Screen.HISTORY`)

Retains: `↑↓`/`j/k`, `PgUp/PgDn`, `g`/`G` top/bottom, `b`/`q`/`Esc` → `MAIN`, `?` → help.

Additions:

| Key | Action | Condition |
|-----|--------|-----------|
| `Enter` / `p` | Enter `HISTORY_PREVIEW` for selected `visible` entry | Entry file exists; else show `RECOVERABLE_ERROR: File not found — <path>` and stay on History |
| `o` | Open `visible` entry with editor | File exists; else same File-not-found error |
| `h` | Toggle `history_show_missing` | Recompute `visible`/`hidden_count`; clamp `history_cursor`/`offset` to new `len(visible)`; preserve logical selection when possible |

`_move`, page, home/end, and `history_offset` clamping mirror `controller.py:1842-1857`.

### History Preview (`Screen.HISTORY_PREVIEW`)

| Key | Action |
|-----|--------|
| `↑`/`k`, `↓`/`j` | Scroll one line (`history_preview_offset ±1`, clamped to `max_offset`) |
| `PgUp`/`PgDn` | Page = `capacity` |
| `g`/`G` | Top / bottom |
| `o` | Open same `history_preview_entry` with editor |
| `b`/`q`/`Esc` | Back to `HISTORY` (restore cursor/offset) |
| `?` | Help |

Viewport `capacity = report_preview_capacity(height, width)` (already width-aware for hint wrapping). Scroll state stored in `state.history_preview_offset`.

## Rendering

### History list

```
Past Reports
════════════════════════════════════════
2 hidden (missing) — press h to show   # dim, only when hidden_count>0

▶ 2026-08-26 14:30  2026-08-20 – 2026-08-26  OpenCode    12 sess  3 repos  structure  reports/worklog-...md
  2026-08-25 09:12  2026-08-19 – 2026-08-25  Daily Standup   8 sess  2 repos  —        reports/daily-...md
  2026-08-24 18:05  2026-08-20 – 2026-08-26  Claude Code  4 sess  1 repos  narrative  reports/worklog-...md  · missing  # dim, only when show_missing

↑↓ jk Scroll  Enter/p Preview  o Open  h Toggle  PgUp/PgDn  g/G Top/Bottom  ? Help  b Back
```

- `_history_entry_line` gains a trailing `· missing` (dim) when `not entry.output_path.exists()`. Cursor row uses `_CURSOR_STYLE`.
- `visible` is `len(entries) - hidden_count` when filtered. `selected`/`offset` are indices into `visible`, not global entries.
- Empty history: `No reports generated yet.` (dim), hint bar without `Enter/p/o/h`, `Enter` does nothing — same as today.
- Truncation: one viewport line per entry via `_print_viewport_line` (ellipsis, never wrap), preserving row-indexed painting.
- Header fixed lines for `history_capacity` updated to account for the optional hidden banner line.

### Preview

```
Report Preview — worklog-2026-08-20_2026-08-26.md
════════════════════════════════════════
# Weekly engineering update
...
↑ 12 more / ↓ 40 more as needed (dim)

↑↓ jk Scroll  PgUp/PgDn  g/G Top/Bottom  o Open  ? Help  b Back
```

Implement as `render_history_preview(console, *, content: str, offset: int, file_name: str)`, internally same as `render_report_preview` (splitlines, `_detail_window`, indicator lines). Title uses `entry.output_path.name`. Full path available in the content's first dim line or via `o` failure detail; `Enter=Preview` addresses "main path is content" request.

## Error Handling

- Missing/toggled-hidden entry selected → `p`/`Enter`/`o` routes to `RECOVERABLE_ERROR` (`kind="history-missing"`, title `File not found`, detail `path + " — file no longer exists"`). `Back` returns to `HISTORY`; cursor unchanged.
- `read_text` failure (`OSError`, `PermissionError`, `UnicodeDecode` with `errors=replace` still possible on binary) → `RECOVERABLE_ERROR` (`kind="history-preview"`, title `Could not preview report`, detail `str(exc)` redacted via `redact_text`).
- `subprocess.run` failure for `o` → `RECOVERABLE_ERROR` (`kind="history-open"`, detail includes command and return code or `No editor configured`).
- Corrupt `history.jsonl` lines already skipped by `read_history`; no new handling.
- Disk full / read-only home: history read is best-effort; preview/open failures are recoverable errors, never crash the TUI (same `contextlib.suppress` posture as `cli_actions.generate` bookkeeping).
- `_idle_interrupt` (Ctrl-C) on `HISTORY` → `MAIN`; on `HISTORY_PREVIEW` → `HISTORY`.

## Testing

Unit tests mirror `tests/unit/interactive/test_render.py` and `test_viewport_wrapping_regressions.py` history sections:

- `test_history_filters_missing_by_default` — mix of existing/missing entries, `show_missing=False` yields only existing in render.
- `test_history_toggle_shows_missing_dimmed` — `show_missing=True` renders missing with `· missing` and dim.
- `test_history_hidden_banner_counts` — `hidden_count` printed only when >0, correct number.
- `test_history_preview_renders_content_and_scrolls` — preview with `capacity` 10, 30-line content, correct `↑/↓` indicators.
- `test_history_preview_handles_missing_and_read_error` — `Enter` on missing / unreadable returns `RECOVERABLE_ERROR`.
- `test_history_open_invokes_editor` — monkeypatch `subprocess.run` / env, assert called with split editor + path.
- `test_history_h_toggle_clamps_cursor` — cursor at last visible, toggle on/off, cursor clamped correctly.
- Viewport regression: `history_capacity` counts wrapping `_HISTORY_HINTS` + optional hidden banner.

Run: `uv run pytest tests/unit/interactive/test_render.py -k history -v` + new `tests/unit/interactive/test_history_preview.py`.

## Alternatives Considered

- **A. Minimal reuse (p=preview, no filter):** Rejected — leaves missing entries polluting the list, no auto-clean.
- **C. Writable history (delete entries):** Rejected — violates append-only guarantee in `history.py`, needs file locking, risks data loss; filtering solves the UX without storage mutation.

## Open Questions for Review

- None — `Enter=Preview` and auto-hide confirmed by user. Ready for implementation planning.
