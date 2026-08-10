from __future__ import annotations

from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.interactive.render import (
    render_help,
    render_session_browser,
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
    assert "? More" in text
    assert "b Back" in text
    assert "a All" not in text
    assert "n None" not in text
    assert "e Exclude repo" not in text
    assert "R Rescan" not in text
    assert "←→ hl" not in text


def test_browser_footer_shows_only_browse_essentials() -> None:
    console, stream = _console()

    render_session_browser(
        console,
        _scan(),
        expanded_repositories=set(),
        cursor=0,
    )

    text = stream.getvalue()
    assert "p Inspect" in text
    assert "/ Search" in text
    assert "? More" in text
    assert "b Back" in text
    assert "R Rescan" not in text
    assert "←→ hl" not in text


def test_help_keeps_hidden_power_shortcuts_discoverable() -> None:
    console, stream = _console()

    render_help(console)

    text = stream.getvalue()
    assert "a              Select all sessions" in text
    assert "n              Select no sessions" in text
    assert "e              Exclude a repository" in text
    assert "R              Rescan sessions" in text
    assert "←→ / hl" in text
