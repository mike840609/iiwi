# Design: Disabled-harness settings read as inactive in the settings editor

Date: 2026-08-25
Status: approved (pending implementation)

## Problem

In the interactive settings editor, rows under a disabled harness still render
at full brightness and accept edits. `harnesses.claude_code.projects_directory`
looks alive while `harnesses.claude_code.enabled` is `false`, even though the
value cannot affect any run. Nothing on screen distinguishes an inert row from
a live one.

The Generate Report screen already solves this exact problem for one row:
Sanitize shows `N/A`, renders dim when unfocused, explains itself in the detail
line ("Only OpenCode can redact on export, so this does nothing here."), and
the controller silently ignores its keys when the harness is not OpenCode.
This design reuses that pattern for every harness-dependent settings row.

## Decision

A row whose owning harness is disabled is **dimmed, explained, and inert**.
Grayed out means not actionable: to edit a sub-setting, enable the harness
first. Rejected alternatives: a passive `[off]` tag (annotates but does not
de-emphasize), collapsing disabled sections (hides information and prevents
pre-configuring before enabling).

## Changes

### `src/iiwi/interactive/settings.py`

- `SettingsRow` gains one field: `disabled_reason: str = ""`.
- `build_settings_rows()` reads all current values first (one pass over
  `config_store.describe_settings()`), then fills `disabled_reason` when:
  - the key starts with one of the three harness prefixes
    (`harnesses.opencode.`, `harnesses.claude_code.`, `harnesses.codex.`),
  - the key is **not** that section's own `.enabled` row,
  - and the section's `enabled` value resolves to `"false"`.
- The reason string names the harness and the key that re-enables it, e.g.
  `"Claude Code is disabled; enable harnesses.claude_code.enabled to make this take effect."`
- Nested keys (`harnesses.opencode.cli.*`) are covered by the prefix rule.
- Non-harness keys (`report.*`, `narrator.*`) never get a reason.

### `src/iiwi/interactive/render.py`

- `_settings_display_items`: an unfocused row with a `disabled_reason` renders
  its whole line (label and value) in `"dim"`; the focused row keeps
  `_CURSOR_STYLE` so keyboard position stays visible.
- `render_settings` detail line precedence becomes:
  `error` > locked message > `row.disabled_reason` > `_SETTINGS_HELP`.
  Selecting an inert row states why it cannot change and which key flips it.

### `src/iiwi/interactive/controller.py`

- `_settings_key` early-return widens from `if row.locked:` to
  `if row.locked or row.disabled_reason:` — no ←→ cycling, no inline editor.
- Liveness is free: `_persist_setting` already rebuilds all rows after every
  write, so flipping `enabled` back to `true` restores full color and
  editability on the same keystroke.

## Out of scope

- No `[off]` suffix tag, no collapsible sections.
- No CLI changes: `iiwi config list` / `iiwi config set` keep their behavior;
  the config file remains writable by hand.

## Tests

- `tests/unit/interactive/test_settings.py`: reason set on sub-rows when
  `enabled=false`; absent on the `.enabled` row itself, on non-harness rows,
  and everywhere when `enabled=true`.
- `tests/unit/interactive/test_render.py`: inert unfocused rows render dim;
  the detail line shows the reason instead of normal help text.
- `tests/unit/interactive/test_settings_controller.py`: ←→ and Enter do
  nothing on an inert row; after re-enabling the harness, edits work again.
