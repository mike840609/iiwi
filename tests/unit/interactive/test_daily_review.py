from datetime import date, datetime

from iiwi.interactive.daily_review import (
    TODAY_MORE_SECTION,
    YESTERDAY_MORE_SECTION,
    visible_daily_review_rows,
)
from iiwi.models.daily import (
    DailySection,
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import OutcomeBucket


def _item(
    statement: str,
    source: DailyStatementSource,
    *,
    rank: int,
    bucket: OutcomeBucket = OutcomeBucket.PRIMARY,
) -> DailySectionItem:
    return DailySectionItem(
        statement=statement,
        source=source,
        rank=rank,
        bucket=bucket,
    )


def _draft() -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=date(2026, 8, 13),
        scan_since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        scan_until=datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
        work_items=[
            DailyStandupWorkItem(
                id="primary",
                yesterday=_item(
                    "Primary yesterday",
                    DailyStatementSource.ACTIVITY_YESTERDAY,
                    rank=0,
                ),
                today=_item(
                    "Primary today",
                    DailyStatementSource.ACTIVITY_TODAY,
                    rank=0,
                ),
            ),
            DailyStandupWorkItem(
                id="more-yesterday",
                yesterday=_item(
                    "More yesterday",
                    DailyStatementSource.ACTIVITY_YESTERDAY,
                    rank=1,
                    bucket=OutcomeBucket.MORE,
                ),
            ),
            DailyStandupWorkItem(
                id="more-today",
                today=_item(
                    "More today",
                    DailyStatementSource.SUGGESTED_FROM_YESTERDAY,
                    rank=1,
                    bucket=OutcomeBucket.MORE,
                ),
            ),
            DailyStandupWorkItem(
                id="blocker-a",
                blocker=_item(
                    "First blocker",
                    DailyStatementSource.DETECTED_BLOCKER,
                    rank=0,
                    bucket=OutcomeBucket.MORE,
                ),
            ),
            DailyStandupWorkItem(
                id="blocker-b",
                blocker=_item(
                    "Second blocker",
                    DailyStatementSource.USER_ADDED,
                    rank=1,
                    bucket=OutcomeBucket.MORE,
                ),
            ),
        ],
    )


def _identity(rows: list[object]) -> list[tuple[str, DailySection, str | None]]:
    return [(row.kind, row.section, row.work_item_id) for row in rows]  # type: ignore[attr-defined]


def test_daily_rows_keep_fixed_sections_and_uncapped_blockers() -> None:
    rows = visible_daily_review_rows(_draft(), set())

    assert _identity(rows) == [
        ("section", DailySection.YESTERDAY, None),
        ("item", DailySection.YESTERDAY, "primary"),
        ("more", DailySection.YESTERDAY, None),
        ("section", DailySection.TODAY, None),
        ("item", DailySection.TODAY, "primary"),
        ("more", DailySection.TODAY, None),
        ("section", DailySection.BLOCKERS, None),
        ("item", DailySection.BLOCKERS, "blocker-a"),
        ("item", DailySection.BLOCKERS, "blocker-b"),
    ]


def test_today_more_disclosure_does_not_reveal_yesterday_more() -> None:
    rows = visible_daily_review_rows(_draft(), {TODAY_MORE_SECTION})

    assert ("item", DailySection.TODAY, "more-today") in _identity(rows)
    assert ("item", DailySection.YESTERDAY, "more-yesterday") not in _identity(rows)


def test_yesterday_more_disclosure_does_not_reveal_today_more() -> None:
    rows = visible_daily_review_rows(_draft(), {YESTERDAY_MORE_SECTION})

    assert ("item", DailySection.YESTERDAY, "more-yesterday") in _identity(rows)
    assert ("item", DailySection.TODAY, "more-today") not in _identity(rows)


def test_empty_draft_still_has_all_three_section_rows() -> None:
    draft = _draft()
    draft.work_items = []

    assert _identity(visible_daily_review_rows(draft, set())) == [
        ("section", DailySection.YESTERDAY, None),
        ("section", DailySection.TODAY, None),
        ("section", DailySection.BLOCKERS, None),
    ]
