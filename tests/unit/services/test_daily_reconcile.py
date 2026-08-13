"""Reconciliation of fresh Daily activity with reviewer-owned state."""

from __future__ import annotations

from datetime import date, datetime

from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import EvidenceRef, OutcomeBucket
from iiwi.services.daily_reconcile import reconcile_daily_draft


def _ref(
    session_id: str,
    *activity_ids: str,
    harness: str | None = "codex",
    repository_id: str = "repo-a",
) -> EvidenceRef:
    return EvidenceRef(
        harness=harness,
        session_id=session_id,
        repository_id=repository_id,
        activity_ids=list(activity_ids),
    )


def _section(
    statement: str,
    refs: list[EvidenceRef] | None = None,
    *,
    source: DailyStatementSource = DailyStatementSource.ACTIVITY_TODAY,
    included: bool = True,
    rank: int = 0,
    bucket: OutcomeBucket = OutcomeBucket.PRIMARY,
    user_edited: bool = False,
    new_activity: bool = False,
) -> DailySectionItem:
    return DailySectionItem(
        statement=statement,
        evidence_refs=refs or [],
        source=source,
        included=included,
        rank=rank,
        bucket=bucket,
        user_edited=user_edited,
        new_activity=new_activity,
    )


def _work(
    identifier: str,
    *,
    today: DailySectionItem | None = None,
    yesterday: DailySectionItem | None = None,
    blocker: DailySectionItem | None = None,
) -> DailyStandupWorkItem:
    return DailyStandupWorkItem(
        id=identifier,
        source_outcome_ids=[f"outcome-{identifier}"],
        repository_ids=["repo-a"],
        yesterday=yesterday,
        today=today,
        blocker=blocker,
    )


def _draft(
    *items: DailyStandupWorkItem,
    standup_date: date = date(2026, 8, 13),
) -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=standup_date,
        scan_since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        scan_until=datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
        work_items=list(items),
    )


def test_previous_review_state_from_another_date_is_not_carried_forward() -> None:
    previous = _draft(
        _work(
            "old-plan",
            today=_section(
                "Yesterday's plan",
                source=DailyStatementSource.USER_ADDED,
                user_edited=True,
            ),
        ),
        standup_date=date(2026, 8, 12),
    )
    fresh = _draft(standup_date=date(2026, 8, 13))

    merged = reconcile_daily_draft(previous, fresh)

    assert merged.standup_date == date(2026, 8, 13)
    assert merged.work_items == []


def test_reviewer_wording_inclusion_and_section_order_survive_machine_refresh() -> None:
    previous = _draft(
        _work(
            "reviewed-second",
            today=_section(
                "My wording",
                [_ref("s2", "a2")],
                included=False,
                rank=0,
                bucket=OutcomeBucket.MORE,
                user_edited=True,
            ),
        ),
        _work("reviewed-first", today=_section("Keep first", [_ref("s1", "a1")], rank=1)),
    )
    fresh = _draft(
        _work("machine-1", today=_section("Machine first", [_ref("s1", "a1")], rank=0)),
        _work("machine-2", today=_section("Machine rewrite", [_ref("s2", "a2")], rank=1)),
    )

    merged = reconcile_daily_draft(previous, fresh)

    assert [item.id for item in merged.work_items] == ["reviewed-second", "reviewed-first"]
    reviewed = merged.work_items[0].today
    assert reviewed is not None
    assert reviewed.statement == "My wording"
    assert reviewed.user_edited is True
    assert reviewed.included is False
    assert reviewed.bucket is OutcomeBucket.MORE
    assert reviewed.rank == 0


def test_user_added_and_partial_scan_missing_items_remain_in_place() -> None:
    manual = _work(
        "manual",
        today=_section(
            "Ask product about launch",
            source=DailyStatementSource.USER_ADDED,
            user_edited=True,
        ),
    )
    missing = _work(
        "temporarily-missing",
        today=_section(
            "Claude task",
            [_ref("c1", "a1", harness="claude-code")],
        ),
    )
    previous = _draft(manual, missing)

    merged = reconcile_daily_draft(previous, _draft())

    assert merged.work_items == [manual, missing]


def test_exact_activity_match_unions_refs_and_marks_only_new_evidence() -> None:
    previous = _draft(
        _work(
            "reviewed",
            today=_section("My wording", [_ref("s1", "a1")], user_edited=True),
        )
    )
    fresh = _draft(
        _work("machine", today=_section("Machine wording", [_ref("s1", "a1", "a2")]))
    )

    merged = reconcile_daily_draft(previous, fresh)

    today = merged.work_items[0].today
    assert today is not None
    assert merged.work_items[0].id == "reviewed"
    assert today.statement == "My wording"
    assert today.user_edited is True
    assert today.new_activity is True
    assert len(today.evidence_refs) == 1
    assert today.evidence_refs[0].activity_ids == ["a1", "a2"]


def test_unmatched_fresh_work_appends_with_new_daily_id_and_new_activity() -> None:
    previous = _draft(_work("reviewed", today=_section("Old", [_ref("s1", "a1")])))
    fresh = _draft(_work("machine-id", today=_section("Brand new", [_ref("s2", "b1")])))

    merged = reconcile_daily_draft(previous, fresh)

    assert [item.id for item in merged.work_items[:1]] == ["reviewed"]
    added = merged.work_items[1]
    assert added.id not in {"reviewed", "machine-id"}
    assert added.today is not None
    assert added.today.statement == "Brand new"
    assert added.today.new_activity is True


def test_exact_activity_overlap_has_priority_over_other_coarse_overlap() -> None:
    exact = _work("exact", today=_section("Exact", [_ref("s1", "a1")]))
    coarse = _work("coarse", today=_section("Coarse", [_ref("s2", "old")]))
    fresh = _work(
        "machine",
        today=_section("Fresh", [_ref("s1", "a1"), _ref("s2", "new")]),
    )

    merged = reconcile_daily_draft(_draft(exact, coarse), _draft(fresh))

    assert merged.work_items[0].id == "exact"
    assert merged.work_items[1].id == "coarse"
    assert len(merged.work_items) == 2


def test_one_unambiguous_session_overlap_matches_without_activity_overlap() -> None:
    previous = _draft(_work("reviewed", today=_section("Old", [_ref("s1", "old")])))
    fresh = _draft(_work("machine", today=_section("Fresh", [_ref("s1", "new")])))

    merged = reconcile_daily_draft(previous, fresh)

    assert len(merged.work_items) == 1
    assert merged.work_items[0].id == "reviewed"


def test_matching_aggregates_evidence_across_all_sections() -> None:
    previous = _draft(
        _work("reviewed", yesterday=_section("Yesterday", [_ref("s1", "a1")]))
    )
    fresh = _draft(
        _work("machine", today=_section("Today", [_ref("s1", "a1")]))
    )

    merged = reconcile_daily_draft(previous, fresh)

    assert len(merged.work_items) == 1
    assert merged.work_items[0].id == "reviewed"
    assert merged.work_items[0].yesterday is not None
    assert merged.work_items[0].today is not None


def test_two_possible_previous_matches_are_preserved_and_fresh_is_new_candidate() -> None:
    previous = _draft(
        _work("first", today=_section("First", [_ref("s1", "a1")])),
        _work("second", today=_section("Second", [_ref("s2", "a2")])),
    )
    fresh = _draft(
        _work(
            "machine",
            today=_section("Combined", [_ref("s1", "new-1"), _ref("s2", "new-2")]),
        )
    )

    merged = reconcile_daily_draft(previous, fresh)

    assert [item.id for item in merged.work_items[:2]] == ["first", "second"]
    assert len(merged.work_items) == 3
    assert merged.work_items[2].id not in {"first", "second", "machine"}


def test_identical_session_ids_from_different_harnesses_never_match() -> None:
    previous = _draft(
        _work("reviewed", today=_section("Codex", [_ref("shared", "a1", harness="codex")]))
    )
    fresh = _draft(
        _work(
            "machine",
            today=_section("Claude", [_ref("shared", "a1", harness="claude-code")]),
        )
    )

    merged = reconcile_daily_draft(previous, fresh)

    assert len(merged.work_items) == 2
    assert merged.work_items[0].id == "reviewed"
    assert merged.work_items[1].id not in {"reviewed", "machine"}


def test_identical_machine_wording_without_evidence_overlap_never_matches() -> None:
    previous = _draft(
        _work("reviewed", today=_section("Same wording", [_ref("s1", "a1")]))
    )
    fresh = _draft(
        _work("machine", today=_section("Same wording", [_ref("s2", "a2")]))
    )

    merged = reconcile_daily_draft(previous, fresh)

    assert len(merged.work_items) == 2


def test_harnessless_legacy_refs_do_not_match() -> None:
    previous = _draft(
        _work("reviewed", today=_section("Legacy", [_ref("shared", "a1", harness=None)]))
    )
    fresh = _draft(
        _work("machine", today=_section("Fresh", [_ref("shared", "a1", harness=None)]))
    )

    merged = reconcile_daily_draft(previous, fresh)

    assert len(merged.work_items) == 2
