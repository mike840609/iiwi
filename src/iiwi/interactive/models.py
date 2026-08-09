"""Short-lived state for the interactive Iiwi flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from iiwi.interactive.selection import noise_reason
from iiwi.models.time_range import DateRange
from iiwi.renderers.markdown import DetailLevel
from iiwi.services.scan import ScanResult


class Screen(StrEnum):
    MAIN = "main"
    REPORT_SETUP = "report_setup"
    SESSION_REVIEW = "session_review"
    SESSION_BROWSER = "session_browser"
    SESSION_PREVIEW = "session_preview"
    REPORT_RESULT = "report_result"
    REPORT_PREVIEW = "report_preview"
    RECOVERABLE_ERROR = "recoverable_error"
    HELP = "help"
    EXIT = "exit"


@dataclass
class ReportDraft:
    harness: str
    period: DateRange
    period_label: str | None = None
    include_subagents: bool = True
    sanitize: bool = False
    detail: DetailLevel = DetailLevel.FULL
    narrative: bool = True
    dry_run: bool = False
    scan: ScanResult | None = None
    selected_session_ids: set[str] = field(default_factory=set)

    def clear_scan(self) -> None:
        self.scan = None
        self.selected_session_ids.clear()

    def set_scan(self, scan: ScanResult) -> None:
        self.scan = scan
        self.selected_session_ids = {
            resolved.session.session_id
            for resolved in scan.resolved_sessions
            if noise_reason(resolved.session) is None
        }

    def set_harness(self, harness: str) -> None:
        if harness != self.harness:
            self.harness = harness
            self.clear_scan()

    def set_period(self, label: str | None, period: DateRange) -> None:
        """Carry the period's display name with the range that produced it."""
        if period != self.period:
            self.period = period
            self.clear_scan()
        self.period_label = label

    def set_include_subagents(self, include_subagents: bool) -> None:
        if include_subagents != self.include_subagents:
            self.include_subagents = include_subagents
            self.clear_scan()

    def set_sanitize(self, sanitize: bool) -> None:
        if sanitize != self.sanitize:
            self.sanitize = sanitize
            self.clear_scan()

    def set_detail(self, detail: DetailLevel) -> None:
        self.detail = detail

    def set_narrative(self, narrative: bool) -> None:
        self.narrative = narrative

    def set_dry_run(self, dry_run: bool) -> None:
        self.dry_run = dry_run
