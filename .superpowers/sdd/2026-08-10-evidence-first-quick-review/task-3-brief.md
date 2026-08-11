### Task 3: Reviewed Report Rendering and Detail Parity

**Files:**
- Modify: `src/iiwi/models/report.py`
- Modify: `src/iiwi/renderers/markdown.py`
- Modify: `src/iiwi/summarizers/opencode_run.py`
- Create: `src/iiwi/templates/outcomes.md.j2`
- Modify: `src/iiwi/services/report.py`
- Test: `tests/unit/renderers/test_outcome_markdown.py`
- Modify: `tests/unit/renderers/test_narrative.py`
- Modify: `tests/unit/summarizers/test_opencode_run.py`
- Modify: `tests/integration/test_report_service.py`

**Interfaces:**
- Consumes: `OutcomeReviewDraft` from Task 1 and existing output safety, redaction, usage, and clock dependencies in `ReportService`.
- Produces: `MarkdownRenderer.render_outcomes(report, *, detail) -> str`.
- Produces: `ReportService.generate_reviewed(review, *, scan, force=False, dry_run=False) -> ReportGenerationResult`.
- Changes: `render_narrative(report, *, timezone, detail=DetailLevel.FULL) -> str`.

- [ ] **Step 1: Write failing renderer matrix tests**

Create `tests/unit/renderers/test_outcome_markdown.py` with a reviewed draft containing one completed outcome with Impact and two evidence refs, one in-progress outcome without Impact, blockers, and next week. Assert:

```python
@pytest.mark.parametrize("report_type, heading", [
    (ReportType.MANAGER, "# Weekly Work Update"),
    (ReportType.ENGINEERING, "# Engineering Worklog"),
])
def test_report_type_controls_heading_and_sections(report_type, heading) -> None:
    output = render(report_type=report_type, detail=DetailLevel.BRIEF)
    assert output.startswith(heading)
    assert "## Outcomes" in output
    assert "## In Progress" in output
    assert "## Blockers" in output
    assert "## Next Week" in output


def test_brief_hides_session_file_and_commit_evidence() -> None:
    output = render(report_type=ReportType.MANAGER, detail=DetailLevel.BRIEF)
    assert "ses-a" not in output
    assert "src/iiwi/services/report.py" not in output


def test_full_groups_evidence_by_repository() -> None:
    output = render(report_type=ReportType.ENGINEERING, detail=DetailLevel.FULL)
    assert "### Evidence" in output
    assert "repo-a" in output
    assert "ses-a" in output


def test_empty_optional_sections_are_omitted() -> None:
    output = render_without_gaps()
    assert "## Blockers" not in output
    assert "## Next Week" not in output
```

Add narrative parity tests:

```python
def test_narrative_brief_omits_usage() -> None:
    report = narrative_report()
    report.usage_text = "gpt-5 123 tokens"
    assert "## Usage" not in render_narrative(
        report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF
    )


def test_narrative_full_keeps_usage() -> None:
    report = narrative_report()
    report.usage_text = "gpt-5 123 tokens"
    assert "## Usage" in render_narrative(
        report, timezone="Asia/Taipei", detail=DetailLevel.FULL
    )
```

- [ ] **Step 2: Run renderer tests and confirm the new path fails**

Run: `uv run pytest tests/unit/renderers/test_outcome_markdown.py tests/unit/renderers/test_narrative.py -q`

Expected: FAIL because `render_outcomes()` and narrative `detail` do not exist.

- [ ] **Step 3: Add reviewed report data without disturbing repository reports**

Extend `WorklogReport` with optional `report_type`, `outcomes`, `blockers`, and `next_week` fields, all defaulting to values that preserve current construction. Add `outcomes.md.j2`; branch on `OutcomeStatus`, show Impact only when non-empty, label user-authored items `User added`, and render evidence only when `full` is true. Evidence rows must be grouped by `repository_id` and use only present fields.

Implement `MarkdownRenderer.render_outcomes()` using the same StrictUndefined Jinja environment and trailing-newline normalization as `render()`.

Update `render_narrative()` to normalize `detail = DetailLevel(detail)` and include Usage only for Full. Change `build_summary_prompt(days, detail=DetailLevel.FULL)` so Brief explicitly requests concise outcomes/impact and forbids session ids, file lists, command lists, and Usage; Full retains the current engineering structure. Pass `self._detail` into both `build_summary_prompt()` in `_narrative_report()` and `render_narrative()` in `generate()`. Add prompt tests proving Brief and Full carry different evidence instructions. This makes Narrative honor Detail at generation and rendering boundaries rather than merely hiding Usage afterward.

- [ ] **Step 4: Add the reviewed service path and tests**

Add integration tests asserting that `generate_reviewed()`:

- uses the supplied draft instead of invoking the repository summarizer;
- respects `dry_run` and output conflict behavior;
- preserves user edits in output;
- redacts title, Impact, blockers, next week, and evidence before rendering;
- collects usage only for Full;
- returns the same `ScanResult` for history and counts.

Implement `generate_reviewed()` by constructing a `WorklogReport` from a deep copy of the reviewed draft, collecting usage through `_collect_usage()` only at Full detail, calling `render_outcomes()`, and reusing `atomic_secure_write()`.

- [ ] **Step 5: Run report tests**

Run: `uv run pytest tests/unit/renderers tests/unit/summarizers/test_opencode_run.py tests/integration/test_report_service.py -q`

Expected: PASS, including existing structured and narrative cases.

- [ ] **Step 6: Commit report rendering**

```bash
git add src/iiwi/models/report.py src/iiwi/renderers/markdown.py src/iiwi/templates/outcomes.md.j2 src/iiwi/services/report.py src/iiwi/summarizers/opencode_run.py tests/unit/renderers/test_outcome_markdown.py tests/unit/renderers/test_narrative.py tests/unit/summarizers/test_opencode_run.py tests/integration/test_report_service.py
git commit -m "feat: render reviewed outcome reports"
```

---
