"""Daily Standup review state."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from iiwi.models.outcome import EvidenceRef, OutcomeBucket


class DailySection(StrEnum):
    YESTERDAY = "yesterday"
    TODAY = "today"
    BLOCKERS = "blockers"


class DailyStatementSource(StrEnum):
    ACTIVITY_YESTERDAY = "activity_yesterday"
    ACTIVITY_TODAY = "activity_today"
    SUGGESTED_FROM_YESTERDAY = "suggested_from_yesterday"
    DETECTED_BLOCKER = "detected_blocker"
    USER_ADDED = "user_added"


class DailySectionItem(BaseModel):
    statement: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    included: bool = True
    rank: int = 0
    bucket: OutcomeBucket = OutcomeBucket.PRIMARY
    user_edited: bool = False
    source: DailyStatementSource
    new_activity: bool = False


class DailyStandupWorkItem(BaseModel):
    id: str
    source_outcome_ids: list[str] = Field(default_factory=list)
    repository_ids: list[str] = Field(default_factory=list)
    yesterday: DailySectionItem | None = None
    today: DailySectionItem | None = None
    blocker: DailySectionItem | None = None


class DailyStandupDraft(BaseModel):
    standup_date: date
    scan_since: datetime
    scan_until: datetime
    work_items: list[DailyStandupWorkItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    coverage_warnings: list[str] = Field(default_factory=list)
    successful_harnesses: list[str] = Field(default_factory=list)
    unavailable_harnesses: list[str] = Field(default_factory=list)
    repository_count: int = 0
    session_count: int = 0
    fallback: bool = False

    @staticmethod
    def _section_attribute(section: DailySection) -> str:
        return "blocker" if section is DailySection.BLOCKERS else section.value

    def _section_item(
        self,
        section: DailySection,
        work_item_id: str,
    ) -> DailySectionItem:
        attribute = self._section_attribute(section)
        work_item = next(item for item in self.work_items if item.id == work_item_id)
        section_item = getattr(work_item, attribute)
        if section_item is None:
            raise ValueError(f"work item {work_item_id!r} has no {section.value} section")
        return section_item

    def ordered_items(
        self,
        section: DailySection,
    ) -> list[tuple[DailyStandupWorkItem, DailySectionItem]]:
        attribute = self._section_attribute(section)
        items = [
            (work_item, section_item)
            for work_item in self.work_items
            if (section_item := getattr(work_item, attribute)) is not None
        ]
        return sorted(items, key=lambda pair: pair[1].rank)

    def toggle_included(self, section: DailySection, work_item_id: str) -> None:
        item = self._section_item(section, work_item_id)
        item.included = not item.included
        if item.included and item.bucket is OutcomeBucket.MORE:
            item.bucket = OutcomeBucket.PRIMARY

    def move(self, section: DailySection, work_item_id: str, delta: int) -> None:
        siblings = self.ordered_items(section)
        index = next(
            position
            for position, (work_item, _) in enumerate(siblings)
            if work_item.id == work_item_id
        )
        target = index + delta
        if not 0 <= target < len(siblings):
            return
        item = siblings[index][1]
        neighbour = siblings[target][1]
        item.rank, neighbour.rank = neighbour.rank, item.rank

    def edit(self, section: DailySection, work_item_id: str, statement: str) -> None:
        item = self._section_item(section, work_item_id)
        item.statement = statement
        item.user_edited = True

    def add_user_item(
        self,
        section: DailySection,
        statement: str,
    ) -> DailyStandupWorkItem:
        section_item = DailySectionItem(
            statement=statement,
            rank=len(self.ordered_items(section)),
            source=DailyStatementSource.USER_ADDED,
            user_edited=True,
        )
        work_item = DailyStandupWorkItem(id=uuid4().hex)
        setattr(work_item, self._section_attribute(section), section_item)
        self.work_items.append(work_item)
        return work_item
