"""Adapters from the interactive controller to existing CLI service builders.

Imports of :mod:`agent_worklog.cli` stay inside callbacks so the Typer module can
import ``build_interactive_actions`` without creating an import cycle.
"""

from __future__ import annotations

import contextlib
from datetime import datetime

from agent_worklog.history import HistoryEntry, append_history
from agent_worklog.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
)
from agent_worklog.interactive.models import ReportDraft
from agent_worklog.logging import ConsoleReporter
from agent_worklog.models.time_range import DateRange
from agent_worklog.process import CommandRunner
from agent_worklog.security.redactor import redact_text
from agent_worklog.services.scan import ScanResult


def _new_draft() -> ReportDraft:
    from agent_worklog import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    enabled = cli._enabled_harnesses(settings)
    harness = cli.Harness.OPENCODE if cli.Harness.OPENCODE in enabled else enabled[0]
    label, period = _named_periods(now)[0]
    return ReportDraft(harness=harness.value, period=period, period_label=label)


def _choose_harness(current: str) -> str:
    """Cycle to the next enabled harness without leaving the key-driven UI."""

    from agent_worklog import cli

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

    from agent_worklog import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    periods = _named_periods(now)
    names = [name for name, _ in periods]
    if current_label not in names:
        return periods[0]
    return periods[(names.index(current_label) + 1) % len(periods)]


def _scan(draft: ReportDraft) -> ScanResult:
    from agent_worklog import cli

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
    from agent_worklog import cli

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
                    narrative=draft.narrative,
                    detail=draft.detail.value,
                )
            )
    return InteractiveReportResult(
        output_path=None if draft.dry_run else result.output_path,
        content=result.content,
        repository_count=len(scan.sessions_by_repository),
        session_count=scan.loaded_session_count,
    )


def _doctor(harness_name: str) -> list[str]:
    from agent_worklog import cli

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
    from agent_worklog import cli

    cli.config_init()


def _restore_selection(
    harness: str,
    period: DateRange,
    include_subagents: bool,
) -> set[str] | None:
    """Return the last Review selection for this key, or None when there is none."""

    from agent_worklog.state import load_selection, period_key

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

    from agent_worklog.state import period_key, save_selection

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

    from agent_worklog import cli, config_store

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
        "Undo with: agent-worklog config unset report.exclude_repositories"
    )


def build_interactive_actions() -> InteractiveActions:
    """Build the controller callbacks from the CLI's existing service seams."""

    return InteractiveActions(
        new_draft=_new_draft,
        choose_harness=_choose_harness,
        choose_period=_choose_period,
        scan=_scan,
        generate=_generate,
        doctor=_doctor,
        edit_settings=_edit_settings,
        restore_selection=_restore_selection,
        save_selection=_save_selection,
        exclude_repository=_exclude_repository,
    )
