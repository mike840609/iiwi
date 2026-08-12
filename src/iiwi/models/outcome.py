"""Outcome synthesis and review-draft domain models."""

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
    impact: str = ""
    status: OutcomeStatus | None = None
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
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def apply_type_default(self) -> OutcomeReviewDraft:
        if self.detail is None:
            self.detail = self.default_detail(self.report_type)
        elif "detail" in self.model_fields_set:
            self.detail_overridden = True
        self._normalize_ranks()
        return self

    @staticmethod
    def default_detail(report_type: ReportType) -> DetailLevel:
        return DetailLevel.BRIEF if report_type is ReportType.MANAGER else DetailLevel.FULL

    def ordered(self) -> list[Outcome]:
        return sorted(self.outcomes, key=lambda outcome: outcome.rank)

    def _normalize_ranks(self) -> None:
        for rank, outcome in enumerate(self.ordered()):
            outcome.rank = rank

    def _outcome(self, identifier: str) -> Outcome:
        return next(outcome for outcome in self.outcomes if outcome.id == identifier)

    def toggle_included(self, identifier: str) -> None:
        outcome = self._outcome(identifier)
        outcome.included = not outcome.included
        if outcome.included and outcome.bucket is OutcomeBucket.MORE:
            outcome.bucket = OutcomeBucket.PRIMARY

    def move(self, identifier: str, delta: int) -> None:
        """Reorder an outcome within its own bucket.

        Quick Review lists primary, more, and ungrouped outcomes as three
        separate sections, so moving past a neighbour from another bucket
        changed the global rank without changing anything on screen — the key
        read as broken. Reordering swaps ranks with the adjacent outcome in the
        same section, and does nothing at either end of it.
        """

        outcome = self._outcome(identifier)
        siblings = [item for item in self.ordered() if item.bucket is outcome.bucket]
        index = next(
            position
            for position, item in enumerate(siblings)
            if item.id == identifier
        )
        target = index + delta
        if not 0 <= target < len(siblings):
            return
        neighbour = siblings[target]
        outcome.rank, neighbour.rank = neighbour.rank, outcome.rank
        self._normalize_ranks()

    def edit(
        self,
        identifier: str,
        *,
        title: str,
        status: OutcomeStatus,
        impact: str,
    ) -> None:
        outcome = self._outcome(identifier)
        outcome.title = title
        outcome.status = status
        outcome.impact = impact

    def split(self, identifier: str) -> None:
        parent = self._outcome(identifier)
        if not parent.source_groups:
            raise ValueError("cannot split outcome without source groups")
        replacement = [
            Outcome(
                id=f"{parent.id}:{group.id}",
                title=group.title,
                status=group.status or parent.status,
                impact=group.impact,
                included=parent.included,
                rank=parent.rank + offset,
                origin=parent.origin,
                bucket=parent.bucket,
                evidence_refs=group.evidence_refs,
            )
            for offset, group in enumerate(parent.source_groups)
        ]
        index = self.outcomes.index(parent)
        self.outcomes[index : index + 1] = replacement
        self._normalize_ranks()

    def add_user_outcome(
        self,
        title: str,
        impact: str,
        status: OutcomeStatus = OutcomeStatus.IN_PROGRESS,
    ) -> Outcome:
        outcome = Outcome(
            id=uuid4().hex,
            title=title,
            status=status,
            impact=impact,
            rank=len(self.outcomes),
            origin=OutcomeOrigin.USER_ADDED,
        )
        self.outcomes.append(outcome)
        self._normalize_ranks()
        return outcome

    def set_report_type(self, report_type: ReportType) -> None:
        self.report_type = report_type
        if not self.detail_overridden:
            self.detail = self.default_detail(report_type)

    def set_detail(self, detail: DetailLevel) -> None:
        self.detail = detail
        self.detail_overridden = True
