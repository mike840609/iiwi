"""Pending-action feedback must paint before long operations block the key loop.

Daily Standup's scan/synthesis, outcome synthesis, and report generation all
run inline in the key loop. Without a pre-block paint the UI freezes on the
last frame for minutes, so each blocking call must first repaint the current
frame plus one dim pending line.
"""

from __future__ import annotations

from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.interactive import controller
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.models.daily import DailyStandupDraft
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")

DAILY_PENDING = "Scanning sessions and synthesizing outcomes"
SYNTHESIS_PENDING = "Synthesizing outcomes"
GENERATION_PENDING = "Generating report"
CANCEL_AFFORDANCE = "(Ctrl-C to cancel)"


def char(value: str) -> KeyPress:
    return KeyPress(char=value)


class ScriptedInput:
    def __init__(self, keys: list[KeyPress]) -> None:
        self._keys = iter(keys)

    def __enter__(self) -> ScriptedInput:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read_key(self) -> KeyPress:
        return next(self._keys)


class RecordingConsole(Console):
    """Console that logs every print so tests can assert paint/call order."""

    def __init__(self, events: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.events = events

    def print(self, *objects: Any, **kwargs: Any) -> None:
        self.events.append(f"paint:{' '.join(str(object) for object in objects)}")
        super().print(*objects, **kwargs)


def _recording_console(events: list[str]) -> RecordingConsole:
    return RecordingConsole(
        events,
        file=StringIO(),
        color_system=None,
        force_terminal=False,
        width=100,
        height=40,
    )


def _event_index(events: list[str], fragment: str) -> int:
    matches = [index for index, event in enumerate(events) if fragment in event]
    assert matches, f"no event containing {fragment!r}; events were {events}"
    return matches[0]


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _activities(count: int = 5) -> list[SessionActivity]:
    return [
        SessionActivity(activity_id=f"act-{i}", activity_type=ActivityType.USER_MESSAGE)
        for i in range(count)
    ]


def _resolved(session_id: str, repository_id: str) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=session_id,
            working_directory=f"/tmp/{repository_id}",
            activities=_activities(),
        ),
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=repository_id,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repository_id}",
            resolution_method="test",
        ),
    )


def _scan() -> ScanResult:
    sessions = [
        _resolved("ses-a1", "repo-a"),
        _resolved("ses-a2", "repo-a"),
        _resolved("ses-b1", "repo-b"),
    ]
    return ScanResult(
        period=_period(),
        candidate_session_count=3,
        loaded_session_count=3,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions[:2], "repo-b": sessions[2:]},
    )


def _outcomes() -> list[Outcome]:
    return [
        Outcome(
            id="outcome-1",
            title="Outcome 1",
            status=OutcomeStatus.IN_PROGRESS,
            impact="Impact",
            rank=0,
            evidence_refs=[EvidenceRef(session_id="ses-a1", repository_id="repo-a")],
        )
    ]


def _daily_draft() -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=date(2026, 8, 13),
        scan_since=_period().since,
        scan_until=_period().until,
    )


def _result() -> InteractiveReportResult:
    return InteractiveReportResult(
        output_path=Path("reports/worklog.md"),
        content="report-content",
        repository_count=1,
        session_count=1,
    )


def _actions(**overrides: Any) -> InteractiveActions:
    values: dict[str, Any] = dict(
        new_draft=lambda: ReportDraft(harness="opencode", period=_period()),
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last week", _period()),
        scan=lambda draft: _scan(),
        generate=lambda draft, scan, force: _result(),
        synthesize=lambda draft, scan, force: OutcomeReviewDraft(
            outcomes=_outcomes()
        ),
        generate_reviewed=lambda draft, scan, review, force: _result(),
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
        start_daily=lambda previous: _daily_draft(),
    )
    values.update(overrides)
    return InteractiveActions(**values)


def test_daily_standup_paints_pending_line_before_start_daily_blocks() -> None:
    events: list[str] = []

    def slow_start_daily(previous: DailyStandupDraft | None) -> DailyStandupDraft:
        events.append("call:start_daily")
        return _daily_draft()

    run_interactive(
        actions=_actions(start_daily=slow_start_daily),
        input_source=ScriptedInput([char("2"), char("q"), char("q")]),
        console=_recording_console(events),
    )

    pending = _event_index(events, DAILY_PENDING)
    assert CANCEL_AFFORDANCE in events[pending]
    assert pending < _event_index(events, "call:start_daily")


def test_direct_daily_startup_paints_pending_line_before_start_daily_blocks() -> None:
    events: list[str] = []

    def slow_start_daily(previous: DailyStandupDraft | None) -> DailyStandupDraft:
        events.append("call:start_daily")
        return _daily_draft()

    run_interactive(
        actions=_actions(start_daily=slow_start_daily),
        input_source=ScriptedInput([char("q"), char("q")]),
        console=_recording_console(events),
        initial_screen=Screen.DAILY_REVIEW,
    )

    pending = _event_index(events, DAILY_PENDING)
    assert CANCEL_AFFORDANCE in events[pending]
    assert pending < _event_index(events, "call:start_daily")


def test_outcome_synthesis_paints_pending_line_before_synthesize_blocks() -> None:
    events: list[str] = []

    def slow_synthesize(
        draft: ReportDraft,
        scan: ScanResult,
        force: bool,
    ) -> OutcomeReviewDraft:
        events.append("call:synthesize")
        return OutcomeReviewDraft(outcomes=_outcomes())

    run_interactive(
        actions=_actions(synthesize=slow_synthesize),
        input_source=ScriptedInput(
            [
                char("3"),
                char("r"),
                KeyPress(key=Key.SPACE),
                char("g"),
                char("b"),
                char("q"),
                char("q"),
                char("q"),
            ]
        ),
        console=_recording_console(events),
    )

    pending = _event_index(events, SYNTHESIS_PENDING)
    assert CANCEL_AFFORDANCE in events[pending]
    assert pending < _event_index(events, "call:synthesize")


def test_report_generation_paints_pending_line_before_generate_blocks() -> None:
    events: list[str] = []
    draft = ReportDraft(harness="opencode", period=_period(), narrative=False)

    def slow_generate(
        draft: ReportDraft,
        scan: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        events.append("call:generate")
        return _result()

    actions = _actions(new_draft=lambda: draft, generate=slow_generate)
    run_interactive(
        actions=actions,
        input_source=ScriptedInput(
            [
                char("3"),
                char("r"),
                KeyPress(key=Key.SPACE),
                char("g"),
                char("q"),
                char("q"),
            ]
        ),
        console=_recording_console(events),
    )

    pending = _event_index(events, GENERATION_PENDING)
    assert CANCEL_AFFORDANCE in events[pending]
    assert pending < _event_index(events, "call:generate")


def test_pending_line_names_ctrl_c_and_renders_dim_below_the_frame() -> None:
    stream = StringIO()
    # Pin the color system explicitly: rich caches parsed styles process-wide
    # and freezes their ANSI codes on first render, so an auto-detected console
    # here would leak whatever this machine guessed into every later test that
    # renders the same styles (the wordmark's scarlet included).
    console = Console(
        file=stream,
        color_system="truecolor",
        force_terminal=True,
        width=100,
        height=40,
    )

    controller._paint_pending(controller._State(), console, SYNTHESIS_PENDING)

    written = stream.getvalue()
    plain_stream = StringIO()
    plain_console = Console(
        file=plain_stream, color_system=None, force_terminal=False, width=100, height=40
    )
    controller._render_screen(controller._State(), plain_console)
    frame = plain_stream.getvalue()
    pending_line = f"⏳ {SYNTHESIS_PENDING}  {CANCEL_AFFORDANCE}"
    assert pending_line in written
    assert "\x1b[2m" in written  # style="dim" reaches the terminal as SGR 2
    assert written.index(frame.splitlines()[0]) < written.index(pending_line)
