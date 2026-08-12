"""Short-lived state for the interactive Iiwi flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from iiwi.interactive.selection import noise_reason
from iiwi.models.report_options import DetailLevel, ReportType
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

_UNSET_DETAIL = cast(DetailLevel, object())


class Screen(StrEnum):
    MAIN = "main"
    REPORT_SETUP = "report_setup"
    SESSION_REVIEW = "session_review"
    SESSION_BROWSER = "session_browser"
    SESSION_PREVIEW = "session_preview"
    OUTCOME_REVIEW = "outcome_review"
    REPORT_RESULT = "report_result"
    REPORT_PREVIEW = "report_preview"
    RECOVERABLE_ERROR = "recoverable_error"
    HELP = "help"
    HISTORY = "history"
    EXIT = "exit"


@dataclass
class ReportDraft:
    harness: str
    period: DateRange
    period_label: str | None = None
    include_subagents: bool = True
    sanitize: bool = False
    report_type: ReportType = ReportType.ENGINEERING
    detail: DetailLevel = _UNSET_DETAIL
    detail_overridden: bool = False
    narrative: bool = True
    dry_run: bool = False
    generation_notice: str | None = None
    scan: ScanResult | None = None
    selected_session_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.detail is _UNSET_DETAIL:
            self.detail = self.default_detail(self.report_type)
        else:
            self.detail_overridden = True

    @staticmethod
    def default_detail(report_type: ReportType) -> DetailLevel:
        return DetailLevel.BRIEF if report_type is ReportType.MANAGER else DetailLevel.FULL

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
        self.detail_overridden = True

    def set_report_type(self, report_type: ReportType) -> None:
        self.report_type = report_type
        if not self.detail_overridden:
            self.detail = self.default_detail(report_type)

    def set_narrative(self, narrative: bool) -> None:
        self.narrative = narrative

    def set_dry_run(self, dry_run: bool) -> None:
        self.dry_run = dry_run
