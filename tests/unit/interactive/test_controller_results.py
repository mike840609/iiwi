from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from agent_worklog.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from agent_worklog.interactive.input import Key, KeyPress
from agent_worklog.interactive.models import ReportDraft
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import ActivityType, AgentSession, SessionActivity
from agent_worklog.models.time_range import DateRange
from agent_worklog.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def char(value: str) -> KeyPress:
    return KeyPress(char=value)


class ScriptedInput:
    def __init__(self, keys: list[KeyPress]) -> None:
        self._keys: Iterator[KeyPress] = iter(keys)

    def __enter__(self) -> ScriptedInput:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read_key(self) -> KeyPress:
        return next(self._keys)


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _activities(count: int = 5) -> list[SessionActivity]:
    """Real scans never yield activity-less sessions; keep fixtures substantive."""

    return [
        SessionActivity(activity_id=f"act-{i}", activity_type=ActivityType.USER_MESSAGE)
        for i in range(count)
    ]


def _scan() -> ScanResult:
    repository = RepositoryIdentity(
        repository_id="repo-a",
        display_name="repo-a",
        identity_type=RepositoryIdentityType.PATH_FALLBACK,
        working_directory="/tmp/repo-a",
        resolution_method="test",
    )
    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="ses-a",
            title="Session A",
            working_directory="/tmp/repo-a",
            activities=_activities(),
        ),
        repository=repository,
    )
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
        sessions_by_repository={"repo-a": [resolved]},
    )


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return Console(file=stream, color_system=None, force_terminal=False, width=100), stream


def _actions() -> InteractiveActions:
    draft = ReportDraft(harness="opencode", period=_period())
    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last week", _period()),
        scan=lambda current: _scan(),
        generate=lambda current, scan, force: InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report",
            repository_count=1,
            session_count=1,
        ),
        doctor=lambda harness: ["OK opencode version: 1.0", "OK git: git version 2.0"],
        edit_settings=lambda: None,
    )


def test_doctor_result_uses_a_persistent_result_screen() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput([char("3"), KeyPress(key=Key.ENTER), char("q")]),
        console=console,
    )

    text = stream.getvalue()
    assert "Check Setup" in text
    assert "OK opencode version: 1.0" in text
    assert "OK git: git version 2.0" in text


def test_settings_completion_returns_through_a_visible_result_screen() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput([char("4"), KeyPress(key=Key.ENTER), char("q")]),
        console=console,
    )

    text = stream.getvalue()
    assert "Settings" in text
    assert "Settings editor finished." in text


def test_print_report_path_opens_a_persistent_path_screen() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("1"),
                char("r"),
                char("g"),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.ENTER),
                char("b"),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Report path" in text
    assert text.count("reports/worklog.md") >= 2


def test_p_opens_session_preview_from_review_and_back_returns_to_it() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("1"),
                char("r"),
                KeyPress(key=Key.RIGHT),
                KeyPress(key=Key.DOWN),
                char("p"),
                char("b"),
                char("b"),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Session Preview" in text
    assert "Session A" in text


def test_p_opens_session_preview_from_browse_and_returns() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.ENTER),
                KeyPress(key=Key.RIGHT),
                KeyPress(key=Key.DOWN),
                char("p"),
                char("b"),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Session Preview" in text


def test_p_on_a_repository_row_does_not_open_a_preview() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("1"),
                char("r"),
                char("p"),
                char("b"),
                char("b"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Session Preview" not in text
