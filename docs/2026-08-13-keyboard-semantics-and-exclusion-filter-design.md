# Keyboard semantics and exclusion filtering design

Date: 2026-08-13
Status: Approved

Two interactive-mode fixes: unify the `q` key so every screen treats it as
"back one level", and stop rescanning the disk when a repository is excluded.

## 1. `q` means back one level

### Problem

The help screen documents `q` as "Main menu / quit from main menu", and every
screen implements `q` as a jump straight to `Screen.MAIN`. On the top-level
screens (setup, review, result) `q` and `b` already land on the same screen,
so the inconsistency only shows on the child screens:

- `OUTCOME_REVIEW`: `q` jumps two levels to MAIN and silently discards the
  whole Quick Review draft; `b` correctly returns to `SESSION_REVIEW`.
- `REPORT_PREVIEW` / `SESSION_PREVIEW`: `q` jumps to MAIN, skipping the screen
  the preview was opened from; `b` returns there.
- `HELP`: `q` jumps to MAIN instead of the screen help was opened from.
- `RECOVERABLE_ERROR`: `q` jumps to MAIN instead of the error's own back
  screen (which already offers an explicit "Main menu" option).
- `SESSION_REVIEW` entered from the report setup: `q` goes to MAIN while `b`
  goes back to `REPORT_SETUP`.

Pressing `q` in a preview or Quick Review reads as "close this view", and the
result is losing everything with no way back.

### Change

`q` behaves exactly like `b` on every screen except the main menu, where
`q`/`Esc` still exits the application:

| Screen | `q` after the change |
|---|---|
| MAIN | exit (unchanged) |
| REPORT_SETUP | MAIN (unchanged, already equals `b`) |
| SESSION_REVIEW | MAIN if `review_from_main` else REPORT_SETUP (was MAIN); still `_sync_selection` first |
| SESSION_PREVIEW | `preview_return_screen` or MAIN (was MAIN); clear `preview_return_screen` |
| OUTCOME_REVIEW | SESSION_REVIEW (was MAIN) |
| REPORT_RESULT | MAIN (unchanged, already equals `b`) |
| REPORT_PREVIEW | `preview_return_screen` or REPORT_RESULT (was MAIN); clear `preview_return_screen` |
| RECOVERABLE_ERROR | `_error_back_screen(error)` (was MAIN) |
| HELP | `help_return_screen` or MAIN (was MAIN); clear `help_return_screen` |

Text updates:

- `_HELP_LINES`: "q Main menu / quit from main menu" → "q Back / quit from the
  main menu".
- Result screen hint "q Menu" → "q Back" (render_report_result).
- Main menu hint "q Quit" unchanged.

The error screen keeps its explicit "Main menu" option, so jumping to the top
remains one extra Enter away, not lost.

Ctrl-C (`_idle_interrupt`) already follows the `b` semantics per screen and
needs no change.

### Test impact

Many existing controller tests drive `q` to reach the main menu (e.g. key
sequences ending `..., q, q`). With `q` = back, those sequences stop at the
parent screen. All such sequences must be rewritten to use `b`/`Esc` or extra
steps, and new tests added for the changed `q` destinations per screen.

## 2. Excluding a repository filters in memory

### Problem

Pressing `e` on a repository row in Review writes the exclusion to config and
then calls `_rescan_review`, which re-reads every session from disk. The
exclusion is already persisted, so the only thing the rescan achieves is
removing that repository from the current view.

### Change

`e` on the review screen no longer rescans. After `actions.exclude_repository`
succeeds:

1. Remove the repository's sessions from the current scan in memory.
2. Drop those session ids from `selection.selected_session_ids`.
3. `_clear_outcome_review` so a cached Quick Review cannot keep evidence from
   the excluded repository.
4. Keep the success message as `review_message` and stay on `SESSION_REVIEW`.

`R` (rescan) remains a full disk re-read — it is the user's explicit request.

### Implementation

- New pure function `without_repository(scan, repository_id) -> ScanResult` in
  `src/iiwi/interactive/selection.py` (mirrors `SelectionState.filtered_scan`
  but removes one repository's sessions instead of keeping a session-id set).
  `loaded_session_count` shrinks accordingly; `excluded_session_count`,
  `failed_session_count` and `warnings` carry over unchanged.
- `SelectionState` gains `exclude_repository(repository_id)` that applies the
  function to its own scan and prunes `selected_session_ids`.
- `_review_key`'s `e` branch calls the selection method instead of
  `_rescan_review`; cursor handling, `review_message` and error handling stay
  as they are.

Future scans still respect the persisted config exclusion (the settings file
remains the source of truth, written by `exclude_repository`).

## Testing

- Unit tests for `without_repository` (repo removed from both structures,
  counts updated, other repos untouched, unknown id).
- Controller tests for the new `q` destinations per screen (drive key
  sequences, assert the rendered screen).
- Controller test: `e` on a repository row removes it without a rescan
  (`scan` counter unchanged) and keeps the message.
- Update all existing `q`-driven test sequences.

## Out of scope

- History view (PR #96, design only).
- Report-type cycling and setup label changes (separate design).
