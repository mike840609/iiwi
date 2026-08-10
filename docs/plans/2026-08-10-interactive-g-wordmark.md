# Interactive G Wordmark Implementation Plan

**Goal:** Replace the interactive main-menu ASCII banner with the selected six-line G-style `iiwi` wordmark while preserving the existing compact fallback on small terminals.

**Architecture:** Keep the change inside `iiwi.interactive.render`. The main menu already gates the wordmark by terminal size and renders every line through the no-wrap viewport helper, so the implementation only changes the `_WORDMARK` constant and its size assumptions. No controller, command, report, or non-interactive output changes.

**Tech Stack:** Python, Rich, pytest.

## Constraints

- Interactive main menu only.
- Use the selected G wordmark exactly as approved.
- Keep the version flush-right on the final wordmark row.
- Preserve the one-line `Iiwi` fallback when the terminal cannot fit the full wordmark.
- Keep all banner rows no-wrap / ellipsis-safe.

## Implementation

- [ ] Update the main-menu render test first so the old wordmark fails the expected assertion.
- [ ] Replace `_WORDMARK` with the six-line G wordmark and update comments/minimum width assumptions for the new dimensions.
- [ ] Update the fixed-screen viewport regression to account for two additional banner rows.
- [ ] Run the interactive render/regression tests and then the full test suite through CI.
- [ ] Review the final PR diff for interactive-only scope and unchanged fallback behavior.
