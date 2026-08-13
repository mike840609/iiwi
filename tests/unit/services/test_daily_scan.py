from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.errors import DailySourceUnavailableError, HarnessSourceError
from iiwi.models.repository import RepositoryIdentity, RepositoryIdentityType, ResolvedSession
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.daily_scan import DailyScanCoordinator, daily_window
from iiwi.services.scan import ScanResult


def test_daily_window_uses_calendar_midnights_across_dst() -> None:
    """Yesterday starts at local midnight, not 24 elapsed hours ago."""

    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 3, 9, 10, 30, tzinfo=tz)

    window = daily_window(now)

    assert window.standup_date.isoformat() == "2026-03-09"
    assert window.yesterday_start == datetime(2026, 3, 8, 0, 0, tzinfo=tz)
    assert window.today_start == datetime(2026, 3, 9, 0, 0, tzinfo=tz)
    assert window.period == DateRange(since=window.yesterday_start, until=now)


def test_daily_window_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        daily_window(datetime(2026, 3, 9, 10, 30))


class StaticScanner:
    def __init__(self, result: ScanResult) -> None:
        self.result = result

    def scan(self) -> ScanResult:
        return self.result


class UnavailableScanner:
    def scan(self) -> ScanResult:
        raise HarnessSourceError("source unavailable")


class BrokenScanner:
    def scan(self) -> ScanResult:
        raise RuntimeError("programming error")


def _resolved_session(
    session_id: str,
    repository_id: str,
    *,
    harness: str = "opencode",
) -> ResolvedSession:
    session = AgentSession(
        harness=harness,
        session_id=session_id,
        activities=[
            SessionActivity(
                activity_id=f"{session_id}:activity",
                activity_type=ActivityType.USER_MESSAGE,
                content="Implement Daily Standup.",
            )
        ],
    )
    repository = RepositoryIdentity(
        repository_id=repository_id,
        display_name=repository_id.rsplit("/", maxsplit=1)[-1],
        identity_type=RepositoryIdentityType.GIT_REMOTE,
        normalized_remote=repository_id.removeprefix("git:"),
        resolution_method="git_origin_remote",
    )
    return ResolvedSession(session=session, repository=repository)


def _scan(
    *,
    period: DateRange,
    resolved_sessions: list[ResolvedSession],
    candidate_count: int,
    failed_count: int,
    warnings: list[str],
    excluded_count: int = 0,
) -> ScanResult:
    return ScanResult(
        period=period,
        candidate_session_count=candidate_count,
        loaded_session_count=len(resolved_sessions),
        failed_session_count=failed_count,
        resolved_sessions=resolved_sessions,
        warnings=warnings,
        excluded_session_count=excluded_count,
    )


def test_daily_scan_coordinator_merges_successful_scans_in_scanner_order() -> None:
    window = daily_window(datetime(2026, 3, 9, 10, 30, tzinfo=ZoneInfo("Asia/Taipei")))
    opencode_session = _resolved_session("open-1", "git:github.com/example/api")
    claude_session = _resolved_session(
        "claude-1",
        "git:github.com/example/web",
        harness="claude-code",
    )
    coordinator = DailyScanCoordinator(
        window=window,
        scanners={
            "opencode": StaticScanner(
                _scan(
                    period=window.period,
                    resolved_sessions=[opencode_session],
                    candidate_count=2,
                    failed_count=1,
                    warnings=["OpenCode session warning"],
                    excluded_count=3,
                )
            ),
            "claude-code": StaticScanner(
                _scan(
                    period=window.period,
                    resolved_sessions=[claude_session],
                    candidate_count=1,
                    failed_count=0,
                    warnings=["Claude Code session warning"],
                )
            ),
        },
    )

    result = coordinator.scan()

    assert result.successful_harnesses == ("opencode", "claude-code")
    assert result.unavailable_harnesses == ()
    assert result.coverage_warnings == ()
    assert result.scan.period == window.period
    assert result.scan.candidate_session_count == 3
    assert result.scan.loaded_session_count == 2
    assert result.scan.failed_session_count == 1
    assert result.scan.excluded_session_count == 3
    assert result.scan.resolved_sessions == [opencode_session, claude_session]
    assert list(result.scan.sessions_by_repository) == [
        "git:github.com/example/api",
        "git:github.com/example/web",
    ]
    assert result.scan.warnings == ["OpenCode session warning", "Claude Code session warning"]


def test_daily_scan_coordinator_continues_when_one_harness_is_unavailable() -> None:
    window = daily_window(datetime(2026, 3, 9, 10, 30, tzinfo=ZoneInfo("Asia/Taipei")))
    claude_session = _resolved_session(
        "claude-1",
        "git:github.com/example/web",
        harness="claude-code",
    )
    coordinator = DailyScanCoordinator(
        window=window,
        scanners={
            "opencode": UnavailableScanner(),
            "claude-code": StaticScanner(
                _scan(
                    period=window.period,
                    resolved_sessions=[claude_session],
                    candidate_count=1,
                    failed_count=0,
                    warnings=["Claude Code session warning"],
                )
            ),
        },
    )

    result = coordinator.scan()

    assert result.successful_harnesses == ("claude-code",)
    assert result.unavailable_harnesses == ("opencode",)
    assert result.coverage_warnings == ("OpenCode activity could not be loaded.",)
    assert result.scan.resolved_sessions == [claude_session]
    assert result.scan.warnings == ["Claude Code session warning"]


def test_daily_scan_coordinator_preserves_window_when_all_harnesses_are_unavailable() -> None:
    window = daily_window(datetime(2026, 3, 9, 10, 30, tzinfo=ZoneInfo("Asia/Taipei")))
    coordinator = DailyScanCoordinator(
        window=window,
        scanners={
            "opencode": UnavailableScanner(),
            "claude-code": UnavailableScanner(),
        },
    )

    with pytest.raises(DailySourceUnavailableError) as caught:
        coordinator.scan()

    assert caught.value.unavailable_harnesses == ("opencode", "claude-code")
    assert caught.value.standup_date == window.standup_date
    assert caught.value.since == window.yesterday_start
    assert caught.value.until == window.now


def test_daily_scan_coordinator_counts_a_zero_activity_scan_as_successful() -> None:
    window = daily_window(datetime(2026, 3, 9, 10, 30, tzinfo=ZoneInfo("Asia/Taipei")))
    coordinator = DailyScanCoordinator(
        window=window,
        scanners={
            "codex": StaticScanner(
                _scan(
                    period=DateRange(
                        since=datetime(2026, 3, 1, tzinfo=ZoneInfo("Asia/Taipei")),
                        until=datetime(2026, 3, 2, tzinfo=ZoneInfo("Asia/Taipei")),
                    ),
                    resolved_sessions=[],
                    candidate_count=0,
                    failed_count=0,
                    warnings=[],
                )
            )
        },
    )

    result = coordinator.scan()

    assert result.successful_harnesses == ("codex",)
    assert result.unavailable_harnesses == ()
    assert result.coverage_warnings == ()
    assert result.scan.period == window.period
    assert result.scan.loaded_session_count == 0


def test_daily_scan_coordinator_propagates_non_source_errors() -> None:
    window = daily_window(datetime(2026, 3, 9, 10, 30, tzinfo=ZoneInfo("Asia/Taipei")))
    coordinator = DailyScanCoordinator(
        window=window,
        scanners={"opencode": BrokenScanner()},
    )

    with pytest.raises(RuntimeError, match="programming error"):
        coordinator.scan()
