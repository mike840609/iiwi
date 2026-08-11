"""Application-specific errors."""


class IiwiError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(IiwiError):
    """Raised when configuration is invalid."""


class HarnessSourceError(IiwiError):
    """Raised when a harness source cannot be queried."""


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
