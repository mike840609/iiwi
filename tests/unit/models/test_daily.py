from datetime import date, datetime

from iiwi.models import EvidenceRef, OutcomeBucket
from iiwi.models.daily import (
    DailySection,
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)


def sample_daily_draft() -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=date(2026, 8, 13),
        scan_since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        scan_until=datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
        work_items=[
            DailyStandupWorkItem(
                id="w1",
                yesterday=DailySectionItem(
                    statement="Started the renderer",
                    source=DailyStatementSource.ACTIVITY_YESTERDAY,
                    rank=0,
                ),
                today=DailySectionItem(
                    statement="Continue the renderer",
                    source=DailyStatementSource.SUGGESTED_FROM_YESTERDAY,
                    rank=1,
                ),
            ),
            DailyStandupWorkItem(
                id="w2",
                today=DailySectionItem(
                    statement="Ship the parser",
                    source=DailyStatementSource.ACTIVITY_TODAY,
                    rank=0,
                ),
            ),
        ],
    )


def test_edit_marks_only_the_target_section_reviewer_owned() -> None:
    draft = sample_daily_draft()

    draft.edit(DailySection.TODAY, "w1", "Finish the renderer")

    yesterday = draft.work_items[0].yesterday
    today = draft.work_items[0].today
    assert yesterday is not None
    assert today is not None
    assert today.statement == "Finish the renderer"
    assert today.user_edited is True
    assert yesterday.user_edited is False


def test_toggling_a_more_item_on_promotes_only_that_section() -> None:
    draft = sample_daily_draft()
    today = draft.work_items[0].today
    yesterday = draft.work_items[0].yesterday
    assert today is not None
    assert yesterday is not None
    today.included = False
    today.bucket = OutcomeBucket.MORE

    draft.toggle_included(DailySection.TODAY, "w1")

    assert today.included is True
    assert today.bucket is OutcomeBucket.PRIMARY
    assert yesterday.included is True
    assert yesterday.bucket is OutcomeBucket.PRIMARY


def test_move_reorders_only_items_in_the_target_section() -> None:
    draft = sample_daily_draft()

    draft.move(DailySection.TODAY, "w1", -1)

    assert [work.id for work, _ in draft.ordered_items(DailySection.TODAY)] == ["w1", "w2"]
    assert [work.id for work, _ in draft.ordered_items(DailySection.YESTERDAY)] == ["w1"]
    yesterday = draft.work_items[0].yesterday
    assert yesterday is not None
    assert yesterday.rank == 0


def test_move_stops_at_the_edge_of_a_section() -> None:
    draft = sample_daily_draft()

    draft.move(DailySection.TODAY, "w2", -1)

    assert [work.id for work, _ in draft.ordered_items(DailySection.TODAY)] == ["w2", "w1"]


def test_add_user_item_has_no_evidence_and_only_the_requested_section() -> None:
    draft = sample_daily_draft()

    added = draft.add_user_item(DailySection.BLOCKERS, "Waiting for API access")

    assert added.source_outcome_ids == []
    assert added.repository_ids == []
    assert added.yesterday is None
    assert added.today is None
    assert added.blocker is not None
    assert added.blocker.statement == "Waiting for API access"
    assert added.blocker.source is DailyStatementSource.USER_ADDED
    assert added.blocker.evidence_refs == []
    assert added.blocker.included is True
    assert added.blocker.user_edited is True


def test_user_item_accepts_an_evidence_ref_model_without_mutating_it() -> None:
    """Daily mutations do not accidentally share or rewrite evidence lists."""

    evidence = EvidenceRef(
        harness="codex",
        session_id="s1",
        repository_id="repo",
        activity_ids=["a1"],
    )
    item = DailySectionItem(
        statement="Existing",
        evidence_refs=[evidence],
        source=DailyStatementSource.ACTIVITY_TODAY,
    )
    draft = sample_daily_draft()
    draft.work_items[0].today = item

    draft.add_user_item(DailySection.TODAY, "Manual")

    assert item.evidence_refs == [evidence]
