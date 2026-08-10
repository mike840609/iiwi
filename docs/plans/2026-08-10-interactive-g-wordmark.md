# Interactive G2 Wordmark Implementation Plan

**Goal:** Replace the interactive main-menu ASCII banner with the selected six-line G2-style `iiwi` wordmark while preserving the existing compact fallback on small terminals.

**Architecture:** Keep the runtime change inside `iiwi.interactive.render`. The main menu already gates the wordmark by terminal size and renders every line through the no-wrap viewport helper, so the implementation changes the `_WORDMARK` constant and its size assumptions only. README assets and terminal examples are updated separately to match the shipped UI. No controller, command, report, or non-interactive output changes.

**Tech Stack:** Python, Rich, pytest, SVG.

## Constraints

- Interactive main menu only.
- Use the selected G2 wordmark exactly as approved.
- Keep the version flush-right on the final wordmark row.
- Preserve the one-line `Iiwi` fallback when the terminal cannot fit the full wordmark.
- Keep all banner rows no-wrap / ellipsis-safe.
- Keep English and Traditional Chinese README visuals in sync with the runtime banner.

## Implementation

- [x] Update the main-menu render test so the previous wordmark fails the expected assertion.
- [x] Replace `_WORDMARK` with the six-line G2 wordmark and update minimum width for its 24-cell lower rows.
- [x] Update the fixed-screen viewport regression for the exact-width G2 gate.
- [x] Add a G2 README hero asset and refresh both README terminal examples.
- [ ] Run the full test, lint, type-check, and package-build matrix through CI.
- [ ] Review the final PR diff for interactive-only runtime scope and documentation consistency.
