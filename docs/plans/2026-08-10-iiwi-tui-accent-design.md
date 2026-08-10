# Iiwi TUI Accent Design

## Goal

Give the interactive TUI a recognizable iiwi brand accent without taking over the user's terminal theme or weakening existing status semantics.

## Palette

Use terminal-safe ANSI color names rather than hard-coded RGB values:

- `bright_red`: focus, primary actions, and activity bars
- `green`: selected / included / success state (unchanged)
- `yellow`: partial selection / caution (unchanged)
- `dim`: inactive / unselected / metadata chrome (unchanged)

The bright red accent represents the vivid scarlet color of the ʻiʻiwi bird while remaining compatible with standard terminal palettes.

## Scope

Change only the three interactive renderer roles that currently use cyan:

- cursor / active row: `bold bright_red`
- unselected primary action: `bright_red`
- activity volume bar: `bright_red`

Do not change:

- terminal background
- normal text color
- selection marker colors
- warning/error semantics
- layout, navigation, labels, or shortcut behavior

## Rationale

The TUI should remain a neutral terminal interface with small brand accents, not become a full branded theme. Keeping status colors intact prevents red from replacing the established green/yellow/dim decision states.

## Testing

Renderer tests must verify:

- cursor glyphs use bright red
- unselected action text uses bright red
- activity bars use bright red
- green/yellow/dim selection markers remain unchanged

No controller tests are required because this change is renderer-only and does not alter interaction behavior.
