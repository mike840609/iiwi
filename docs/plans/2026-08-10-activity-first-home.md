# Activity-First Interactive Home Implementation Plan

> **For agentic workers:** implement task-by-task with test-first changes and verify the full CI matrix before marking complete.

**Goal:** Make the bare `iiwi` home lead with reviewing agent activity instead of report generation, while keeping report generation and all direct CLI commands available.

**Architecture:** Keep the existing main-menu renderer and controller state machine. Change only the main-menu information architecture and dispatch order: activity browsing becomes the first/default action, report generation becomes the second action, and diagnostic/settings actions remain available. No service or persistence behavior changes.

**Tech Stack:** Python 3.11+, Typer, Rich, pytest, Ruff, Pyright.

## Global Constraints

- Branch is independent and starts from `main`.
- Direct CLI behavior is unchanged.
- Existing wordmark, version, project link, viewport behavior, numeric shortcuts, and keyboard navigation remain intact.
- Main subtitle becomes `See what your agent did`.
- Main menu order is `Review Activity`, `Generate Report`, `Check Setup`, `Settings`.
- `Review Activity` enters the existing activity browser using configured defaults.
- `Generate Report` enters the existing report setup flow.

---

### Task 1: Lock the activity-first contract with tests

**Files:**
- Create: `tests/unit/interactive/test_activity_first_home.py`

**Interfaces:**
- Consumes: `render_main_menu`, `run_interactive`, `InteractiveActions`.
- Produces: regression coverage for copy, ordering, numeric shortcut `1`, and numeric shortcut `2`.

- [ ] Write a rendering test asserting `See what your agent did`, `▶ Review Activity`, and that `Review Activity` appears before `Generate Report`.
- [ ] Write a controller test asserting shortcut `1` scans immediately without entering the report setup flow.
- [ ] Write a controller test asserting shortcut `2` creates a report draft and allows Back to return to main.
- [ ] Open/update the PR and verify GitHub Actions fails because the production menu still uses the old report-first contract.

### Task 2: Implement the activity-first home

**Files:**
- Modify: `src/iiwi/interactive/render.py`
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `docs/cli-reference.md`

**Interfaces:**
- `main_menu_options()` continues returning four display labels.
- `_main_key(...)` continues supporting `1`–`4`, arrows/Vim navigation, Enter, Esc, and q.

- [ ] Change `_MAIN_OPTIONS`, `_MAIN_DESCRIPTIONS`, and `_MAIN_SUBTITLE` to the activity-first copy.
- [ ] Swap controller dispatch for cursor positions 0 and 1 so `Review Activity` calls the existing browse loader and `Generate Report` calls `_new_report`.
- [ ] Update the interactive-mode documentation to describe the new order without changing direct subcommands.
- [ ] Verify targeted tests pass.
- [ ] Verify the full GitHub Actions CI matrix passes on Python 3.11, 3.12, and 3.13.

### Task 3: Review scope

- [ ] Confirm the diff contains only home information architecture, tests, and matching docs.
- [ ] Confirm Browse/Review unification, advanced-setting collapse, and footer simplification are not included in this PR.
