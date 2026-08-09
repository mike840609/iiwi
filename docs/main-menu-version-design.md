# Main Menu Version Display Design

**Date:** 2026-08-09

## Summary

Show the installed version in the corner of the main menu's title row, the
way `gh`, `k9s`, and lazygit put status information in their title rows.
The version stays out of the subtitle, which reverts to its plain
description.

`agent-worklog --version` remains the authoritative, script-friendly source
of the version; the title row is a glanceable copy for the interactive flow,
where it pairs with the `update` command.

## Goals

- Show `v<version>` in the main menu title row, right-aligned and dim, on the
  same line as `Agent Worklog`.
- Keep every other screen unchanged: `_print_header` and its callers are
  untouched.
- Degrade gracefully on narrow terminals: when title + version cannot fit,
  the title wins and the version is omitted. `--version` stays the complete
  source.
- Keep the subtitle as the plain description line it was before the earlier
  `· v0.8.0` experiment.

## Design

`render_main_menu` (in `src/agent_worklog/interactive/render.py`) builds its
own title line instead of handing a plain string to `_print_header`:

- Title text: `Agent Worklog` in the existing bold style.
- Version text: `v{__version__}` in the existing dim style, right-aligned by
  padding with spaces so the pair spans exactly `console.size.width`.
- If `cell_len("Agent Worklog") + 1 + cell_len(version)` exceeds the console
  width, print the bare title line and skip the version.
- `__version__` is imported from `agent_worklog` at module top; the package
  `__init__` only defines the constant, so there is no import cycle.
- The rule and subtitle lines below are printed exactly as `_print_header`
  prints them today.

### Testing

- A width-100 console renders the version on the same line as the title.
- A narrow console (title + version cannot fit) renders the title without
  the version.
- Existing main-menu rendering and painting tests stay green.

## Out of Scope

- Version display on any other screen (setup, review, browser, results).
- Changing `--version` output or the update command.
- Terminal compatibility handling (#5 from the mole comparison) — unrelated.
