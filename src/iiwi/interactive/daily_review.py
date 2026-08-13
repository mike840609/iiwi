"""Visible-row derivation for the Daily Standup quick review."""

from __future__ import annotations

from dataclasses import dataclass

from iiwi.models.daily import DailySection, DailyStandupDraft
from iiwi.models.outcome import OutcomeBucket

YESTERDAY_MORE_SECTION = "__daily_yesterday_more__"
TODAY_MORE_SECTION = "__daily_today_more__"


@dataclass(frozen=True)
class DailyReviewRow:
    kind: str
    section: DailySection
    work_item_id: str | None = None


def visible_daily_review_rows(
    draft: DailyStandupDraft,
    expanded: set[str],
) -> list[DailyReviewRow]:
    """Return the Daily rows that share cursor and rendering order."""

    rows: list[DailyReviewRow] = []
    disclosures = {
        DailySection.YESTERDAY: YESTERDAY_MORE_SECTION,
        DailySection.TODAY: TODAY_MORE_SECTION,
    }
    for section in (
        DailySection.YESTERDAY,
        DailySection.TODAY,
        DailySection.BLOCKERS,
    ):
        rows.append(DailyReviewRow("section", section))
        ordered = draft.ordered_items(section)
        if section is DailySection.BLOCKERS:
            rows.extend(
                DailyReviewRow("item", section, work_item.id)
                for work_item, _ in ordered
            )
            continue
        primary = [
            work_item
            for work_item, item in ordered
            if item.bucket is not OutcomeBucket.MORE
        ]
        more = [
            work_item
            for work_item, item in ordered
            if item.bucket is OutcomeBucket.MORE
        ]
        rows.extend(DailyReviewRow("item", section, item.id) for item in primary)
        if more:
            rows.append(DailyReviewRow("more", section))
            if disclosures[section] in expanded:
                rows.extend(DailyReviewRow("item", section, item.id) for item in more)
    return rows
