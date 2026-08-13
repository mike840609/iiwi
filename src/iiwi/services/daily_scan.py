"""Daily, multi-harness session scan coordination."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol

from iiwi.errors import DailySourceUnavailableError, HarnessSourceError
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult
from iiwi.sessions.hierarchy import group_resolved_sessions


@dataclass(frozen=True)
class DailyWindow:
    """The local-calendar window used for one Daily Standup."""

    standup_date: date
    yesterday_start: datetime
    today_start: datetime
    now: datetime

    @property
    def period(self) -> DateRange:
        return DateRange(since=self.yesterday_start, until=self.now)


def daily_window(now: datetime) -> DailyWindow:
    """Derive a Daily Standup window from local calendar midnights."""

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.date()
    today_start = datetime.combine(today, time.min, tzinfo=now.tzinfo)
    yesterday_start = datetime.combine(
        today - timedelta(days=1),
        time.min,
        tzinfo=now.tzinfo,
    )
    return DailyWindow(
        standup_date=today,
        yesterday_start=yesterday_start,
        today_start=today_start,
        now=now,
    )


@dataclass(frozen=True)
class DailyScanResult:
    """The merged result and source coverage for one Daily Standup."""

    window: DailyWindow
    scan: ScanResult
    successful_harnesses: tuple[str, ...]
    unavailable_harnesses: tuple[str, ...]
    coverage_warnings: tuple[str, ...]


class Scanner(Protocol):
    """A single-harness scan operation."""

    def scan(self) -> ScanResult: ...


class DailyScanCoordinator:
    """Merge independent single-harness scans for a Daily Standup."""

    def __init__(
        self,
        *,
        window: DailyWindow,
        scanners: Mapping[str, Scanner],
    ) -> None:
        self._window = window
        self._scanners = scanners

    def scan(self) -> DailyScanResult:
        successful_harnesses: list[str] = []
        unavailable_harnesses: list[str] = []
        scans: list[ScanResult] = []
        for harness, scanner in self._scanners.items():
            try:
                scans.append(scanner.scan())
            except HarnessSourceError:
                unavailable_harnesses.append(harness)
                continue
            successful_harnesses.append(harness)

        if not successful_harnesses:
            raise DailySourceUnavailableError(
                unavailable_harnesses=tuple(unavailable_harnesses),
                standup_date=self._window.standup_date,
                since=self._window.yesterday_start,
                until=self._window.now,
            )

        resolved_sessions = [
            session for scan in scans for session in scan.resolved_sessions
        ]
        scan = ScanResult(
            period=self._window.period,
            candidate_session_count=sum(item.candidate_session_count for item in scans),
            loaded_session_count=sum(item.loaded_session_count for item in scans),
            failed_session_count=sum(item.failed_session_count for item in scans),
            resolved_sessions=resolved_sessions,
            sessions_by_repository=group_resolved_sessions(resolved_sessions),
            warnings=[warning for item in scans for warning in item.warnings],
            excluded_session_count=sum(item.excluded_session_count for item in scans),
        )
        return DailyScanResult(
            window=self._window,
            scan=scan,
            successful_harnesses=tuple(successful_harnesses),
            unavailable_harnesses=tuple(unavailable_harnesses),
            coverage_warnings=tuple(
                f"{_display_harness_name(harness)} activity could not be loaded."
                for harness in unavailable_harnesses
            ),
        )


def _display_harness_name(harness: str) -> str:
    return {
        "opencode": "OpenCode",
        "claude-code": "Claude Code",
        "codex": "Codex",
    }.get(harness, harness)
