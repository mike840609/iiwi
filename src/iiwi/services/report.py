"""Repository worklog generation orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from iiwi.errors import HarnessSourceError, ReportAlreadyExistsError
from iiwi.extraction.pipeline import extract_evidence
from iiwi.models.evidence import RepositoryEvidence, SessionEvidence
from iiwi.models.outcome import OutcomeReviewDraft
from iiwi.models.report import RepositorySummary, WorklogReport
from iiwi.models.time_range import DateRange
from iiwi.progress import NullProgressReporter, ProgressReporter, ProgressStage
from iiwi.renderers.markdown import (
    DetailLevel,
    MarkdownRenderer,
    render_narrative,
)
from iiwi.security.redactor import redact_text, redact_value
from iiwi.security.secure_files import atomic_secure_write
from iiwi.services.scan import ScanResult, ScanService
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
from iiwi.sessions.hierarchy import count_child_sessions_by_repository
from iiwi.summarizers.base import RepositorySummarizer
from iiwi.summarizers.opencode_run import (
    OpenCodeRunError,
    OpenCodeRunner,
    build_summary_prompt,
)
from iiwi.summarizers.transcript import build_grouped_transcript


class Renderer(Protocol):
    def render(
        self,
        report: WorklogReport,
        *,
        detail: DetailLevel = DetailLevel.FULL,
    ) -> str: ...

    def render_outcomes(
        self,
        report: WorklogReport,
        *,
        detail: DetailLevel = DetailLevel.FULL,
    ) -> str: ...


@dataclass(frozen=True)
class ReportGenerationResult:
    report: WorklogReport
    content: str
    output_path: Path
    scan: ScanResult

    @property
    def warnings(self) -> list[str]:
        """Return report warnings for CLI and integration consumers."""

        return self.report.warnings


class ReportService:
    """Generate a redacted repository-based Markdown worklog."""

    def __init__(
        self,
        *,
        scan_service: ScanService,
        summarizer: RepositorySummarizer,
        renderer: Renderer | MarkdownRenderer,
        period: DateRange,
        output_path: Path,
        now_factory: Callable[[], datetime],
        usage_provider: Callable[[ScanResult], str] | None = None,
        usage_days: int | None = None,
        detail: DetailLevel = DetailLevel.FULL,
        progress: ProgressReporter | None = None,
        initial_warnings: list[str] | None = None,
        narrative: bool = False,
        opencode_runner: OpenCodeRunner | None = None,
        include_subagents: bool = False,
        sanitized: bool = False,
    ) -> None:
        self._scan_service = scan_service
        self._summarizer = summarizer
        self._renderer = renderer
        self._period = period
        self._output_path = output_path
        self._now_factory = now_factory
        self._usage_provider = usage_provider
        self._usage_days = usage_days
        self._detail = detail
        self._progress = progress if progress is not None else NullProgressReporter()
        self._initial_warnings = list(initial_warnings or [])
        self._narrative = narrative
        self._opencode_runner = opencode_runner
        self._include_subagents = include_subagents
        self._sanitized = sanitized

    def _repository_evidence(self, scan: ScanResult) -> list[RepositoryEvidence]:
        child_counts = count_child_sessions_by_repository(scan.resolved_sessions)
        repositories: list[RepositoryEvidence] = []
        self._progress.start(
            ProgressStage.PREPARING_EVIDENCE,
            total=len(scan.sessions_by_repository),
        )
        for completed, (repository_id, resolved_items) in enumerate(
            scan.sessions_by_repository.items(),
            start=1,
        ):
            first = resolved_items[0].repository
            sessions: list[SessionEvidence] = []
            branches: list[str] = []
            for resolved in resolved_items:
                extracted = extract_evidence(resolved)
                redacted = redact_value(extracted.model_dump(mode="json"))
                sessions.append(SessionEvidence.model_validate(redacted))
                branch = resolved.repository.branch
                if branch and branch not in branches:
                    branches.append(branch)
            repositories.append(
                RepositoryEvidence(
                    repository_id=repository_id,
                    display_name=first.display_name,
                    normalized_remote=first.normalized_remote,
                    branches=branches,
                    sessions=sessions,
                    child_session_count=child_counts.get(repository_id, 0),
                )
            )
            self._progress.advance(completed)
        return repositories

    def _collect_usage(
        self,
        scan: ScanResult,
        warnings: list[str],
    ) -> str | None:
        if self._usage_provider is None:
            return None
        self._progress.start(ProgressStage.COLLECTING_USAGE)
        try:
            return redact_text(self._usage_provider(scan))
        except HarnessSourceError as exc:
            warnings.append(f"usage statistics unavailable: {exc}")
            return None

    def _structured_report(
        self,
        scan: ScanResult,
        warnings: list[str],
    ) -> WorklogReport:
        evidence_items = self._repository_evidence(scan)
        summaries: list[RepositorySummary] = []
        self._progress.start(
            ProgressStage.SUMMARIZING_REPOSITORIES,
            total=len(evidence_items),
        )
        for completed, evidence in enumerate(evidence_items, start=1):
            summaries.append(self._summarizer.summarize(evidence))
            drain_warnings = getattr(self._summarizer, "drain_warnings", None)
            if callable(drain_warnings):
                warnings.extend(cast(list[str], drain_warnings()))
            self._progress.advance(completed)
        summaries.sort(key=lambda item: item.display_name.casefold())
        usage_text = self._collect_usage(scan, warnings)
        return WorklogReport(
            generated_at=self._now_factory(),
            period=self._period,
            repositories=summaries,
            usage_text=usage_text,
            usage_days=self._usage_days if usage_text else None,
            warnings=[redact_text(warning) for warning in warnings],
        )

    def _narrative_report(
        self,
        scan: ScanResult,
        warnings: list[str],
    ) -> WorklogReport:
        if self._opencode_runner is None:
            raise OpenCodeRunError(
                "no local opencode run driver configured for narrative mode"
            )
        self._progress.start(ProgressStage.SUMMARIZING_REPOSITORIES, total=1)
        # FULL asks the model for a Usage Overview, so the real statistics must
        # reach the transcript (`--file`) before the model call; BRIEF never
        # asks for usage, so it is not collected here either.
        usage_text = (
            self._collect_usage(scan, warnings)
            if self._detail is DetailLevel.FULL
            else None
        )
        transcript = build_grouped_transcript(
            sessions_by_repository=scan.sessions_by_repository,
            period=self._period,
            generated_at=self._now_factory(),
            include_subagents=self._include_subagents,
            sanitized=self._sanitized,
            usage_text=usage_text,
        )
        days = self._usage_days or max(1, (self._period.until - self._period.since).days)
        narrative = self._opencode_runner.run(
            transcript=transcript,
            prompt=build_summary_prompt(days, detail=self._detail),
            title=(
                f"{IIWI_SESSION_TITLE_PREFIX}narrative "
                f"{self._period.since.date().isoformat()} "
                f"to {self._period.until.date().isoformat()}"
            ),
        )
        self._progress.advance(1)
        # No `usage_text`: the narrative owns the usage section (fed by the
        # transcript); carrying it would make the renderer append a second,
        # competing `## Usage` block.
        return WorklogReport(
            generated_at=self._now_factory(),
            period=self._period,
            repositories=[],
            narrative_text=narrative,
            warnings=[redact_text(warning) for warning in warnings],
        )

    def generate(
        self,
        *,
        force: bool = False,
        dry_run: bool = False,
        scan: ScanResult | None = None,
    ) -> ReportGenerationResult:
        destination = self._output_path.expanduser()
        if not dry_run and not force and destination.exists():
            raise ReportAlreadyExistsError(f"report already exists: {destination}")
        if scan is None:
            scan = self._scan_service.scan()
        warnings = [*self._initial_warnings, *scan.warnings]
        narrative_content = self._narrative
        if self._narrative:
            try:
                report = self._narrative_report(scan, warnings)
            except OpenCodeRunError as exc:
                warnings.append(
                    f"opencode run unavailable; used structured fallback ({exc})"
                )
                report = self._structured_report(scan, warnings)
                narrative_content = False
        else:
            report = self._structured_report(scan, warnings)
        self._progress.start(ProgressStage.RENDERING_REPORT)
        if narrative_content:
            timezone = getattr(
                self._period.since.tzinfo, "key", str(self._period.since.tzinfo)
            )
            content = redact_text(
                render_narrative(report, timezone=timezone, detail=self._detail)
            )
        else:
            content = redact_text(self._renderer.render(report, detail=self._detail))
        if not dry_run:
            self._progress.start(ProgressStage.WRITING_REPORT)
            atomic_secure_write(self._output_path, content, force=force)
        return ReportGenerationResult(
            report=report,
            content=content,
            output_path=self._output_path,
            scan=scan,
        )

    def generate_reviewed(
        self,
        review: OutcomeReviewDraft,
        *,
        scan: ScanResult | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> ReportGenerationResult:
        """Render a reviewed outcome draft without invoking repository summarization."""

        destination = self._output_path.expanduser()
        if not dry_run and not force and destination.exists():
            raise ReportAlreadyExistsError(f"report already exists: {destination}")
        if scan is None:
            scan = self._scan_service.scan()
        warnings = [*self._initial_warnings, *scan.warnings]
        reviewed = OutcomeReviewDraft.model_validate(
            redact_value(review.model_copy(deep=True).model_dump(mode="json"))
        )
        warnings.extend(reviewed.warnings)
        detail = DetailLevel(reviewed.detail)
        usage_text = self._collect_usage(scan, warnings) if detail is DetailLevel.FULL else None
        report = WorklogReport(
            generated_at=self._now_factory(),
            period=self._period,
            repositories=[],
            report_type=reviewed.report_type,
            outcomes=reviewed.ordered(),
            blockers=reviewed.blockers,
            next_week=reviewed.next_week,
            usage_text=usage_text,
            usage_days=self._usage_days if usage_text else None,
            warnings=[redact_text(warning) for warning in warnings],
        )
        self._progress.start(ProgressStage.RENDERING_REPORT)
        content = redact_text(self._renderer.render_outcomes(report, detail=detail))
        if not dry_run:
            self._progress.start(ProgressStage.WRITING_REPORT)
            atomic_secure_write(self._output_path, content, force=force)
        return ReportGenerationResult(
            report=report,
            content=content,
            output_path=self._output_path,
            scan=scan,
        )
