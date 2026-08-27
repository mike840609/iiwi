from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.interactive.models import Screen
from iiwi.interactive.render import (
    render_daily_result,
    render_help,
    render_report_result,
    render_session_review,
)
from iiwi.interactive.selection import SelectionState
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import AgentSession
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(
            file=stream,
            color_system=None,
            force_terminal=False,
            width=100,
            height=25,
        ),
        stream,
    )


def _scan() -> ScanResult:
    period = DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )
    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="ses-1",
            title="Improve interactive UX",
            working_directory="/tmp/iiwi",
        ),
        repository=RepositoryIdentity(
            repository_id="repo-iiwi",
            display_name="iiwi",
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory="/tmp/iiwi",
            resolution_method="test",
        ),
    )
    return ScanResult(
        period=period,
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
        sessions_by_repository={"repo-iiwi": [resolved]},
    )


def test_review_footer_shows_core_actions_not_power_shortcuts() -> None:
    console, stream = _console()
    selection = SelectionState.from_scan(_scan())

    render_session_review(
        console,
        selection,
        expanded_repositories=set(),
        cursor=0,
    )

    text = stream.getvalue()
    assert "Space Select" in text
    assert "p Inspect" in text
    assert "/ Search" in text
    assert "g Report" in text
    assert "G Force" in text
    assert "? More" in text
    assert "b Back" in text
    assert "a All" not in text
    assert "n None" not in text
    assert "e Exclude repo" not in text
    assert "R Rescan" not in text
    assert "←→ hl" not in text


def test_review_hint_bar_shows_force_shortcut() -> None:
    console, stream = _console()
    selection = SelectionState.from_scan(_scan())

    render_session_review(
        console,
        selection,
        expanded_repositories=set(),
        cursor=0,
    )

    assert "G Force" in stream.getvalue()


def test_help_keeps_hidden_power_shortcuts_discoverable() -> None:
    console, stream = _console()

    render_help(console)

    text = stream.getvalue()
    assert "Select all sessions" in text
    assert "Select no sessions" in text
    assert "Exclude a repository" in text
    assert "Rescan sessions" in text
    assert "←→ / hl" in text


def test_help_documents_the_quick_review_keys_and_marks_the_overloaded_ones() -> None:
    """Quick Review's hint bar sends people here, so the four reused keys must be flagged."""

    stream = StringIO()
    console = Console(
        file=stream,
        color_system=None,
        force_terminal=False,
        width=100,
        height=40,
    )

    render_help(console)

    text = stream.getvalue()
    assert "Quick Review" in text
    assert "J / K          Reorder the focused outcome within its section" in text
    assert "v              Show or hide the focused outcome's evidence" in text
    assert "s              Split a merged outcome into its source groups" in text
    assert "Space          Include or exclude the focused outcome" in text
    # `a`, `e`, `p` and `g` all mean something else on Quick Review.
    for line in ("a *", "e *", "p *", "g * / G"):
        assert line in text


def test_q_reads_the_same_on_both_result_screens_and_in_daily_help() -> None:
    """`q` and `b` do the same thing now, so one vocabulary has to say so."""

    report_console, report_stream = _console()
    render_report_result(
        report_console,
        period=_scan().period,
        repository_count=1,
        session_count=1,
        output_path=Path("reports/worklog.md"),
        selected=0,
    )

    daily_console, daily_stream = _console()
    render_daily_result(daily_console, output_path=Path("reports/daily.md"), selected=0)

    assert "q Back" in report_stream.getvalue()
    assert "q Back" in daily_stream.getvalue()
    assert "q Menu" not in daily_stream.getvalue()

    help_console, help_stream = _console()
    render_help(help_console, screen=Screen.DAILY_REVIEW)

    daily_help = help_stream.getvalue()
    assert "b / Esc        Back to the main menu" in daily_help
    assert "q              Back to the main menu" in daily_help


def test_help_documents_the_history_keys_and_marks_the_overloaded_one() -> None:
    """`h` is documented as expanding tree rows, so History's meaning must be listed too.

    `o` exists on no other screen, so without this block the help screen is the
    one place a user looking for it would come up empty.
    """

    stream = StringIO()
    console = Console(
        file=stream,
        color_system=None,
        force_terminal=False,
        width=100,
        height=44,
    )

    render_help(console)

    text = stream.getvalue()
    assert "History" in text
    assert "Enter / p      Preview the selected report" in text
    assert "o              Open the report in $VISUAL / $EDITOR, or the system viewer" in text
    assert "h              Show or hide reports whose file is gone" in text
    # `h` scrolls a tree row everywhere else; the marker is what sends a reader
    # down to the per-screen blocks.
    assert "←→ / hl *" in text
    assert "* these keys mean something else on the screens below" in text
