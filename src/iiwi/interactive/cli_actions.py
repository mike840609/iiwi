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
from iiwi.history import HistoryEntry, append_history
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
)
from iiwi.interactive.models import ReportDraft
from iiwi.logging import ConsoleReporter
from iiwi.models.outcome import (
    Outcome,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.report_options import ReportType
from iiwi.models.time_range import DateRange
from iiwi.process import CommandRunner
from iiwi.security.redactor import redact_text
from iiwi.services.outcomes import OutcomeSynthesisService
from iiwi.services.scan import ScanResult
from iiwi.summarizers.opencode_run import OpenCodeRunner


def _new_draft() -> ReportDraft:
    from iiwi import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    enabled = cli._enabled_harnesses(settings)
    harness = cli.Harness.OPENCODE if cli.Harness.OPENCODE in enabled else enabled[0]
    label, period = _named_periods(now)[0]
    return ReportDraft(
        harness=harness.value,
        period=period,
        period_label=label,
        report_type=settings.report.quick_review_report_type,
    )


def _choose_harness(current: str) -> str:
    """Cycle to the next enabled harness without leaving the key-driven UI."""

    from iiwi import cli

    settings = cli._load_settings()
    enabled = [harness.value for harness in cli._enabled_harnesses(settings)]
    if not enabled:
        return current
    try:
        index = enabled.index(current)
    except ValueError:
        return enabled[0]
    return enabled[(index + 1) % len(enabled)]


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
                )
            )
    return InteractiveReportResult(
        output_path=None if draft.dry_run else result.output_path,
        content=result.content,
        repository_count=len(scan.sessions_by_repository),
        session_count=scan.loaded_session_count,
    )


def _synthesize(draft: ReportDraft, scan: ScanResult) -> OutcomeReviewDraft:
    """Synthesize the already-filtered review selection into an editable draft."""

    from iiwi import cli

    settings = cli._load_settings()
    cli_settings = settings.harnesses.opencode.cli
    runner = OpenCodeRunner(
        runner=CommandRunner(timeout_seconds=cli_settings.run_timeout_seconds),
        executable=cli_settings.executable,
        model=cli_settings.model,
    )
    result = OutcomeSynthesisService(runner).synthesize(scan)
    arguments: dict[str, object] = {
        "outcomes": result.outcomes,
        "report_type": draft.report_type,
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


def _edit_settings() -> None:
    from iiwi import cli

    cli.config_init()


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
        edit_settings=_edit_settings,
        restore_selection=_restore_selection,
        save_selection=_save_selection,
        exclude_repository=_exclude_repository,
    )
