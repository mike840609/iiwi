# Settings Editor

**Date:** 2026-08-13

## Summary

The Settings entry in the interactive menu drops into the linear
`iiwi config init` wizard: one free-text prompt per setting. The page makes
users nervous because a blank line never says what belongs there. Two
settings (`model`, `exclude_repositories`) even default to an empty `[]`
bracket, and none of the boolean, report-type, or timezone settings hint at
their valid choices. This design replaces the Settings entry with a
full-screen editor in the same style as the Generate Report screen: every
setting is a row showing its current value, choice fields cycle with `←→`,
free-text fields edit inline on Enter, and changes write to the settings
file immediately.

## Goals

- Every setting row shows its current value — never a blank.
- Settings with a fixed set of choices (`enabled`, `sanitize`,
  `quick_review_report_type`, `source`, timezone) list and cycle those
  choices with `←→`.
- Settings without fixed choices (model, paths, numbers,
  `exclude_repositories`) edit inline on Enter with the current value
  pre-filled.
- Changes persist immediately through the existing `config_store`
  machinery, so `config list` and later runs see them with no extra step.
- Environment-variable-sourced values display honestly as
  `[environment]` and stay read-only, because writing them to the file
  would silently do nothing.
- The interactive Settings entry returns to the main menu when done,
  instead of reporting "Settings editor finished."

## Non-goals

- No change to the CLI `iiwi config init` / `config set` / `config unset`
  commands; the linear wizard remains the way to walk settings from a plain
  terminal (no TUI loop).
- No new configuration keys, defaults, or validation rules.
- No staged writes or undo; a change is written the moment it is made.
- No model-choice lists; opencode's model space changes faster than a
  curated list can track it.

## Design

### 1. New screen

- `Screen.SETTINGS = "settings"` added to the `Screen` enum
  (src/iiwi/interactive/models.py).
- `_State` gains a settings block: `settings_cursor: int = 0`,
  `settings_values: dict[str, str]` (key → resolved value), and a
  line-editor buffer (`settings_edit: str | None`) plus
  `settings_edit_error: str | None` for inline editing.
- The main menu's Enter dispatch (`_main_key`) branch for the Settings
  row no longer calls `actions.edit_settings()`; it sets
  `state.screen = Screen.SETTINGS` and loads the rows (see §2).
- `_dispatch` routes `Screen.SETTINGS` to a new `_settings_key` handler;
  the Ctrl-C `_idle_interrupt` branch returns to `Screen.MAIN`.

### 2. Rows

Rows are derived from `config_store.setting_keys()` so a new setting in
`config.py` appears here without a hand-kept list, and each row carries
its resolved value from `config_store.describe_settings()` (the same
source `config list` uses, so environment/file/default precedence and
source labels match exactly).

Rows split by the setting's annotation:

- **Choice rows** (`bool`, the `ReportType` StrEnum, and the fixed
  `source` string): `←→` cycles the choices and writes the new value
  immediately. The row renders every choice at once, separated by ` / `,
  with the choice in force highlighted (`bold cyan`, the cursor style)
  and the rest dim — so the user sees the full option list, never a lone
  value.
- **Edit rows** (paths, numbers, `model`, `exclude_repositories`,
  `executable`, `output_directory`): Enter opens an inline editor. These
  rows show only their current value, because their option space is open.
- **Timezone row**: `←→` cycles a curated shortlist
  (`Asia/Taipei`, `Asia/Shanghai`, `Asia/Tokyo`, `Asia/Singapore`,
  `Europe/London`, `Europe/Berlin`, `America/New_York`,
  `America/Los_Angeles`, `UTC`); Enter edits any IANA zone. The row always
  displays only the actual value in force — nine zones would not fit one
  row — and `←→` still steps through the shortlist.
- **Environment-sourced rows**: value shown with a `[environment]` tag and
  the row is locked — `←→` and Enter do nothing on it.

### 3. Rendering

New `render_settings(console, *, rows, selected, source_tags, editing)`
in src/iiwi/interactive/render.py, in the same style as
`render_report_setup`:

- Header `"Settings"` via `_print_header`, plus a dim line with the
  settings file path (from `config_store.config_file_path()`).
- One viewport line per setting: `▶ label` + padded value column. Choice
  rows render their full option list (`true / false`,
  `manager / engineering`) with the active choice in `_CURSOR_STYLE` and
  the rest dim. Empty values render as dim `(default)` instead of blank,
  so nothing on the page is empty.
- The cursor row uses `_CURSOR_STYLE`; a dim `[environment]` tag follows
  locked values.
- The bottom line is the existing `_setup_help`-style per-row detail:
  for choice rows the choices list (`true / false`), for edit rows a short
  purpose line, for locked rows "Set by the IIWI_* environment variable."
- While the inline editor is open, a prompt line renders at the bottom:
  `key [current]: <typed text>`; the detail line becomes any validation
  error.
- Hints: `↑↓ jk`, `←→ Cycle`, `Enter Edit`, `? Help`, `b Back`.

### 4. Inline editor

Enter on an edit row opens the editor with the current value pre-filled.
Inside the cbreak loop the controller accumulates `KeyPress.char` into
`settings_edit`; Backspace deletes, Escape cancels, Enter validates and
writes:

- A trimmed empty answer restores the default (`config_store.unset_value`),
  matching `config set <key> ""`.
- `config_store.validate_value` runs before writing; on failure the
  editor stays open with the error shown on the detail line, and the
  stored value is untouched.

### 5. Writing

- Choice cycle and editor confirm both call
  `config_store.set_value(key, value)` immediately (skipping it when the
  value did not change), then refresh `settings_values`.
- A write failure (unreadable/unwritable settings file) surfaces as an
  error state with the `ConfigurationError` message; the row keeps its
  old value.
- `b` / `Esc` / `q` return to `Screen.MAIN`. Nothing further to save —
  the writes already happened.

## Error handling

- Invalid typed values: refused by `validate_value` before any disk
  write; the editor stays open and shows the reason.
- Settings file write failure: error state with the underlying message,
  old value retained.
- No history of edits; an accidental change is undone by cycling back or
  editing the value again (the same immediacy the rest of the menu has).

## Testing

- Rendering: every setting key renders as a row; empty values show
  `(default)`; environment-sourced rows show `[environment]`; the file
  path header shows; choice rows list every option separated by ` / `
  with only the choice in force highlighted and the rest dim; the
  timezone row shows only its current value.
- Choice cycling: `←→` on `enabled`, `sanitize`, `quick_review_report_type`,
  and timezone writes the next choice through `config_store` and updates
  the row; an unchanged value writes nothing.
- Timezone: cycling reaches the shortlist; Enter edits an arbitrary zone.
- Inline editor: Enter pre-fills the current value; typing + Enter writes;
  empty + Enter unsets; Escape cancels; Backspace edits; an invalid value
  keeps the old value, shows the error, and stays open.
- Locked rows: `←→` and Enter on an environment-sourced row do nothing.
- Navigation: cursor moves and wraps; `b`/`Esc`/`q` return to the main
  menu; Ctrl-C returns to MAIN.
- Integration: selecting Settings in the main menu opens `Screen.SETTINGS`
  (replacing the tests that assert `config_init` is called and the
  "Settings editor finished." result screen).
