# Unified Activity Review Implementation Plan

> **For agentic workers:** implement task-by-task with test-first changes and verify the full CI matrix before marking complete.

**Goal:** Remove the split between read-only Browse Sessions and selection-enabled Review Sessions so one activity explorer supports browsing, inspecting, selecting, and generating a report.

**Architecture:** Reuse the existing repository/session tree, selection model, search, preview, rescan, and persistence seams. The main-menu browse action will create a report draft, scan it, initialize `SelectionState`, and enter the existing review-capable tree instead of maintaining a separate `browser_scan` interaction mode. The report setup path continues to reach the same review screen.

**Tech Stack:** Python 3.11+, Typer, Rich, pytest, Ruff, Pyright.

## Global Constraints

- Branch is independent and starts from `main`.
- Direct CLI behavior is unchanged.
- Search, preview, viewport, selection persistence, repository exclusion, warnings, and rescan behavior remain available.
- No new persistence format or service API is introduced.
- Existing Browse Sessions data is not discarded; its entry path is redirected into the selection-capable activity explorer.

---

### Task 1: Lock one-explorer behavior with tests

**Files:**
- Create: `tests/unit/interactive/test_unified_activity_review.py`

**Interfaces:**
- Consumes: `run_interactive`, `InteractiveActions`, existing `SelectionState` behavior.
- Produces: regression coverage that the main browse entry supports session selection and report generation.

- [ ] Write a controller test that enters the current Browse Sessions menu item, toggles a session with Space, generates with `g`, and observes one generation call.
- [ ] Write a controller test that the same entry can open session preview and return without losing selection.
- [ ] Open/update the PR and verify GitHub Actions fails because the read-only browser ignores selection/generation keys.

### Task 2: Route browsing through the review-capable explorer

**Files:**
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `src/iiwi/interactive/render.py`
- Modify: `docs/cli-reference.md`

**Interfaces:**
- `_review(...)` remains the single initializer for a scanned selectable activity tree.
- The main-menu activity/browse entry creates a draft and calls the same review initialization path.
- `SESSION_BROWSER` may remain as a compatibility enum/internal path only if still required by tests; it must no longer be the normal main-menu destination.

- [ ] Replace the main-menu browse loader with a draft + `_review(...)` path.
- [ ] Ensure the unified explorer copy is neutral (`Activity`/`Review Activity`) rather than implying a report-only detour.
- [ ] Preserve `Space`, `g`, `p`, `/`, `R`, `e`, navigation, and Back behavior.
- [ ] Update documentation so users are taught one repository/session explorer rather than Browse vs Review modes.
- [ ] Verify targeted tests pass.
- [ ] Verify the full GitHub Actions CI matrix passes.

### Task 3: Review scope

- [ ] Confirm no report-generation service logic changed.
- [ ] Confirm no advanced-settings or footer simplification work leaked into this PR.
- [ ] Confirm the existing read-only renderer can be removed only if no production or test caller remains; otherwise leave it for a later cleanup PR.
