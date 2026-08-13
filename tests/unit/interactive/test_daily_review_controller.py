from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from iiwi.interactive import controller
from iiwi.interactive.controller import InteractiveActions, InteractiveReportResult
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.models.daily import (
    DailySection,
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import OutcomeReviewDraft
from iiwi.models.time_range import DateRange


def _period() -> DateRange:
    return DateRange(
        since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        until=datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
    )


def _draft() -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=date(2026, 8, 13),
        scan_since=_period().since,
        scan_until=_period().until,
        work_items=[
            DailyStandupWorkItem(
                id="yesterday-a",
                yesterday=DailySectionItem(
                    statement="Yesterday A",
                    source=DailyStatementSource.ACTIVITY_YESTERDAY,
                    rank=0,
                ),
            ),
            DailyStandupWorkItem(
                id="yesterday-b",
                yesterday=DailySectionItem(
                    statement="Yesterday B",
                    source=DailyStatementSource.ACTIVITY_YESTERDAY,
                    rank=1,
                ),
            ),
            DailyStandupWorkItem(
                id="today-a",
                today=DailySectionItem(
                    statement="Today A",
                    source=DailyStatementSource.ACTIVITY_TODAY,
                    rank=0,
                ),
            ),
        ],
    )


class ActionLog:
    def __init__(self) -> None:
        self.persisted: list[DailyStandupDraft] = []
        self.previewed: list[DailyStandupDraft] = []
        self.generated: list[DailyStandupDraft] = []
        self.added_sections: list[DailySection] = []


def _result(path: str | None) -> InteractiveReportResult:
    return InteractiveReportResult(
        output_path=Path(path) if path else None,
        content="# Daily Standup\n",
        repository_count=1,
        session_count=2,
    )


def _actions(log: ActionLog, *, warning: str | None = None) -> InteractiveActions:
    def persist(draft: DailyStandupDraft) -> str | None:
        log.persisted.append(draft.model_copy(deep=True))
        return warning

    def preview(draft: DailyStandupDraft) -> InteractiveReportResult:
        log.previewed.append(draft.model_copy(deep=True))
        return _result(None)

    def generate(draft: DailyStandupDraft) -> InteractiveReportResult:
        log.generated.append(draft.model_copy(deep=True))
        return _result("reports/daily-2026-08-13.md")

    def add(section: DailySection) -> str | None:
        log.added_sections.append(section)
        return f"Added {section.value}"

    return InteractiveActions(
        new_draft=lambda: ReportDraft(harness="codex", period=_period()),
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Daily", _period()),
        scan=lambda draft: pytest.fail("ordinary scan should not run"),
        generate=lambda draft, scan, force: pytest.fail("ordinary generate should not run"),
        synthesize=lambda draft, scan: OutcomeReviewDraft(outcomes=[]),
        generate_reviewed=lambda draft, scan, review, force: pytest.fail(
            "reviewed report generation should not run"
        ),
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
        start_daily=lambda previous: previous or _draft(),
        continue_daily_empty=lambda error, previous: previous or _draft(),
        persist_daily=persist,
        preview_daily=preview,
        generate_daily=generate,
        edit_daily_statement=lambda statement: f"Edited {statement}",
        add_daily_statement=add,
    )


def _state(draft: DailyStandupDraft | None = None) -> controller._State:
    return controller._State(
        screen=Screen.DAILY_REVIEW,
        daily_review=draft or _draft(),
        daily_cursor=1,
        daily_expanded=set(),
    )


def _key(value: str) -> KeyPress:
    return KeyPress(char=value)


def test_space_toggles_focused_daily_item_and_persists_warning() -> None:
    log = ActionLog()
    state = _state()

    controller._daily_review_key(
        state,
        KeyPress(key=Key.SPACE),
        _actions(log, warning="State could not be saved"),
    )

    assert state.daily_review is not None
    assert state.daily_review.work_items[0].yesterday is not None
    assert state.daily_review.work_items[0].yesterday.included is False
    assert len(log.persisted) == 1
    assert state.daily_message == "State could not be saved"


def test_e_edits_through_model_and_marks_reviewer_ownership_before_persist() -> None:
    log = ActionLog()
    state = _state()

    controller._daily_review_key(state, _key("e"), _actions(log))

    assert state.daily_review is not None
    item = state.daily_review.work_items[0].yesterday
    assert item is not None
    assert item.statement == "Edited Yesterday A"
    assert item.user_edited is True
    assert len(log.persisted) == 1


def test_uppercase_reorder_stays_inside_section_and_persists() -> None:
    log = ActionLog()
    draft = _draft()
    state = _state(draft)

    controller._daily_review_key(state, _key("J"), _actions(log))

    assert [
        work.id for work, _ in draft.ordered_items(DailySection.YESTERDAY)
    ] == ["yesterday-b", "yesterday-a"]
    assert [work.id for work, _ in draft.ordered_items(DailySection.TODAY)] == [
        "today-a"
    ]
    assert len(log.persisted) == 1


def test_v_only_toggles_daily_evidence_ui_state() -> None:
    log = ActionLog()
    state = _state()

    controller._daily_review_key(state, _key("v"), _actions(log))

    assert state.daily_expanded == {"yesterday-a"}
    assert log.persisted == []


@pytest.mark.parametrize(
    ("cursor", "section"),
    [
        (0, DailySection.YESTERDAY),
        (3, DailySection.TODAY),
        (5, DailySection.BLOCKERS),
    ],
)
def test_a_adds_to_focused_section_including_empty_section(
    cursor: int,
    section: DailySection,
) -> None:
    log = ActionLog()
    state = _state()
    state.daily_cursor = cursor

    controller._daily_review_key(state, _key("a"), _actions(log))

    assert log.added_sections == [section]
    assert state.daily_review is not None
    assert any(
        item.statement == f"Added {section.value}"
        for _, item in state.daily_review.ordered_items(section)
    )
    assert len(log.persisted) == 1


def test_b_returns_daily_review_to_main_without_discarding_draft() -> None:
    log = ActionLog()
    state = _state()
    original = state.daily_review

    controller._daily_review_key(state, _key("b"), _actions(log))

    assert state.screen is Screen.MAIN
    assert state.daily_review is original


def test_p_previews_without_mutating_draft_and_returns_to_daily_review() -> None:
    log = ActionLog()
    state = _state()
    assert state.daily_review is not None
    before = state.daily_review.model_copy(deep=True)

    controller._daily_review_key(state, _key("p"), _actions(log))

    assert log.previewed == [before]
    assert state.daily_review == before
    assert state.result == _result(None)
    assert state.preview_return_screen is Screen.DAILY_REVIEW
    assert state.screen is Screen.REPORT_PREVIEW


def test_g_generates_daily_result_and_daily_result_path_returns_to_it() -> None:
    log = ActionLog()
    state = _state()

    controller._daily_review_key(state, _key("g"), _actions(log))

    assert len(log.generated) == 1
    assert state.screen is Screen.DAILY_RESULT
    assert state.daily_result == _result("reports/daily-2026-08-13.md")

    state.daily_result_cursor = 1
    controller._daily_result_key(state, KeyPress(key=Key.ENTER))
    assert state.error is not None
    assert state.error.kind == "daily-path"
    assert state.screen is Screen.RECOVERABLE_ERROR
