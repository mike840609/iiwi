"""Application-specific errors."""

from datetime import date, datetime


class IiwiError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(IiwiError):
    """Raised when configuration is invalid."""


class HarnessSourceError(IiwiError):
    """Raised when a harness source cannot be queried."""


class DailySourceUnavailableError(IiwiError):
    """Raised when no configured source can scan a Daily Standup window."""

    unavailable_harnesses: tuple[str, ...]
    standup_date: date
    since: datetime
    until: datetime

    def __init__(
        self,
        *,
        unavailable_harnesses: tuple[str, ...],
        standup_date: date,
        since: datetime,
        until: datetime,
    ) -> None:
        super().__init__("all Daily Standup harness sources are unavailable")
        self.unavailable_harnesses = unavailable_harnesses
        self.standup_date = standup_date
        self.since = since
        self.until = until


class SessionParseError(HarnessSourceError):
    """Raised when a harness session payload cannot be normalized."""


class ReportOutputError(IiwiError):
    """Raised when a report cannot be written safely."""


class ReportAlreadyExistsError(ReportOutputError):
    """Raised when report generation would overwrite an existing file."""


class NoSessionsError(IiwiError):
    """Raised when no session activity matches the requested period."""


class OutcomeSynthesisError(IiwiError):
    """Raised when outcome synthesis cannot produce valid evidence-backed output."""
