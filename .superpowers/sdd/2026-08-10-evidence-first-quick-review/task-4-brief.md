### Task 4: Quick Review Actions, Configuration, and Draft Editing

**Files:**
- Modify: `src/iiwi/config.py`
- Modify: `src/iiwi/interactive/cli_actions.py`
- Modify: `src/iiwi/interactive/controller.py`
- Test: `tests/unit/test_config.py`
- Modify: `tests/unit/interactive/test_cli_actions.py`
- Create: `tests/unit/interactive/test_outcome_review_controller.py`

**Interfaces:**
- Consumes: `OutcomeSynthesisService`, `ReportService.generate_reviewed()`, and Task 1 mutation methods.
- Extends `InteractiveActions` with:
  - `synthesize: Callable[[ReportDraft, ScanResult], OutcomeReviewDraft]`
  - `generate_reviewed: Callable[[ReportDraft, ScanResult, OutcomeReviewDraft, bool], InteractiveReportResult]`
  - `edit_outcome: Callable[[Outcome], Outcome]`
  - `add_outcome: Callable[[], Outcome | None]`
  - `edit_gap: Callable[[str, str | None], str | None]`
  - `save_report_type: Callable[[ReportType], None]`
- Produces: controller state fields `outcome_review`, `outcome_cursor`, `outcome_message`, and `expanded_evidence`.

- [ ] **Step 1: Write failing configuration and action adapter tests**

Add assertions that `ReportSettings.quick_review_report_type` defaults to `manager`, accepts `IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE=engineering`, and is discoverable through `config list/set/unset` as `report.quick_review_report_type`.

In `test_cli_actions.py`, monkeypatch the runner and service builders; assert `_new_draft()` maps Manager to Brief, `_synthesize()` uses the already-filtered scan, `_generate_reviewed()` passes the same `OutcomeReviewDraft` object to `ReportService.generate_reviewed()`, and `_save_report_type()` writes only the report-type preference.

- [ ] **Step 2: Write failing controller tests for every mutation key**

In `tests/unit/interactive/test_outcome_review_controller.py`, reuse the existing `ScriptedInput` style and assert:

- `g` from Session Review synthesizes once and opens `OUTCOME_REVIEW`.
- Up/Down changes focus; Space toggles inclusion.
- uppercase `J`/`K` reorder while lowercase `j`/`k` navigate.
- `e` applies the callback result without losing id/evidence.
- `s` splits an outcome with two source groups.
- `a` adds a `User added` outcome.
- activating Blockers and Next week calls `edit_gap` and preserves `None`.
- changing Report type persists it and updates Detail only before an explicit Detail override.
- `p` dry-runs reviewed generation and opens Report Preview.
- `g` writes the reviewed report and opens Report Result.
- `b` from Preview returns to the same review draft.

- [ ] **Step 3: Run focused tests and verify they fail**

Run: `uv run pytest tests/unit/test_config.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_controller.py -q`

Expected: FAIL because the new configuration leaf, callbacks, and screen dispatch do not exist.

- [ ] **Step 4: Implement action adapters and controller state transitions**

Add `quick_review_report_type: ReportType = ReportType.MANAGER` to `ReportSettings`.

Build one `OpenCodeRunner` in `_synthesize()` with the same configured executable, model, and timeout as narrative generation. Build `OutcomeSynthesisService`, synthesize the filtered scan, and create `OutcomeReviewDraft` with the `ReportDraft` report type and detail state. `_generate_reviewed()` must use the existing report service builder and call `generate_reviewed()`.

Typed callbacks use `typer.prompt` only after an explicit key. `edit_outcome` prompts title and Impact with the current values, and cycles status with a two-choice prompt. `add_outcome` asks title, optional Impact, and status; it returns `None` when title is blank. `edit_gap` accepts blank as `None` and the literal `none` case-insensitively as `None`.

In the controller, change only report-generation intent: `g` from Session Review starts synthesis and opens `OUTCOME_REVIEW`; existing direct generation remains callable only through the explicit complete-synthesis fallback. Add `_outcome_review_key()` and dispatch/render hooks. Preserve `state.outcome_review` across preview and recoverable errors; clear it only for New report, Generate another report, or changes that invalidate the scan.

- [ ] **Step 5: Run controller/action tests**

Run: `uv run pytest tests/unit/test_config.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_controller.py -q`

Expected: PASS.

- [ ] **Step 6: Run existing interactive controller regressions**

Run: `uv run pytest tests/unit/interactive -q`

Expected: PASS after updating existing fixtures to supply the new action callbacks. Do not weaken existing assertions about scan count, selection, output conflicts, or terminal restoration.

- [ ] **Step 7: Commit action and controller behavior**

```bash
git add src/iiwi/config.py src/iiwi/interactive/cli_actions.py src/iiwi/interactive/controller.py tests/unit/test_config.py tests/unit/interactive/test_cli_actions.py tests/unit/interactive/test_outcome_review_controller.py tests/unit/interactive
git commit -m "feat: add quick review controller flow"
```

---
