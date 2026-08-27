"""Pin where `q` lands on every screen.

`q` means "back one level" everywhere except the main menu, where it exits.
Each case reaches its screen through the same key path a user takes, so a
destination that depends on state the arrival sets — Daily's preview writing
`preview_return_screen` — breaks the test when that state stops being set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi.interactive import controller
from iiwi.interactive.controller import InteractiveActions, InteractiveReportResult
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import EvidenceRef, Outcome, OutcomeReviewDraft, OutcomeStatus
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")

ENTER = KeyPress(key=Key.ENTER)
RIGHT = KeyPress(key=Key.RIGHT)


def char(value: str) -> KeyPress:
    return KeyPress(char=value)


def _console() -> Console:
    return Console(file=StringIO(), color_system=None, force_terminal=False, width=110)


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _scan() -> ScanResult:
    sessions = [
        ResolvedSession(
            session=AgentSession(
                harness="opencode",
                session_id="ses-0",
                title="Session 0",
                working_directory="/tmp/repo-a",
                activities=[
                    SessionActivity(
                        activity_id=f"act-{index}",
                        activity_type=ActivityType.USER_MESSAGE,
                    )
                    for index in range(5)
                ],
            ),
            repository=RepositoryIdentity(
                repository_id="repo-a",
                display_name="repo-a",
                identity_type=RepositoryIdentityType.PATH_FALLBACK,
                working_directory="/tmp/repo-a",
                resolution_method="test",
            ),
        )
    ]
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )


def _daily_draft() -> DailyStandupDraft:
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
                id="today-a",
                today=DailySectionItem(
                    statement="Today A",
                    source=DailyStatementSource.ACTIVITY_TODAY,
                    rank=0,
                ),
            ),
        ],
    )


def _outcomes() -> list[Outcome]:
    return [
        Outcome(
            id="outcome-1",
            title="Outcome 1",
            status=OutcomeStatus.IN_PROGRESS,
            impact="Impact",
            rank=0,
            evidence_refs=[EvidenceRef(session_id="ses-0", repository_id="repo-a")],
        )
    ]


def _result(path: str | None) -> InteractiveReportResult:
    return InteractiveReportResult(
        output_path=Path(path) if path else None,
        content="report",
        repository_count=1,
        session_count=1,
    )


def _actions() -> InteractiveActions:
    return InteractiveActions(
        new_draft=lambda: ReportDraft(harness="opencode", period=_period()),
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last 7 days", _period()),
        scan=lambda draft: _scan(),
        generate=lambda draft, scan, force: _result("reports/worklog.md"),
        synthesize=lambda draft, scan, force: OutcomeReviewDraft(
            outcomes=_outcomes(), report_type=draft.report_type
        ),
        generate_reviewed=lambda draft, scan, review, force: _result("reports/worklog.md"),
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [f"{harness}: ok"],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
        start_daily=lambda previous: previous or _daily_draft(),
        continue_daily_empty=lambda error, previous: previous or _daily_draft(),
        persist_daily=lambda draft: None,
        preview_daily=lambda draft: _result(None),
        generate_daily=lambda draft: _result("reports/daily-2026-08-13.md"),
        edit_daily_statement=lambda statement: statement,
        add_daily_statement=lambda section: None,
    )


@dataclass(frozen=True)
class QCase:
    """One row of the contract: how a screen is reached, and where `q` lands."""

    label: str
    arrival: tuple[KeyPress, ...]
    destination: Screen


# Main menu rows, by the number key that selects them.
_ACTIVITY = char("1")
_DAILY = char("2")
_REPORT = char("3")
_HISTORY = char("4")
_DOCTOR = char("5")
_SETTINGS = char("6")

Q_CONTRACT: dict[Screen, tuple[QCase, ...]] = {
    Screen.MAIN: (QCase("main menu", (), Screen.EXIT),),
    Screen.REPORT_SETUP: (QCase("report setup", (_REPORT,), Screen.MAIN),),
    Screen.SESSION_REVIEW: (
        QCase("review opened from the main menu", (_ACTIVITY,), Screen.MAIN),
        QCase("review opened from setup", (_REPORT, char("r")), Screen.REPORT_SETUP),
    ),
    Screen.SESSION_PREVIEW: (
        QCase(
            "session preview opened from review",
            (_REPORT, char("r"), RIGHT, char("j"), char("p")),
            Screen.SESSION_REVIEW,
        ),
    ),
    Screen.OUTCOME_REVIEW: (QCase("quick review", (_REPORT, char("g")), Screen.SESSION_REVIEW),),
    Screen.DAILY_REVIEW: (QCase("daily review", (_DAILY,), Screen.MAIN),),
    Screen.DAILY_RESULT: (QCase("daily result", (_DAILY, char("g")), Screen.MAIN),),
    Screen.REPORT_RESULT: (QCase("report result", (_REPORT, char("g"), char("g")), Screen.MAIN),),
    Screen.REPORT_PREVIEW: (
        QCase(
            "preview opened from daily review",
            (_DAILY, char("p")),
            Screen.DAILY_REVIEW,
        ),
        QCase(
            "preview opened from quick review",
            (_REPORT, char("g"), char("p")),
            Screen.OUTCOME_REVIEW,
        ),
    ),
    Screen.RECOVERABLE_ERROR: (
        QCase("check-setup output", (_DOCTOR,), Screen.MAIN),
        QCase(
            "report path shown from the result screen",
            (_REPORT, char("g"), char("g"), char("j"), char("j"), ENTER),
            Screen.REPORT_RESULT,
        ),
    ),
    Screen.HELP: (
        QCase("help opened from the main menu", (char("?"),), Screen.MAIN),
        QCase("help opened from review", (_ACTIVITY, char("?")), Screen.SESSION_REVIEW),
    ),
    Screen.HISTORY: (QCase("history", (_HISTORY,), Screen.MAIN),),
    Screen.HISTORY_PREVIEW: (QCase("history preview", (_HISTORY, ENTER), Screen.HISTORY),),
    Screen.SETTINGS: (QCase("settings", (_SETTINGS,), Screen.MAIN),),
}

_CASES = [(screen, case) for screen, cases in Q_CONTRACT.items() for case in cases]


@pytest.mark.parametrize(
    ("screen", "case"),
    _CASES,
    ids=[case.label for _, case in _CASES],
)
def test_q_returns_to_the_declared_screen(
    screen: Screen, case: QCase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # HISTORY_PREVIEW needs a real file so Enter finds a visible entry.
    if screen is Screen.HISTORY_PREVIEW:
        from datetime import datetime

        from iiwi.history import HistoryEntry, HistoryKind, append_history

        report = tmp_path / "preview.md"
        report.write_text("preview", encoding="utf-8")
        monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
        append_history(
            HistoryEntry(
                generated_at=datetime.now(TZ),
                since=datetime.now(TZ),
                until=datetime.now(TZ),
                output_path=report,
                repository_count=1,
                session_count=1,
                kind=HistoryKind.REPORT,
                harness="opencode",
            )
        )
    actions = _actions()
    console = _console()
    state = controller._State()
    for key in case.arrival:
        controller._dispatch(state, key, actions, console)
    assert state.screen is screen, f"arrival landed on {state.screen.value}"

    controller._dispatch(state, char("q"), actions, console)

    assert state.screen is case.destination


@pytest.mark.parametrize(
    "screen",
    [screen for screen in Screen if screen is not Screen.EXIT],
    ids=lambda screen: screen.value,
)
def test_every_screen_declares_a_q_destination(screen: Screen) -> None:
    assert screen in Q_CONTRACT, (
        f"{screen.value} declares no `q` destination. Add a QCase to Q_CONTRACT with "
        "the keys that reach the screen and the screen `q` must return to."
    )


def test_daily_preview_returns_to_daily_review_because_the_arrival_records_it() -> None:
    """The `q` destination is carried by state, not by the preview screen.

    `q` on a preview reads `preview_return_screen`; only the Daily preview path
    sets it to DAILY_REVIEW. Without that record the same key discards the
    standup draft to the main menu, so pin the record as well as the landing.
    """

    actions = _actions()
    console = _console()
    state = controller._State()
    controller._dispatch(state, _DAILY, actions, console)
    draft = state.daily_review
    controller._dispatch(state, char("p"), actions, console)

    assert state.screen is Screen.REPORT_PREVIEW
    assert state.preview_return_screen is Screen.DAILY_REVIEW

    controller._dispatch(state, char("q"), actions, console)

    assert state.screen is Screen.DAILY_REVIEW
    assert state.daily_review is draft
