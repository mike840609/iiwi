# Simplified Interactive Footer Implementation Plan

> **For agentic workers:** implement task-by-task with test-first changes and verify the full CI matrix before marking complete.

**Goal:** Keep power-user shortcuts working while reducing the always-visible footer to the few controls needed for the current task.

**Architecture:** Change renderer hint lists only. Controller key handling remains untouched, so hidden shortcuts keep working and stay documented in the Help screen. Viewport calculations continue deriving reserved height from the same hint lists, so simplifying them also returns vertical space to content.

**Tech Stack:** Python 3.11+, Rich, pytest, Ruff, Pyright.

## Global Constraints

- Branch is independent and starts from `main`.
- No controller key behavior changes.
- Main menu keeps its current concise footer.
- Report setup keeps navigation, change/select, generate/review, help, and back/menu affordances but removes redundant aliases where Help can teach them.
- Session review always shows only `Enter Inspect`, `Space Include`, `/ Search`, `g Report`, `? More`, and `b Back` equivalents appropriate to the existing key model.
- Session browser always shows only navigation/inspect/search/help/back essentials.
- `a`, `n`, `e`, `R`, `h/l`, PgUp/PgDn, and other power shortcuts remain functional and discoverable through Help.

---

### Task 1: Lock concise footer behavior with tests

**Files:**
- Create: `tests/unit/interactive/test_simplified_footer.py`

**Interfaces:**
- Consumes: `render_session_review`, `render_session_browser`, `render_report_setup`, `render_help`.
- Produces: regression coverage that core hints stay visible, power hints move out of primary chrome, and Help still documents them.

- [ ] Write a review-render test asserting primary hints are present and `a All`, `n None`, `e Exclude repo`, and `R Rescan` are absent from the footer output.
- [ ] Write a browser-render test asserting Preview/Search/Help/Back remain while Rescan and horizontal aliases are absent from primary chrome.
- [ ] Write a Help test asserting hidden power shortcuts remain documented.
- [ ] Open/update the PR and verify GitHub Actions fails because the current renderers expose every shortcut.

### Task 2: Simplify renderer hint lists

**Files:**
- Modify: `src/iiwi/interactive/render.py`
- Modify: `docs/cli-reference.md`

**Interfaces:**
- Existing controller key bindings remain unchanged.
- Existing `_hint_lines(...)` and viewport reservation continue to operate on the shorter lists.

- [ ] Replace session-review hints with the concise primary action set.
- [ ] Replace session-browser hints with the concise primary action set.
- [ ] Trim report-setup hints where aliases are redundant, without hiding Generate/Review/Help/Back.
- [ ] Ensure `render_help` still lists all supported power shortcuts.
- [ ] Update CLI reference wording to distinguish visible primary hints from additional shortcuts available in Help.
- [ ] Verify targeted tests pass.
- [ ] Verify the full GitHub Actions CI matrix passes.

### Task 3: Review scope

- [ ] Confirm controller.py is unchanged.
- [ ] Confirm no shortcut was removed, only primary on-screen hint copy.
- [ ] Confirm viewport regression tests still pass with the shorter footer.
