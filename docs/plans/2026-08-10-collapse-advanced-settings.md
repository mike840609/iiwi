# Collapsed Advanced Report Settings Implementation Plan

> **For agentic workers:** implement task-by-task with test-first changes and verify the full CI matrix before marking complete.

**Goal:** Reduce report-setup cognitive load with explicit Generate/Preview actions, primary Harness and Period controls, and Detail, Subagents, Narrative, and Sanitize behind one expandable Advanced settings row.

**Architecture:** Keep `ReportDraft` and all existing field mutators unchanged. Add a short-lived controller flag for whether advanced settings are expanded, make the setup renderer derive its navigable rows from that flag, and keep the same keyboard edit behavior for visible fields. No setting persistence or scan-invalidation semantics change.

**Tech Stack:** Python 3.11+, Typer, Rich, pytest, Ruff, Pyright.

## Global Constraints

- Branch is independent and starts from `main`.
- Direct CLI and `ReportDraft` behavior is unchanged.
- Action rows: `Generate report`, `Preview report`.
- Primary settings: `Harness`, `Period`, `Advanced settings`.
- Advanced rows when expanded: `Detail`, `Subagents`, `Narrative`, `Sanitize`, indented beneath the disclosure row.
- `Preview report` uses dry-run internally and returns directly to report preview; `Dry run` is no longer a visible setup setting.
- Advanced settings start collapsed for each new report flow.
- Existing `r Review`, `g Generate`, Back/Menu behavior remains available.
- Changing scan-identity settings preserves the existing invalidation rules.

---

### Task 1: Lock collapsed setup behavior with tests

**Files:**
- Create: `tests/unit/interactive/test_collapsed_advanced_settings.py`

**Interfaces:**
- Consumes: `render_report_setup`, `run_interactive`.
- Produces: regression coverage for collapsed default, expansion, and editing an advanced field.

- [ ] Write a render test asserting Generate/Preview plus Harness/Period/Advanced settings are visible while the four advanced fields are collapsed by default.
- [ ] Write a controller/render-flow test that activates Advanced settings and sees the four indented advanced rows.
- [ ] Write controller tests proving Preview uses dry-run temporarily and Generate always writes normally.
- [ ] Write a controller test that edits Detail after expansion and keeps the existing no-scan behavior.
- [ ] Open/update the PR and verify GitHub Actions fails because all seven settings are currently always rendered.

### Task 2: Implement expandable advanced settings

**Files:**
- Modify: `src/iiwi/interactive/render.py`
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `docs/cli-reference.md`

**Interfaces:**
- `report_setup_rows(*, advanced: bool)` returns both action rows, primary settings, Advanced settings, and optionally the indented advanced fields.
- `render_report_setup(..., advanced: bool = False)` renders only rows returned for the current state.
- Controller `_State` gains `setup_advanced: bool = False` and resets it when starting a new report.

- [ ] Split setup fields into primary and advanced constants.
- [ ] Add the `Advanced settings` row with `▸`/`▾` state and help copy.
- [ ] Toggle expansion with Enter or horizontal-change keys while the cursor is on Advanced settings.
- [ ] Clamp setup cursor when collapsing so it cannot point to a hidden row.
- [ ] Preserve existing edit dispatch for each real setting.
- [ ] Update documentation to describe the collapsed default and expanded controls.
- [ ] Verify targeted tests pass.
- [ ] Verify the full GitHub Actions CI matrix passes.

### Task 3: Review scope

- [ ] Confirm `ReportDraft` serialization/persistence is untouched.
- [ ] Confirm no main-menu ordering or session explorer behavior changed.
- [ ] Confirm footer simplification remains outside this PR.
