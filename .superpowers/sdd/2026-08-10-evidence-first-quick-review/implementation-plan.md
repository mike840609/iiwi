# Evidence-first Quick Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn selected agent sessions into evidence-backed outcomes that a user can correct in a 30–60 second terminal review before producing a Manager or Engineering report.

**Architecture:** Keep the existing scan and evidence extraction layers as the source of truth. Add domain models for outcomes and the mutable in-process review draft, a synthesis service that validates LLM JSON at a deterministic boundary, and a reviewed-report path in `ReportService`; then add one `OUTCOME_REVIEW` state to the existing Rich/Typer controller. Existing session-based generation remains untouched as the non-interactive path and explicit fallback.

**Tech Stack:** Python 3.11+, Pydantic 2, Rich 14, Typer 0.16, Jinja2 3.1, pytest 8, Ruff, Pyright.

## Global Constraints

- Preserve the existing non-interactive CLI and `--detail brief|full` behavior.
- `Report type` chooses Manager or Engineering; `Detail` chooses evidence depth; Quick Review changes only the current period's content.
- Manager defaults to Brief and Engineering defaults to Full; an explicit Detail choice wins.
- Both narrative and structured session-based output must honor `Detail`.
- Cross-repository auto-merge requires `high` confidence plus either one explicit shared work identifier or at least two independent linkage signals; wording similarity and timestamp proximity do not count.
- Preselect at most five outcomes, normally 3–5 when enough valid candidates exist; retain every other candidate.
- Never invent Impact or evidence. Unsupported Impact remains empty.
- Keep the review draft only in process; do not add cross-process draft persistence.
- Version one excludes manual merge, historical style learning, collaborative review, and automatic publishing.
- At terminal heights of 20–30 lines, preserve the screen identity, focused control, and relevant key help.

---

### Task 1: Outcome and Review-Draft Domain Model

**Files:**
- Create: `src/iiwi/models/report_options.py`
- Create: `src/iiwi/models/outcome.py`
- Modify: `src/iiwi/models/__init__.py`
- Modify: `src/iiwi/renderers/markdown.py`
- Modify: `src/iiwi/interactive/models.py`
- Test: `tests/unit/models/test_outcome.py`
- Test: `tests/unit/interactive/test_models.py`

**Interfaces:**
- Consumes: existing `DateRange`.
- Produces: `OutcomeStatus`, `OutcomeOrigin`, `OutcomeBucket`, `EvidenceRef`, `OutcomeSourceGroup`, `Outcome`, `OutcomeSynthesisResult`, and `OutcomeReviewDraft`.
- Produces: `DetailLevel` and `ReportType` in `iiwi.models.report_options`; `iiwi.renderers.markdown` re-exports `DetailLevel` so existing imports remain compatible and model/render imports cannot form a cycle.
- Produces: `ReportDraft.report_type`, `ReportDraft.detail_overridden`, `ReportDraft.set_report_type()`, and `Screen.OUTCOME_REVIEW`.

- [ ] **Step 1: Write failing enum, validation, ordering, split, and user-add tests**

Create `tests/unit/models/test_outcome.py` with representative constructors and these assertions:

```python
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeBucket,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeSourceGroup,
    OutcomeStatus,
)
from iiwi.models.report_options import DetailLevel, ReportType


def outcome(identifier: str, rank: int, *, bucket=OutcomeBucket.PRIMARY) -> Outcome:
    ref = EvidenceRef(session_id=f"ses-{identifier}", repository_id="repo-a")
    return Outcome(
        id=identifier,
        title=f"Outcome {identifier}",
        status=OutcomeStatus.COMPLETED,
        rank=rank,
        bucket=bucket,
        evidence_refs=[ref],
        source_groups=[OutcomeSourceGroup(id=f"group-{identifier}", evidence_refs=[ref])],
    )


def test_manager_defaults_to_brief_and_explicit_detail_survives_type_change() -> None:
    draft = OutcomeReviewDraft(
        outcomes=[outcome("a", 0)], report_type=ReportType.MANAGER
    )
    assert draft.detail is DetailLevel.BRIEF

    draft.set_detail(DetailLevel.FULL)
    draft.set_report_type(ReportType.ENGINEERING)
    draft.set_report_type(ReportType.MANAGER)

    assert draft.detail is DetailLevel.FULL
    assert draft.detail_overridden is True


def test_reorder_normalizes_ranks_without_dropping_candidates() -> None:
    draft = OutcomeReviewDraft(outcomes=[outcome("a", 0), outcome("b", 1)])
    draft.move("b", -1)
    assert [(item.id, item.rank) for item in draft.ordered()] == [("b", 0), ("a", 1)]


def test_split_restores_source_groups_and_preserves_evidence() -> None:
    first = EvidenceRef(session_id="ses-a", repository_id="repo-a")
    second = EvidenceRef(session_id="ses-b", repository_id="repo-b")
    merged = Outcome(
        id="merged",
        title="Shared delivery",
        status=OutcomeStatus.COMPLETED,
        rank=0,
        evidence_refs=[first, second],
        source_groups=[
            OutcomeSourceGroup(id="a", title="API", evidence_refs=[first]),
            OutcomeSourceGroup(id="b", title="UI", evidence_refs=[second]),
        ],
    )
    draft = OutcomeReviewDraft(outcomes=[merged])

    draft.split("merged")

    assert [item.title for item in draft.ordered()] == ["API", "UI"]
    assert [item.evidence_refs for item in draft.ordered()] == [[first], [second]]


def test_add_user_outcome_has_no_invented_evidence() -> None:
    draft = OutcomeReviewDraft(outcomes=[])
    added = draft.add_user_outcome("Reviewed launch design", "Reduced ambiguity")
    assert added.origin is OutcomeOrigin.USER_ADDED
    assert added.evidence_refs == []
    assert added.bucket is OutcomeBucket.PRIMARY
```

Add to `tests/unit/interactive/test_models.py`:

```python
def test_report_type_applies_default_detail_until_detail_is_explicit() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    draft.set_report_type(ReportType.MANAGER)
    assert draft.detail is DetailLevel.BRIEF

    draft.set_detail(DetailLevel.FULL)
    draft.set_report_type(ReportType.ENGINEERING)
    draft.set_report_type(ReportType.MANAGER)
    assert draft.detail is DetailLevel.FULL
```

- [ ] **Step 2: Run the focused tests and confirm the imports fail**

Run: `uv run pytest tests/unit/models/test_outcome.py tests/unit/interactive/test_models.py -q`

Expected: FAIL because `iiwi.models.outcome`, `ReportType`, and `Screen.OUTCOME_REVIEW` do not exist.

- [ ] **Step 3: Implement the domain types and mutation rules**

Create `src/iiwi/models/report_options.py` with `DetailLevel(StrEnum)` values `brief` and `full`, plus `ReportType(StrEnum)` values `manager` and `engineering`. Remove the enum definition from `renderers/markdown.py` and import it there so all current `from iiwi.renderers.markdown import DetailLevel` callers continue to work.

Create `src/iiwi/models/outcome.py` with these public shapes:

```python
from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from iiwi.models.report_options import DetailLevel, ReportType


class OutcomeStatus(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"


class OutcomeOrigin(StrEnum):
    SYNTHESIZED = "synthesized"
    USER_ADDED = "user_added"


class OutcomeBucket(StrEnum):
    PRIMARY = "primary"
    MORE = "more"
    UNGROUPED = "ungrouped"


class EvidenceRef(BaseModel):
    session_id: str
    repository_id: str
    commit: str | None = None
    file: str | None = None


class OutcomeSourceGroup(BaseModel):
    id: str
    title: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class Outcome(BaseModel):
    id: str
    title: str
    status: OutcomeStatus
    impact: str = ""
    included: bool = True
    rank: int
    origin: OutcomeOrigin = OutcomeOrigin.SYNTHESIZED
    bucket: OutcomeBucket = OutcomeBucket.PRIMARY
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    source_groups: list[OutcomeSourceGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def synthesized_outcomes_are_traceable(self) -> Outcome:
        if self.origin is OutcomeOrigin.SYNTHESIZED and not self.evidence_refs:
            raise ValueError("synthesized outcomes require evidence")
        return self


class OutcomeSynthesisResult(BaseModel):
    outcomes: list[Outcome]
    failed_session_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OutcomeReviewDraft(BaseModel):
    outcomes: list[Outcome]
    report_type: ReportType = ReportType.ENGINEERING
    detail: DetailLevel | None = None
    detail_overridden: bool = False
    blockers: str | None = None
    next_week: str | None = None

    @model_validator(mode="after")
    def apply_type_default(self) -> OutcomeReviewDraft:
        if self.detail is None:
            self.detail = self.default_detail(self.report_type)
        self._normalize_ranks()
        return self

    @staticmethod
    def default_detail(report_type: ReportType) -> DetailLevel:
        return DetailLevel.BRIEF if report_type is ReportType.MANAGER else DetailLevel.FULL
```

Implement `ordered()`, `_normalize_ranks()`, `toggle_included(id)`, `move(id, delta)`, `edit(id, *, title, status, impact)`, `split(id)`, `add_user_outcome(title, impact, status=IN_PROGRESS)`, `set_report_type()`, and `set_detail()`. `split()` must replace the merged item in place, derive stable child ids as `f"{parent.id}:{group.id}"`, copy the parent's status/inclusion/bucket, and keep each group's references. `add_user_outcome()` may use `uuid4().hex` because its id only needs to be stable inside the in-memory draft.

Extend `ReportDraft` with `report_type=ReportType.ENGINEERING` and `detail_overridden=False`. `set_detail()` marks the override; `set_report_type()` changes detail only while `detail_overridden` is false. Add `OUTCOME_REVIEW = "outcome_review"` to `Screen`.

- [ ] **Step 4: Run model tests**

Run: `uv run pytest tests/unit/models/test_outcome.py tests/unit/interactive/test_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the model boundary**

```bash
git add src/iiwi/models/report_options.py src/iiwi/models/outcome.py src/iiwi/models/__init__.py src/iiwi/renderers/markdown.py src/iiwi/interactive/models.py tests/unit/models/test_outcome.py tests/unit/interactive/test_models.py
git commit -m "feat: add outcome review domain model"
```

---

### Task 2: Deterministic Outcome Synthesis Boundary

**Files:**
- Create: `src/iiwi/services/outcomes.py`
- Create: `src/iiwi/summarizers/outcome_prompt.py`
- Modify: `src/iiwi/errors.py`
- Test: `tests/unit/services/test_outcomes.py`
- Test: `tests/unit/summarizers/test_outcome_prompt.py`

**Interfaces:**
- Consumes: `ScanResult`, `extract_evidence(ResolvedSession)`, `OpenCodeRunner.run()`, and Task 1 outcome models.
- Produces: `OutcomeSynthesisService(runner).synthesize(scan) -> OutcomeSynthesisResult`.
- Produces: `OutcomeSynthesisError(IiwiError)` and `build_outcome_prompt() -> str`.

- [ ] **Step 1: Write failing service tests for ranking, evidence, merge confidence, and degradation**

Create `tests/unit/services/test_outcomes.py` around a `StaticRunner` whose `run()` returns supplied JSON. Cover these exact cases:

```python
def test_preselects_five_and_retains_the_remainder_in_more() -> None:
    service = service_for_json(payload_with_six_single_session_outcomes())
    result = service.synthesize(scan_with_six_sessions())
    assert [item.bucket for item in result.outcomes[:5]] == [OutcomeBucket.PRIMARY] * 5
    assert result.outcomes[5].bucket is OutcomeBucket.MORE
    assert len(result.outcomes) == 6


def test_high_confidence_cross_repo_merge_requires_two_independent_signals() -> None:
    result = service_for_json(cross_repo_payload(
        confidence="high",
        linkage_signals=[
            {"kind": "branch_or_issue", "value": "IIWI-42"},
            {"kind": "direct_reference", "value": "same feature rollout"},
        ],
    )).synthesize(two_repo_scan())
    assert len(result.outcomes) == 1
    assert {ref.repository_id for ref in result.outcomes[0].evidence_refs} == {
        "repo-a", "repo-b"
    }


@pytest.mark.parametrize("signals", [
    [{"kind": "similar_wording", "value": "auth"}],
    [{"kind": "timestamp_proximity", "value": "same hour"}],
    [{"kind": "branch_or_issue", "value": "IIWI-42"}],
])
def test_unsupported_cross_repo_merge_is_split_by_repository(signals) -> None:
    result = service_for_json(cross_repo_payload(
        confidence="high", linkage_signals=signals
    )).synthesize(two_repo_scan())
    assert len(result.outcomes) == 2


def test_model_cannot_attach_evidence_from_an_unknown_session() -> None:
    with pytest.raises(OutcomeSynthesisError, match="unknown session"):
        service_for_json(payload_for_sessions(["invented-session"])).synthesize(one_scan())


def test_unsupported_impact_is_left_empty() -> None:
    result = service_for_json(payload(impact="", source_session_ids=["ses-a"])) \
        .synthesize(one_scan())
    assert result.outcomes[0].impact == ""


def test_one_extraction_failure_becomes_ungrouped_without_blocking_success(monkeypatch) -> None:
    monkeypatch.setattr(outcomes, "extract_evidence", fail_only("ses-b"))
    result = service_for_json(payload_for_sessions(["ses-a"])).synthesize(two_session_scan())
    assert result.failed_session_ids == ["ses-b"]
    assert any(item.bucket is OutcomeBucket.UNGROUPED for item in result.outcomes)


def test_invalid_or_empty_model_output_is_a_complete_synthesis_error() -> None:
    with pytest.raises(OutcomeSynthesisError, match="valid outcome JSON"):
        service_for_raw("not-json").synthesize(one_scan())
```

- [ ] **Step 2: Run the service tests and verify they fail at import**

Run: `uv run pytest tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py -q`

Expected: FAIL because the synthesis service and prompt module do not exist.

- [ ] **Step 3: Implement the JSON contract and evidence reconstruction**

In `src/iiwi/services/outcomes.py`, define private Pydantic response models with only these model-controlled fields:

```python
class _LinkSignal(BaseModel):
    kind: Literal["shared_work_id", "branch_or_issue", "direct_reference", "similar_wording", "timestamp_proximity"]
    value: str


class _ProposedOutcome(BaseModel):
    title: str
    status: OutcomeStatus
    impact: str = ""
    source_session_ids: list[str]
    confidence: EvidenceConfidence
    linkage_signals: list[_LinkSignal] = Field(default_factory=list)


class _SynthesisPayload(BaseModel):
    outcomes: list[_ProposedOutcome]
```

`OutcomeSynthesisService.synthesize()` must:

1. Extract and redact evidence session by session; collect extraction failures.
2. Send `model_dump_json(indent=2)` evidence to `OpenCodeRunner.run()` with `build_outcome_prompt()`.
3. Strip an optional fenced `json` wrapper, parse with `_SynthesisPayload.model_validate_json()`, and raise `OutcomeSynthesisError` on empty/invalid output.
4. Rebuild every `EvidenceRef` from known `SessionEvidence`; never accept model-generated repository, file, commit, or activity ids.
5. Reject unknown source session ids.
6. Permit a multi-repository outcome only for HIGH confidence and either a `shared_work_id` signal or two distinct allowed linkage kinds from `{branch_or_issue, direct_reference}`.
7. Split unsupported multi-repository proposals into one outcome per repository.
8. Use `sha256("\0".join([normalized_title, *sorted(session_ids)]).encode()).hexdigest()[:16]` for stable synthesized ids, so two distinct outcomes sourced from one session cannot collide.
9. Sort in returned proposal order, assign ranks, mark the first five `PRIMARY` and the remainder `MORE`.
10. Create one `UNGROUPED` outcome per extraction failure with title from the session, empty Impact, and its known session/repository reference.

Create `build_outcome_prompt()` with the exact JSON keys above, the 3–5 ranking target, the merge confidence contract, an explicit instruction that Impact must be `""` when unsupported, and a rule forbidding unknown session ids.

- [ ] **Step 4: Run synthesis and prompt tests**

Run: `uv run pytest tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py -q`

Expected: PASS.

- [ ] **Step 5: Run extraction regression tests**

Run: `uv run pytest tests/unit/extraction tests/unit/summarizers/test_opencode_run.py -q`

Expected: PASS; synthesis reuses extraction without changing its conservative behavior.

- [ ] **Step 6: Commit synthesis**

```bash
git add src/iiwi/services/outcomes.py src/iiwi/summarizers/outcome_prompt.py src/iiwi/errors.py tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py
git commit -m "feat: synthesize evidence-backed outcomes"
```

---

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

### Task 5: Rendered-line-aware Single-screen TUI

**Files:**
- Modify: `src/iiwi/interactive/render.py`
- Modify: `src/iiwi/interactive/controller.py`
- Create: `tests/unit/interactive/test_outcome_review_render.py`
- Modify: `tests/unit/interactive/test_viewport_wrapping_regressions.py`

**Interfaces:**
- Consumes: `OutcomeReviewDraft`, cursor index, expanded evidence ids, and optional status message.
- Produces: `outcome_review_rows(draft) -> list[OutcomeReviewRow]` and `render_outcome_review(console, draft, *, cursor, expanded_evidence, message=None) -> None`.

- [ ] **Step 1: Write failing visual hierarchy tests**

Create renderer tests asserting the screen includes:

```python
assert "Quick Review" in text
assert "Manager" in text and "Brief" in text
assert "3 selected" in text
assert "More candidates" in text
assert "Blockers" in text and "Next week" in text
assert "Space Include" in text
assert "e Edit" in text
assert "J/K Reorder" in text
assert "v Evidence" in text
assert "s Split" in text
assert "a Add" in text
assert "p Preview" in text and "g Generate" in text
```

Assert an unfocused outcome occupies one display line; the focused outcome adds Status, non-empty Impact, and evidence summary; pressing `v` adds repository/session/file rows; user-added and ungrouped items carry visible labels.

- [ ] **Step 2: Write the terminal matrix regression**

Extend `test_viewport_wrapping_regressions.py` with long title, Impact, repository, file, and error strings. For widths `(40, 60, 80, 100, 140)`, heights `(20, 24, 30)`, and first/middle/last focus, assert:

```python
lines = stream.getvalue().splitlines()
assert len(lines) <= height - 1
assert any("Quick Review" in line for line in lines)
assert any("▶" in line for line in lines)
assert any("p Preview" in line or "g Generate" in line for line in lines)
```

- [ ] **Step 3: Run the renderer tests and confirm failure**

Run: `uv run pytest tests/unit/interactive/test_outcome_review_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py -q`

Expected: FAIL because the Quick Review renderer does not exist.

- [ ] **Step 4: Implement block rows and display-line budgeting**

Add a frozen `OutcomeReviewRow(kind, outcome_id=None)` and build rows in this order: settings, primary outcomes, More candidates control and included children when open, Ungrouped candidates control and children when present/open, Blockers, Next week, Preview, Generate.

Render each logical row into a `list[Text]` block. Only the focused outcome expands. Calculate every block's height from its actual rendered lines at the current width; use `Text.truncate(width, overflow="ellipsis")` before printing. The viewport algorithm must reserve header, blank separators, message, scroll indicators, and packed hint lines, then choose the largest contiguous block window containing the focused block. When space is tight, remove evidence detail first, then Impact continuation lines, while retaining the focused summary.

Reuse `_print_viewport_text()` and `_print_hints()`; do not introduce Textual or a second repaint loop.

- [ ] **Step 5: Run renderer and viewport tests**

Run: `uv run pytest tests/unit/interactive/test_outcome_review_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py -q`

Expected: PASS at every width/height/focus combination.

- [ ] **Step 6: Run all interactive tests**

Run: `uv run pytest tests/unit/interactive -q`

Expected: PASS.

- [ ] **Step 7: Commit the TUI**

```bash
git add src/iiwi/interactive/render.py src/iiwi/interactive/controller.py tests/unit/interactive/test_outcome_review_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py
git commit -m "feat: render outcome quick review TUI"
```

---

### Task 6: Retry, Partial Failure, and Session-report Fallback

**Files:**
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `src/iiwi/interactive/render.py`
- Modify: `src/iiwi/errors.py`
- Create: `tests/unit/interactive/test_outcome_review_failures.py`

**Interfaces:**
- Consumes: `OutcomeSynthesisError`, `OutcomeSynthesisResult.failed_session_ids`, existing `_ErrorState`, and existing direct `actions.generate()` session-report path.
- Produces: recoverable error kinds `outcome-synthesis`, `outcome-preview`, and `outcome-write`, each with explicit retry/back/fallback behavior.

- [ ] **Step 1: Write failing failure-path tests**

Cover these scripts:

1. Synthesis raises once, user selects Retry, synthesis succeeds, and review opens.
2. Complete synthesis failure offers `Use session-based report`; selecting it calls existing `actions.generate()` and labels the result as fallback in the warning.
3. Partial synthesis result opens review with `Ungrouped candidates` and successful primary outcomes.
4. Preview raises once, `Back to Quick Review` restores inclusion, order, edits, user-added outcomes, Blockers, and Next week.
5. Preview Retry uses the same draft object and succeeds.
6. Write conflict still offers `Overwrite once`, but retries `generate_reviewed()` rather than session-based generation.

- [ ] **Step 2: Run failure tests and verify missing options**

Run: `uv run pytest tests/unit/interactive/test_outcome_review_failures.py -q`

Expected: FAIL because outcome-specific error options and retry targets do not exist.

- [ ] **Step 3: Implement explicit recoverable routes**

Store an error retry discriminator, not a closure, in `_ErrorState`. `_error_options()` must return:

- synthesis: `Retry`, `Use session-based report`, `Back`;
- preview: `Retry`, `Back to Quick Review`, `Main menu`;
- reviewed write conflict: `Overwrite once`, `Back to Quick Review`, `Main menu`;
- reviewed write failure: `Back to Quick Review`, `Main menu`.

Add transient `ReportDraft.generation_notice: str | None = None`. The session-based fallback sets it to `Outcome synthesis unavailable; generated the session-based report.`, calls the pre-existing `actions.generate(draft, filtered_scan, force)`, and clears it in `finally`. Thread the notice into `_build_report_service(..., initial_warnings=[notice] if notice else None)` so the warning is present in both the written file and preview/result content. It must never label the output as outcome-synthesized, and ordinary interactive/non-interactive generation leaves the notice unset.

All preview/write errors leave `state.outcome_review` untouched. A synthesis Retry reruns synthesis from the already filtered scan without rescanning. `Overwrite once` calls reviewed generation with `force=True`.

- [ ] **Step 4: Run failure and existing error tests**

Run: `uv run pytest tests/unit/interactive/test_outcome_review_failures.py tests/unit/interactive/test_interactive_regressions.py tests/unit/interactive/test_controller_generation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit degradation behavior**

```bash
git add src/iiwi/interactive/controller.py src/iiwi/interactive/render.py src/iiwi/errors.py tests/unit/interactive/test_outcome_review_failures.py
git commit -m "feat: add quick review recovery paths"
```

---

### Task 7: End-to-end Compatibility, Documentation, and Final Verification

**Files:**
- Modify: `tests/integration/test_interactive_cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `tests/unit/test_documentation.py`
- Modify: `tests/unit/test_interactive_documentation.py`
- Modify: `README.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/configuration.md`
- Create: `docs/evidence-first-quick-review.md`

**Interfaces:**
- Consumes: the complete Quick Review flow from Tasks 1–6.
- Produces: executable user documentation and full-suite proof that legacy CLI behavior remains compatible.

- [ ] **Step 1: Add end-to-end interactive tests**

Use a deterministic synthesis runner and temporary output directory. Drive this complete flow:

```text
New report → Review sessions → Generate outcomes → exclude one outcome
→ edit another → add manual outcome → set Blockers/Next week
→ Preview → Back → Generate → Result
```

Assert the file contains the reviewed order and edits, omits the excluded outcome, labels the user-added outcome, contains the optional gaps, and contains no unsupported Impact.

Add a second flow for a 20-line terminal with six candidates, More candidates, expanded evidence, Preview failure, return, and successful retry.

- [ ] **Step 2: Add non-interactive compatibility tests**

In `tests/integration/test_cli.py`, preserve the existing command shape and assert both:

```python
runner.invoke(app, ["run", "--detail", "brief"])
runner.invoke(app, ["run", "--detail", "full"])
```

still generate the session-based report without invoking outcome synthesis. Assert the prior narrative and structured detail differences remain intact.

- [ ] **Step 3: Run integration tests and confirm documentation is the remaining failure**

Run: `uv run pytest tests/integration/test_interactive_cli.py tests/integration/test_cli.py -q`

Expected: PASS for behavior. Documentation tests added in the next step still fail until copy is updated.

- [ ] **Step 4: Document only shipped behavior**

Update README and docs with:

- Outcome-first explanation and the 30–60 second target.
- Manager vs Engineering and Brief vs Full responsibility table.
- Keys: Space, e, J/K, v, s, a, p, g, b.
- More candidates and Ungrouped candidates behavior.
- User-added outcomes and optional Blockers/Next week.
- Explicit synthesis retry/session-report fallback.
- `report.quick_review_report_type` configuration and environment variable.
- Version-one exclusions, including no persistent drafts and no manual merge.

Make documentation tests assert the exact config key and the `p Preview`/`g Generate` distinction so stale docs fail visibly.

- [ ] **Step 5: Run static checks and the full suite**

Run: `uv run ruff check .`

Expected: no diagnostics.

Run: `uv run pyright`

Expected: 0 errors.

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Manually verify the viewport and fallback**

Run: `uv run iiwi`

Verify in terminals at 20, 24, and 30 rows:

- the focused row and key help stay visible;
- long Impact/evidence truncates before screen controls disappear;
- More candidates can replace a primary outcome;
- Preview Back preserves all edits;
- a forced synthesis failure exposes Retry and session-based fallback;
- the final report matches Report type and Detail.

- [ ] **Step 7: Commit documentation and integration proof**

```bash
git add README.md docs/cli-reference.md docs/configuration.md docs/evidence-first-quick-review.md tests/integration/test_interactive_cli.py tests/integration/test_cli.py tests/unit/test_documentation.py tests/unit/test_interactive_documentation.py
git commit -m "docs: document evidence-first quick review"
```

---

## Final Acceptance Gate

- [ ] Related sessions produce one traceable outcome; the high-confidence cross-repository fixture merges.
- [ ] Low-confidence or weak-signal cross-repository work remains separate.
- [ ] Up to five outcomes are preselected and every remaining candidate is retained.
- [ ] Include, exclude, edit, reorder, split, add, Blockers, and Next week work from documented keys.
- [ ] Preview and all recoverable errors preserve the in-memory draft.
- [ ] Partial synthesis produces Ungrouped candidates; complete failure supports retry and explicit session-report fallback.
- [ ] Manager/Engineering and Brief/Full combinations render correctly.
- [ ] Narrative and structured session-based reports both honor Detail.
- [ ] The 20–30 line terminal matrix keeps focus and action help visible.
- [ ] Existing non-interactive CLI and `--detail brief|full` remain compatible.
