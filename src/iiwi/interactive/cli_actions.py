"""Adapters from the interactive controller to existing CLI service builders.

Imports of :mod:`iiwi.cli` stay inside callbacks so the Typer module can
import ``build_interactive_actions`` without creating an import cycle.
"""

from __future__ import annotations

import contextlib
import os
from datetime import datetime
from uuid import uuid4

import typer

from iiwi import config_store
from iiwi.config import AppSettings
from iiwi.daily_state import load_daily_draft, save_daily_draft
from iiwi.errors import (
    DailySourceUnavailableError,
    IiwiError,
    OutcomeSynthesisError,
    ReportOutputError,
)
from iiwi.history import HistoryEntry, HistoryKind, append_history
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
)
from iiwi.interactive.models import ReportDraft
from iiwi.logging import ConsoleReporter
from iiwi.models.daily import DailySection, DailyStandupDraft
from iiwi.models.outcome import (
    Outcome,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.report_options import ReportType
from iiwi.models.time_range import DateRange
from iiwi.process import CommandRunner
from iiwi.progress import ProgressStage
from iiwi.security.redactor import redact_text
from iiwi.services.daily_reconcile import reconcile_daily_draft
from iiwi.services.daily_report import (
    DailyReportResult,
    DailyReportService,
    daily_output_path,
)
from iiwi.services.daily_scan import DailyScanCoordinator, DailyWindow
from iiwi.services.daily_workflow import DailyWorkflowService
from iiwi.services.outcomes import OutcomeSynthesisService
from iiwi.services.scan import ScanResult
from iiwi.summarizers.opencode_run import OpenCodeRunError, OpenCodeRunner

_ALL_DAILY_SOURCES_UNAVAILABLE_WARNING = (
    "All Daily Standup activity sources are unavailable."
)


def _new_draft() -> ReportDraft:
    from iiwi import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    harness = cli._default_harness(settings)
    label, period = _named_periods(now)[0]
    return ReportDraft(
        harness=harness.value,
        period=period,
        period_label=label,
        report_type=settings.report.quick_review_report_type,
    )


def _choose_harness(current: str) -> str:
    """Cycle to the next available harness without leaving the key-driven UI."""

    from iiwi import cli

    settings = cli._load_settings()
    available = [harness.value for harness in cli._available_harnesses(settings)]
    if not available:
        return current
    try:
        index = available.index(current)
    except ValueError:
        return available[0]
    return available[(index + 1) % len(available)]


def _named_periods(now: datetime) -> list[tuple[str, DateRange]]:
    """The periods `→` cycles, in order, each with the name shown on screen."""

    return [
        ("This week", DateRange.current_week(now=now)),
        ("Last week", DateRange.previous_week(now=now)),
        ("Last 7 days", DateRange.from_days(days=7, now=now)),
        ("Last 14 days", DateRange.from_days(days=14, now=now)),
        ("Last 30 days", DateRange.from_days(days=30, now=now)),
    ]


def _choose_period(current_label: str | None) -> tuple[str, DateRange]:
    """Advance to the next named period.

    Identified by name rather than by comparing timestamps. A rolling period's
    `until` is the moment it was built, so re-deriving the list a second later
    never matched the stored range: the cycle fell back to the first entry every
    other press, and the 14- and 30-day windows could not be reached at all.
    """

    from iiwi import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    periods = _named_periods(now)
    names = [name for name, _ in periods]
    if current_label not in names:
        return periods[0]
    return periods[(names.index(current_label) + 1) % len(periods)]


def _scan(draft: ReportDraft) -> ScanResult:
    from iiwi import cli

    settings = cli._load_settings()
    harness = cli.Harness(draft.harness)
    reporter = ConsoleReporter()
    with reporter.progress() as progress:
        service = cli._build_scan_service(
            settings,
            draft.period,
            not draft.include_subagents,
            harness=harness,
            sanitize=draft.sanitize,
            progress=progress,
        )
        return service.scan()


def _generate(
    draft: ReportDraft,
    scan: ScanResult,
    force: bool,
) -> InteractiveReportResult:
    from iiwi import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    harness = cli.Harness(draft.harness)
    output_path = cli._default_output_path(settings, draft.period)
    reporter = ConsoleReporter()
    with reporter.progress() as progress:
        service = cli._build_report_service(
            settings,
            draft.period,
            output_path,
            no_llm=not draft.narrative,
            root_only=not draft.include_subagents,
            now=now,
            harness=harness,
            sanitize=draft.sanitize,
            detail=draft.detail,
            progress=progress,
            initial_warnings=([draft.generation_notice] if draft.generation_notice else None),
        )
        result = service.generate(force=force, dry_run=draft.dry_run, scan=scan)
    if not draft.dry_run:
        # The TUI paints the next frame over the last, so a stray console line
        # from a failed log write would be painted over and never seen; the log
        # is bookkeeping, so the loss is accepted silently here.
        with contextlib.suppress(OSError):
            append_history(
                HistoryEntry(
                    generated_at=now,
                    harness=harness.value,
                    since=draft.period.since,
                    until=draft.period.until,
                    output_path=result.output_path,
                    repository_count=len(scan.sessions_by_repository),
                    session_count=scan.loaded_session_count,
                    narrative=bool(result.report.narrative_text),
                    detail=draft.detail.value,
                    kind=HistoryKind.REPORT,
                )
            )
    return InteractiveReportResult(
        output_path=None if draft.dry_run else result.output_path,
        content=result.content,
        repository_count=len(scan.sessions_by_repository),
        session_count=scan.loaded_session_count,
    )


def _synthesize(draft: ReportDraft, scan: ScanResult, force: bool) -> OutcomeReviewDraft:
    """Synthesize the already-filtered review selection into an editable draft.

    `force` sends the newest sessions that fit the evidence budget instead of
    refusing an over-budget selection; synthesis measures the budget itself.
    """

    from iiwi import cli

    settings = cli._load_settings()
    cli_settings = settings.harnesses.opencode.cli
    runner = OpenCodeRunner(
        runner=CommandRunner(timeout_seconds=cli_settings.run_timeout_seconds),
        executable=cli_settings.executable,
        model=cli_settings.model,
    )
    reporter = ConsoleReporter()
    try:
        # Synthesis extracts and redacts every selected session and then runs one
        # `opencode run` that can take minutes, and the TUI holds the last painted
        # frame until it returns; without this the app looks hung right after
        # "Exporting sessions".
        # ponytail: one animated status line, no percentage — the work is a single
        # subprocess, so there is nothing finer to report.
        with reporter.progress() as progress:
            progress.start(ProgressStage.SYNTHESIZING_OUTCOMES)
            result = OutcomeSynthesisService(
                runner,
                max_evidence_bytes=settings.report.quick_review_max_evidence_bytes,
            ).synthesize(scan, force=force)
    except (OpenCodeRunError, OSError) as exc:
        raise OutcomeSynthesisError(str(exc)) from exc
    arguments: dict[str, object] = {
        "outcomes": result.outcomes,
        "report_type": draft.report_type,
        "warnings": result.warnings,
    }
    if draft.detail_overridden:
        arguments["detail"] = draft.detail
    return OutcomeReviewDraft.model_validate(arguments)


def _generate_reviewed(
    draft: ReportDraft,
    scan: ScanResult,
    review: OutcomeReviewDraft,
    force: bool,
) -> InteractiveReportResult:
    """Render the exact in-memory review through the existing report builder."""

    from iiwi import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    harness = cli.Harness(draft.harness)
    output_path = cli._default_output_path(settings, draft.period)
    assert review.detail is not None
    reporter = ConsoleReporter()
    with reporter.progress() as progress:
        service = cli._build_report_service(
            settings,
            draft.period,
            output_path,
            no_llm=True,
            root_only=not draft.include_subagents,
            now=now,
            harness=harness,
            sanitize=draft.sanitize,
            detail=review.detail,
            progress=progress,
        )
        result = service.generate_reviewed(
            review,
            scan=scan,
            force=force,
            dry_run=draft.dry_run,
        )
    if not draft.dry_run:
        with contextlib.suppress(OSError):
            append_history(
                HistoryEntry(
                    generated_at=now,
                    harness=harness.value,
                    since=draft.period.since,
                    until=draft.period.until,
                    output_path=result.output_path,
                    repository_count=len(scan.sessions_by_repository),
                    session_count=scan.loaded_session_count,
                    narrative=False,
                    detail=review.detail.value,
                    kind=HistoryKind.REPORT,
                )
            )
    return InteractiveReportResult(
        output_path=None if draft.dry_run else result.output_path,
        content=result.content,
        repository_count=len(scan.sessions_by_repository),
        session_count=scan.loaded_session_count,
    )


def _prompt_status(current: OutcomeStatus) -> OutcomeStatus:
    choices = "/".join(status.value for status in OutcomeStatus)
    while True:
        answer = typer.prompt(
            f"Status ({choices})",
            default=current.value,
        )
        try:
            return OutcomeStatus(answer.strip().casefold())
        except ValueError:
            typer.echo(f"  choose one of: {choices}")


def _edit_outcome(outcome: Outcome) -> Outcome:
    """Prompt for editable prose while leaving traceability fields untouched."""

    title = typer.prompt("Title", default=outcome.title).strip()
    impact = typer.prompt("Impact", default=outcome.impact).strip()
    status = _prompt_status(outcome.status)
    return outcome.model_copy(
        update={"title": title, "impact": impact, "status": status},
        deep=True,
    )


def _add_outcome() -> Outcome | None:
    title = typer.prompt("Title", default="", show_default=False).strip()
    if not title:
        return None
    impact = typer.prompt("Impact", default="", show_default=False).strip()
    status = _prompt_status(OutcomeStatus.IN_PROGRESS)
    return Outcome(
        id=uuid4().hex,
        title=title,
        status=status,
        impact=impact,
        rank=0,
        origin=OutcomeOrigin.USER_ADDED,
    )


def _edit_gap(label: str, current: str | None) -> str | None:
    prompt = f"{label} [{current}]" if current else label
    answer = typer.prompt(
        prompt,
        default="",
        show_default=False,
    ).strip()
    if not answer or answer.casefold() == "none":
        return None
    return answer


def _save_report_type(report_type: ReportType) -> None:
    config_store.set_value(
        "report.quick_review_report_type",
        report_type.value,
    )


def _doctor(harness_name: str) -> list[str]:
    from iiwi import cli

    settings = cli._load_settings()
    harness = cli.Harness(harness_name)
    cli._require_enabled_harness(settings, harness)
    runner = CommandRunner(
        timeout_seconds=settings.harnesses.opencode.cli.timeout_seconds
    )
    result = cli.run_doctor(settings, runner=runner, harness=harness.value)
    return [
        f"{'OK' if check.ok else 'ERROR'} {check.name}: {check.detail}"
        for check in result.checks
    ]


def _restore_selection(
    harness: str,
    period: DateRange,
    include_subagents: bool,
) -> set[str] | None:
    """Return the last Review selection for this key, or None when there is none."""

    from iiwi.state import load_selection, period_key

    return load_selection(
        harness=harness,
        period_key=period_key(since=period.since, until=period.until),
        include_subagents=include_subagents,
    )


def _save_selection(
    harness: str,
    period: DateRange,
    include_subagents: bool,
    selected_session_ids: set[str],
) -> None:
    """Record the Review selection so a later scan of the same period restores it."""

    from iiwi.state import period_key, save_selection

    save_selection(
        harness=harness,
        period_key=period_key(since=period.since, until=period.until),
        include_subagents=include_subagents,
        selected_session_ids=selected_session_ids,
    )


def _exclude_repository(repository_id: str, display_name: str) -> str:
    """Add a repository to the persistent exclusion list, returning a message.

    Appending keeps any exclusions already configured. The value is written
    through `config set` so the settings file, the environment override, and
    `config list` stay the single source of truth.
    """

    from iiwi import cli, config_store

    if os.environ.get("IIWI_REPORT__EXCLUDE_REPOSITORIES") is not None:
        # The environment outranks the settings file, so an exclusion written
        # here would be ignored by every later run that exports the variable.
        return (
            "report.exclude_repositories is set in the environment; unset "
            "IIWI_REPORT__EXCLUDE_REPOSITORIES to persist exclusions."
        )
    settings = cli._load_settings()
    existing = settings.report.excluded_repository_ids()
    if repository_id in existing:
        return f"{redact_text(display_name)} is already excluded."
    entries = [*existing, repository_id]
    config_store.set_value(
        "report.exclude_repositories",
        ",".join(entries),
    )
    return (
        f"Excluded {redact_text(display_name)}; future scans will skip it. "
        "Undo with: iiwi config unset report.exclude_repositories"
    )


class _DailyOpenCodeRunner(OpenCodeRunner):
    """Translate the model runner's operational error into the workflow boundary."""

    def __init__(self, delegate: OpenCodeRunner) -> None:
        self._delegate = delegate

    def run(
        self,
        *,
        transcript: str,
        prompt: str,
        title: str,
    ) -> str:
        try:
            return self._delegate.run(
                transcript=transcript,
                prompt=prompt,
                title=title,
            )
        except (OpenCodeRunError, OSError) as exc:
            raise OutcomeSynthesisError(str(exc)) from exc


def _start_daily(previous: DailyStandupDraft | None) -> DailyStandupDraft:
    """Refresh Daily through the date-bound workflow service."""

    from iiwi import cli

    settings = cli._load_settings()
    cli_settings = settings.harnesses.opencode.cli
    runner = _DailyOpenCodeRunner(
        OpenCodeRunner(
            runner=CommandRunner(timeout_seconds=cli_settings.run_timeout_seconds),
            executable=cli_settings.executable,
            model=cli_settings.model,
        )
    )
    outcome_service = OutcomeSynthesisService(
        runner,
        max_evidence_bytes=settings.report.quick_review_max_evidence_bytes,
    )
    reporter = ConsoleReporter()
    with reporter.progress() as progress:

        def scan_coordinator(window: DailyWindow) -> DailyScanCoordinator:
            period = window.period
            scanners = {
                harness.value: cli._build_scan_service(
                    settings,
                    period,
                    False,
                    harness=harness,
                    sanitize=cli._effective_sanitize(settings, harness, None),
                    progress=progress,
                )
                for harness in cli._available_harnesses(settings)
            }
            return DailyScanCoordinator(window=window, scanners=scanners)

        workflow = DailyWorkflowService(
            scan_coordinator_factory=scan_coordinator,
            outcome_service=outcome_service,
            now_factory=lambda: cli._now_in_timezone(settings.report.timezone),
        )
        return workflow.refresh(previous)


def _continue_daily_empty(
    error: DailySourceUnavailableError,
    previous: DailyStandupDraft | None,
) -> DailyStandupDraft:
    """Continue review with no fresh activity while preserving the failed window."""

    state_warning: str | None = None
    if previous is None or previous.standup_date != error.standup_date:
        loaded = load_daily_draft(error.standup_date)
        previous = loaded.draft
        state_warning = loaded.warning
    empty_fresh = DailyStandupDraft(
        standup_date=error.standup_date,
        scan_since=error.since,
        scan_until=error.until,
        successful_harnesses=[],
        unavailable_harnesses=list(error.unavailable_harnesses),
        coverage_warnings=[_ALL_DAILY_SOURCES_UNAVAILABLE_WARNING],
        # reconcile keeps every scalar from the fresh draft, so leaving these at
        # zero would report "0 sess 0 repos" for a standup that still carries
        # the reviewed items this path exists to preserve. No source answered,
        # so the reviewed counts are the only coverage there is to state.
        repository_count=previous.repository_count if previous is not None else 0,
        session_count=previous.session_count if previous is not None else 0,
    )
    if state_warning is not None:
        empty_fresh.warnings.append(state_warning)
    return reconcile_daily_draft(previous, empty_fresh)


def _persist_daily(draft: DailyStandupDraft) -> str | None:
    """Save review state, returning a visible TUI warning on bookkeeping failure."""

    try:
        save_daily_draft(draft)
    except (OSError, IiwiError):
        return "Could not save Daily Standup review state."
    return None


def _daily_report_result(result: DailyReportResult) -> InteractiveReportResult:
    return InteractiveReportResult(
        output_path=result.output_path,
        content=result.content,
        repository_count=result.repository_count,
        session_count=result.session_count,
    )


def _current_standup_clock(draft: DailyStandupDraft) -> tuple[AppSettings, datetime]:
    """Return settings and the local clock, refusing a review the date has passed.

    Preview and Generate share this read so they cannot disagree:
    docs/daily-standup.md promises Preview renders exactly what Generate writes,
    and a review left open across local midnight would otherwise preview a
    complete artifact dated yesterday that Generate then refuses to write.
    """

    from iiwi import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    if now.date() != draft.standup_date:
        raise ReportOutputError(
            f"Daily Standup review is for {draft.standup_date:%Y-%m-%d}, but the "
            f"current local date is {now.date():%Y-%m-%d}. Refresh Daily Standup "
            "to continue."
        )
    return settings, now


def _preview_daily(draft: DailyStandupDraft) -> InteractiveReportResult:
    """Render the existing Daily review without refreshing or writing it."""

    _current_standup_clock(draft)
    return _daily_report_result(DailyReportService().preview(draft))


def _generate_daily(draft: DailyStandupDraft) -> InteractiveReportResult:
    """Write the reviewed Daily artifact, then its state and history bookkeeping."""

    settings, now = _current_standup_clock(draft)
    output_path = daily_output_path(
        settings.report.output_directory,
        draft.standup_date,
    )
    result = DailyReportService().generate(draft, output_path=output_path)

    with contextlib.suppress(OSError, IiwiError):
        save_daily_draft(draft)

    with contextlib.suppress(OSError):
        append_history(
            HistoryEntry(
                generated_at=now,
                since=draft.scan_since,
                until=draft.scan_until,
                output_path=output_path,
                repository_count=draft.repository_count,
                session_count=draft.session_count,
                kind=HistoryKind.DAILY_STANDUP,
                harnesses=tuple(draft.successful_harnesses),
                unavailable_harnesses=tuple(draft.unavailable_harnesses),
            )
        )
    return _daily_report_result(result)


def _edit_daily_statement(statement: str) -> str | None:
    edited = typer.prompt("Statement", default=statement).strip()
    return edited or None


def _add_daily_statement(section: DailySection) -> str | None:
    statement = typer.prompt(
        f"Add to {section.value}",
        default="",
        show_default=False,
    ).strip()
    return statement or None


def build_interactive_actions() -> InteractiveActions:
    """Build the controller callbacks from the CLI's existing service seams."""

    return InteractiveActions(
        new_draft=_new_draft,
        choose_harness=_choose_harness,
        choose_period=_choose_period,
        scan=_scan,
        generate=_generate,
        synthesize=_synthesize,
        generate_reviewed=_generate_reviewed,
        edit_outcome=_edit_outcome,
        add_outcome=_add_outcome,
        edit_gap=_edit_gap,
        save_report_type=_save_report_type,
        doctor=_doctor,
        restore_selection=_restore_selection,
        save_selection=_save_selection,
        exclude_repository=_exclude_repository,
        start_daily=_start_daily,
        continue_daily_empty=_continue_daily_empty,
        persist_daily=_persist_daily,
        preview_daily=_preview_daily,
        generate_daily=_generate_daily,
        edit_daily_statement=_edit_daily_statement,
        add_daily_statement=_add_daily_statement,
    )
