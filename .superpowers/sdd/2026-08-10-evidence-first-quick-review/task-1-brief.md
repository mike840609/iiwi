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
