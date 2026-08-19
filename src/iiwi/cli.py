"""Command-line interface for Iiwi."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

from iiwi import __version__, config_store
from iiwi.config import DEFAULT_NARRATOR_TIMEOUT_SECONDS, AppSettings
from iiwi.errors import (
    ConfigurationError,
    HarnessSourceError,
    NoSessionsError,
    ReportOutputError,
)
from iiwi.harnesses.base import HarnessSessionSource
from iiwi.harnesses.claude_code.source import ClaudeCodeFileSource
from iiwi.harnesses.claude_code.source import is_available as claude_code_is_available
from iiwi.harnesses.codex.source import CodexSource
from iiwi.harnesses.codex.source import is_available as codex_is_available
from iiwi.harnesses.opencode.source import OpenCodeCliSource
from iiwi.harnesses.opencode.source import is_available as opencode_is_available
from iiwi.harnesses.opencode.stats import collect_usage_stats, usage_days
from iiwi.history import (
    HistoryEntry,
    HistoryKind,
    append_history,
    history_to_json,
    read_history,
)
from iiwi.interactive.cli_actions import build_interactive_actions
from iiwi.interactive.controller import run_interactive
from iiwi.interactive.input import TerminalInput
from iiwi.interactive.models import Screen
from iiwi.json_output import doctor_result_to_json, scan_result_to_json
from iiwi.logging import ConsoleReporter
from iiwi.models.time_range import DateRange
from iiwi.process import CommandRunner
from iiwi.progress import ProgressReporter
from iiwi.renderers.markdown import DetailLevel, MarkdownRenderer
from iiwi.renderers.usage import render_activity_usage
from iiwi.repositories.resolver import RepositoryResolver
from iiwi.security.redactor import redact_text
from iiwi.services.doctor import NarratorDescription, run_doctor
from iiwi.services.report import ReportService
from iiwi.services.scan import ScanResult, ScanService
from iiwi.summarizers.narrator import NarrativeRunError, NarrativeRunner
from iiwi.summarizers.narrators.claude import ClaudeNarrator
from iiwi.summarizers.narrators.codex import CodexNarrator
from iiwi.summarizers.opencode_run import OpenCodeRunner
from iiwi.summarizers.rule_based import RuleBasedSummarizer
from iiwi.update import (
    UpdateCheckError,
    check_for_update,
    update_error_to_json,
    update_to_json,
)


class Harness(StrEnum):
    OPENCODE = "opencode"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


# A module-level singleton, per ruff B008: an Enum-typed `typer.Option(...)` call
# isn't recognized as an immutable default, so it must be constructed once here
# and shared, rather than called inline in each command's signature.
_HARNESS_OPTION = typer.Option(
    None,
    "--harness",
    help="Coding-agent harness to read sessions from; defaults to the first available harness.",
)

_DETAIL_OPTION = typer.Option(
    DetailLevel.FULL,
    "--detail",
    help="How much detail the report contains: full (default) or brief.",
)

_RUN_DETAIL_OPTION = typer.Option(
    None,
    "--detail",
    help="How much detail the report contains: full or brief; prompts when omitted.",
)

app = typer.Typer(
    help="Turn coding-agent sessions into repository-based engineering reports.",
)


_DEPRECATED_KEYS = {
    "harnesses.opencode.cli.model": "narrator.model",
    "harnesses.opencode.cli.run_timeout_seconds": "narrator.timeout_seconds",
}

# Module-level, not per-call: the interactive layer calls _load_settings on
# nearly every keypress (_choose_harness alone reloads it once per harness
# cycle), so without a process-wide guard a user with one deprecated key set
# gets this notice painted over the TUI on almost every action instead of
# exactly once.
_deprecation_notice_emitted = False


def _warn_about_deprecated_keys(settings: AppSettings) -> None:
    """Say which key replaced a deprecated one, once per process, on stderr.

    Not through the report's warnings: a configuration migration printed inside
    the report body would outlive the migration in every file it was written to.
    """

    global _deprecation_notice_emitted
    if _deprecation_notice_emitted:
        return
    cli_settings = settings.harnesses.opencode.cli
    in_use = []
    if cli_settings.model:
        in_use.append("harnesses.opencode.cli.model")
    if "run_timeout_seconds" in cli_settings.model_fields_set:
        in_use.append("harnesses.opencode.cli.run_timeout_seconds")
    if not in_use:
        return
    for key in in_use:
        typer.echo(
            f"Note: {key} is deprecated; use {_DEPRECATED_KEYS[key]}.",
            err=True,
        )
    _deprecation_notice_emitted = True


def _load_settings() -> AppSettings:
    """Load settings, layering the settings file below the environment.

    pydantic-settings gives environment variables precedence over `_env_file`,
    which is the order `config set` promises: the file holds defaults, an
    exported variable overrides them for one shell.
    """

    path = config_store.config_file_path()
    try:
        settings = AppSettings(_env_file=path)  # type: ignore[call-arg]
    except Exception as exc:  # Pydantic aggregates configuration failures.
        # Name the file when there is one: a parse error otherwise says what is
        # wrong without saying where the value came from.
        hint = f"; settings come from the environment and {path}" if path.exists() else ""
        # Pydantic's validation errors echo the offending input verbatim (e.g.
        # `input_value='sk-proj-...'`), so a bad value in a setting the model
        # DOES own — a base URL with an embedded password, an API key typed
        # into the wrong field — must not reach stdout unredacted.
        raise ConfigurationError(redact_text(f"{exc}{hint}")) from exc
    _warn_about_deprecated_keys(settings)
    return settings


def _now_in_timezone(timezone: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(f"unknown timezone: {timezone}") from exc


def _parse_iso_datetime(value: str, *, timezone: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter(f"invalid ISO datetime: {value}") from exc
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"unknown timezone: {timezone}") from exc
    return parsed


def _resolve_period(
    *,
    days: int | None,
    period: str | None,
    since: str | None,
    until: str | None,
    timezone: str,
    now: datetime,
) -> DateRange:
    """Resolve the requested period against a single clock read for the command."""

    selectors = sum(value is not None for value in (days, period, since))
    if selectors != 1:
        raise typer.BadParameter("provide exactly one of --days, --period, or --since")
    if until is not None and since is None:
        raise typer.BadParameter("--until requires --since")
    if days is not None:
        if days < 1:
            raise typer.BadParameter("--days must be at least 1")
        return DateRange.from_days(days=days, now=now)
    if period is not None:
        if period != "last-week":
            raise typer.BadParameter("--period accepts only 'last-week'")
        return DateRange.previous_week(now=now)
    assert since is not None
    start = _parse_iso_datetime(since, timezone=timezone)
    end = _parse_iso_datetime(until, timezone=timezone) if until else now
    if start >= end:
        raise typer.BadParameter("--since must be earlier than --until")
    return DateRange(since=start, until=end)


def _default_output_path(settings: AppSettings, period: DateRange) -> Path:
    filename = f"worklog-{period.since:%Y-%m-%d}_{period.until:%Y-%m-%d}.md"
    return settings.report.output_directory / filename


def _require_enabled_harness(settings: AppSettings, harness: Harness) -> None:
    """Refuse a harness its configuration has turned off.

    A privacy tool must not advertise an off switch that does nothing: reading
    `~/.claude/projects` or `~/.codex` is exactly the kind of thing an operator
    may need to forbid for a whole machine.

    Each enum member's name is the settings field name, so a new harness needs
    no edit here.
    """

    if not getattr(settings.harnesses, harness.name.lower()).enabled:
        variable = f"IIWI_HARNESSES__{harness.name}__ENABLED"
        raise ConfigurationError(
            f"harness {harness.value} is disabled by configuration; "
            f"set {variable}=true to use it"
        )


def _validate_privacy_options(
    *,
    harness: Harness,
    sanitize: bool | None,
) -> None:
    if sanitize is not None and harness is not Harness.OPENCODE:
        raise typer.BadParameter(
            "--sanitize and --no-sanitize are supported only with --harness opencode"
        )


def _effective_sanitize(
    settings: AppSettings,
    harness: Harness,
    override: bool | None,
) -> bool:
    if harness is not Harness.OPENCODE:
        return False
    if override is not None:
        return override
    return settings.harnesses.opencode.cli.sanitize


def _build_scan_service(
    settings: AppSettings,
    period: DateRange,
    root_only: bool = False,
    *,
    harness: Harness = Harness.OPENCODE,
    sanitize: bool = False,
    progress: ProgressReporter | None = None,
) -> ScanService:
    _require_enabled_harness(settings, harness)
    git_runner = CommandRunner(timeout_seconds=5.0)
    source: HarnessSessionSource
    if harness is Harness.CLAUDE_CODE:
        source = ClaudeCodeFileSource(
            projects_directory=settings.harnesses.claude_code.projects_directory,
            root_only=root_only,
        )
    elif harness is Harness.CODEX:
        source = CodexSource(
            home_directory=settings.harnesses.codex.home_directory,
            root_only=root_only,
        )
    else:
        cli_settings = settings.harnesses.opencode.cli
        source = OpenCodeCliSource(
            runner=CommandRunner(timeout_seconds=cli_settings.timeout_seconds),
            executable=cli_settings.executable,
            root_only=root_only,
            sanitize=sanitize,
        )
    return ScanService(
        source=source,
        period=period,
        resolver=RepositoryResolver(runner=git_runner),
        progress=progress,
        excluded_repository_ids=frozenset(settings.report.excluded_repository_ids()),
        runner=git_runner,
    )


def _usage_provider(
    settings: AppSettings,
    period: DateRange,
    harness: Harness,
    now: datetime,
) -> tuple[Callable[[ScanResult], str], int | None]:
    """Return the harness usage provider and the window it covers, if narrower."""

    if harness in {Harness.CLAUDE_CODE, Harness.CODEX}:
        # Usage rides on the already-filtered activities, so the window is exact
        # and needs no "wider than the period" caveat.
        return partial(render_activity_usage, harness=harness.value), None

    cli_settings = settings.harnesses.opencode.cli
    stats_runner = CommandRunner(timeout_seconds=cli_settings.timeout_seconds)
    days = usage_days(period, now)

    def collect(_scan: ScanResult) -> str:
        return collect_usage_stats(
            runner=stats_runner,
            executable=cli_settings.executable,
            days=days,
        )

    return collect, days


_PROVIDER_BY_HARNESS = {
    Harness.OPENCODE: "opencode",
    Harness.CLAUDE_CODE: "claude",
    Harness.CODEX: "codex",
}
_PROVIDERS = frozenset(_PROVIDER_BY_HARNESS.values())


def _validate_configured_provider(provider: str) -> str:
    """Validate a `narrator.provider` value the user configured, harness-free.

    Kept separate from `_resolve_provider` so validating a configured string
    never needs a harness to stand in for: `_build_daily_narrator` has no
    single harness to offer (it scans every enabled one), and passing it a
    placeholder just to reuse this check would be a bug wearing a parameter.
    """

    if provider not in _PROVIDERS:
        allowed = ", ".join(sorted(_PROVIDERS))
        raise ConfigurationError(f"unknown narrator.provider: {provider}; choose from {allowed}")
    return provider


def _resolve_provider(settings: AppSettings, harness: Harness) -> str:
    """Which CLI writes the prose. Configuration always beats the harness."""

    configured = settings.narrator.provider.strip()
    if not configured:
        return _PROVIDER_BY_HARNESS[harness]
    return _validate_configured_provider(configured)


def _resolve_executable(settings: AppSettings, provider: str) -> str:
    # The OpenCode fallback below applies only to the OpenCode provider: a
    # model name left over from an OpenCode setup would be rejected by
    # `claude --model` or `codex -m` if it leaked into another provider.
    configured = settings.narrator.executable.strip()
    if configured:
        return configured
    if provider == "opencode":
        return settings.harnesses.opencode.cli.executable
    return provider


def _describe_narrator(settings: AppSettings, harness: Harness) -> NarratorDescription:
    """Name the resolved narrator for `doctor`, and where that choice came from.

    Sharing `_resolve_provider`/`_resolve_executable` with the narration path
    is what makes "scan Codex, narrate with Claude" visible: doctor reports
    exactly what a report run would pick.
    """

    provider = _resolve_provider(settings, harness)
    configured = settings.narrator.provider.strip()
    source = "narrator.provider" if configured else f"--harness {harness.value}"
    return NarratorDescription(
        provider=provider,
        executable=_resolve_executable(settings, provider),
        source=source,
    )


def _resolve_model(settings: AppSettings, provider: str) -> str:
    if settings.narrator.model:
        return settings.narrator.model
    if provider == "opencode":
        return settings.harnesses.opencode.cli.model
    return ""


def _resolve_timeout(settings: AppSettings, provider: str) -> float:
    if settings.narrator.timeout_seconds is not None:
        return settings.narrator.timeout_seconds
    if provider == "opencode":
        return settings.harnesses.opencode.cli.run_timeout_seconds
    return DEFAULT_NARRATOR_TIMEOUT_SECONDS


def _narrator_for_provider(settings: AppSettings, provider: str) -> NarrativeRunner:
    executable = _resolve_executable(settings, provider)
    model = _resolve_model(settings, provider)
    runner = CommandRunner(timeout_seconds=_resolve_timeout(settings, provider))
    executable_configured = bool(settings.narrator.executable.strip())
    if provider == "claude":
        return ClaudeNarrator(
            runner=runner,
            executable=executable,
            model=model,
            executable_configured=executable_configured,
        )
    if provider == "codex":
        return CodexNarrator(
            runner=runner,
            executable=executable,
            model=model,
            codex_home=settings.harnesses.codex.home_directory,
            executable_configured=executable_configured,
        )
    return OpenCodeRunner(
        runner=runner,
        executable=executable,
        model=model,
        executable_configured=executable_configured,
    )


def _build_narrator(settings: AppSettings, harness: Harness) -> NarrativeRunner:
    return _narrator_for_provider(settings, _resolve_provider(settings, harness))


def _build_daily_narrator(settings: AppSettings) -> NarrativeRunner:
    """Daily scans every harness, so no single one names the provider.

    Configuration wins; otherwise take an installed provider, preferring
    OpenCode so an existing setup keeps the CLI it already used.
    """

    configured = settings.narrator.provider.strip()
    if configured:
        return _narrator_for_provider(settings, _validate_configured_provider(configured))
    if settings.narrator.executable.strip():
        # _resolve_executable applies a configured narrator.executable to
        # every provider alike, but this path probes every enabled harness's
        # provider to pick one: without narrator.provider too, the same
        # executable would appear installed for all three, "win" as whichever
        # provider is checked first, and then run with that provider's flags
        # against a binary that is not necessarily built for them (C1). A
        # single already-resolved harness (report/scan/doctor) has no such
        # ambiguity, so only this multi-harness path refuses it.
        raise NarrativeRunError(
            "narrator.executable is set without narrator.provider; Daily "
            "resolves the provider from whichever harness is installed, so "
            "it cannot tell which CLI that executable belongs to. Set "
            "narrator.provider as well."
        )
    candidates = [
        _PROVIDER_BY_HARNESS[harness]
        for harness in _enabled_harnesses(settings)
        if shutil.which(_resolve_executable(settings, _PROVIDER_BY_HARNESS[harness]))
    ]
    if "opencode" in candidates:
        return _narrator_for_provider(settings, "opencode")
    if candidates:
        return _narrator_for_provider(settings, candidates[0])
    looked_for = ", ".join(
        _resolve_executable(settings, _PROVIDER_BY_HARNESS[harness])
        for harness in _enabled_harnesses(settings)
    )
    raise NarrativeRunError(
        f"no narration provider is installed; looked for {looked_for}. "
        "Set narrator.provider or narrator.executable."
    )


def _build_report_service(
    settings: AppSettings,
    period: DateRange,
    output_path: Path,
    no_llm: bool,
    root_only: bool = False,
    *,
    now: datetime,
    harness: Harness = Harness.OPENCODE,
    sanitize: bool = False,
    detail: DetailLevel = DetailLevel.FULL,
    progress: ProgressReporter | None = None,
    initial_warnings: list[str] | None = None,
) -> ReportService:
    """Build the report service around the command's single clock read."""

    # Only the narrative path reads narrator settings, so `--no-llm` — the
    # documented way to run without an AI CLI — must not fail on a provider it
    # never invokes.
    narrator = None if no_llm else _build_narrator(settings, harness)
    summarizer = RuleBasedSummarizer()

    usage_provider, days = _usage_provider(settings, period, harness, now)
    scan_service = _build_scan_service(
        settings,
        period,
        root_only,
        harness=harness,
        sanitize=sanitize,
        progress=progress,
    )

    return ReportService(
        scan_service=scan_service,
        summarizer=summarizer,
        renderer=MarkdownRenderer(),
        period=period,
        output_path=output_path,
        now_factory=lambda: now,
        usage_provider=usage_provider,
        usage_days=days,
        detail=detail,
        progress=progress,
        narrative=not no_llm,
        narrator=narrator,
        include_subagents=not root_only,
        sanitized=sanitize,
        initial_warnings=initial_warnings,
    )


def _no_sessions_message(
    harness: Harness,
    *,
    excluded: bool,
    failed: bool = False,
) -> str:
    """The empty-scan error, naming exclusion when the configuration caused it.

    A scan must never be a mystery: "none found" is the honest description
    only when exclusion removed everything. Sessions that failed to load are
    a different cause carrying their own scan warnings, so an exclusion
    message would blame the configuration for someone else's corrupt export.
    """

    if excluded and not failed:
        return (
            f"all {harness.value} sessions in the requested period "
            "were excluded by configuration"
        )
    return f"no {harness.value} activity found in the requested period"


def _handle_expected_error(exc: Exception, *, code: int) -> None:
    typer.echo(f"Error: {exc}")
    raise typer.Exit(code=code)


def _validate_output_mode(*, quiet: bool, verbose: bool) -> None:
    if quiet and verbose:
        raise typer.BadParameter("--quiet and --verbose cannot be used together")


def _stdout_is_a_terminal() -> bool:
    """Whether stdout goes to a person rather than a pipe or file."""
    return sys.stdout.isatty()


def _json_mode(json_flag: bool | None, *, quiet: bool) -> bool:
    """Resolve `--json` against the pipe default, with `--quiet` kept explicit.

    Piped stdout is where scripts live, so JSON is the default there — the way
    `mo status | jq` just works. `--quiet` keeps its documented contract (the
    session count, or the output path) and opts out of the auto-switch.
    """

    if json_flag is not None:
        return json_flag
    return not quiet and not _stdout_is_a_terminal()


def _validate_json_mode(*, json: bool | None, quiet: bool) -> None:
    if json is True and quiet:
        raise typer.BadParameter("--json and --quiet cannot be used together")


def _record_history(
    *,
    harness: Harness,
    period: DateRange,
    output_path: Path,
    repository_count: int,
    session_count: int,
    narrative: bool,
    detail: DetailLevel,
    now: datetime,
    reporter: ConsoleReporter,
) -> None:
    """Record one written report; a history failure must not fail the report.

    The log is bookkeeping, not the deliverable: losing an entry must never
    turn a successfully written report into an error exit.
    """

    try:
        append_history(
            HistoryEntry(
                generated_at=now,
                harness=harness.value,
                since=period.since,
                until=period.until,
                output_path=output_path,
                repository_count=repository_count,
                session_count=session_count,
                narrative=narrative,
                detail=detail.value,
                kind=HistoryKind.REPORT,
            )
        )
    except OSError as exc:
        reporter.message(f"Warning: could not record report history: {exc}")


@app.command()
def doctor(
    harness: Harness | None = _HARNESS_OPTION,
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
    json: bool | None = typer.Option(
        None,
        "--json/--no-json",
        help=(
            "Emit machine-readable JSON. When stdout is piped, JSON is the "
            "default; --no-json forces the human output."
        ),
    ),
) -> None:
    """Validate the selected harness and Git dependencies."""

    _validate_output_mode(quiet=quiet, verbose=verbose)
    _validate_json_mode(json=json, quiet=quiet)
    reporter = ConsoleReporter(quiet=quiet, verbose=verbose)
    try:
        settings = _load_settings()
        # doctor exists to diagnose an unusable setup, so it falls back instead
        # of raising here; see _doctor_default_harness.
        harness = harness or _doctor_default_harness(settings)
        _require_enabled_harness(settings, harness)
        runner = CommandRunner(
            timeout_seconds=settings.harnesses.opencode.cli.timeout_seconds
        )
        narrator = _describe_narrator(settings, harness)
        result = run_doctor(
            settings, runner=runner, harness=harness.value, narrator=narrator
        )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    if _json_mode(json, quiet=quiet):
        typer.echo(doctor_result_to_json(result, harness.value))
    else:
        for check in result.checks:
            reporter.doctor_check(check.name, check.ok, check.detail)
    if not result.ok:
        raise typer.Exit(code=5)


@app.command()
def scan(
    days: int | None = typer.Option(None, "--days"),
    period: str | None = typer.Option(None, "--period"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    root_only: bool = typer.Option(
        False,
        "--root-only",
        help="Exclude child/subagent sessions.",
    ),
    sanitize: bool | None = typer.Option(
        None,
        "--sanitize/--no-sanitize",
        help=(
            "Ask OpenCode to redact exported session content. "
            "Disabled by default. OpenCode only."
        ),
    ),
    harness: Harness | None = _HARNESS_OPTION,
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
    json: bool | None = typer.Option(
        None,
        "--json/--no-json",
        help=(
            "Emit machine-readable JSON. When stdout is piped, JSON is the "
            "default; --no-json forces the human output."
        ),
    ),
) -> None:
    """Find coding-agent sessions and group them by Git repository."""

    _validate_output_mode(quiet=quiet, verbose=verbose)
    _validate_json_mode(json=json, quiet=quiet)
    reporter = ConsoleReporter(quiet=quiet, verbose=verbose)
    try:
        settings = _load_settings()
        harness = harness or _default_harness(settings)
        _validate_privacy_options(harness=harness, sanitize=sanitize)
        effective_sanitize = _effective_sanitize(settings, harness, sanitize)
        now = _now_in_timezone(settings.report.timezone)
        selected_period = _resolve_period(
            days=days,
            period=period,
            since=since,
            until=until,
            timezone=settings.report.timezone,
            now=now,
        )
        with reporter.progress() as progress:
            if effective_sanitize:
                service = _build_scan_service(
                    settings,
                    selected_period,
                    root_only,
                    harness=harness,
                    sanitize=True,
                    progress=progress,
                )
            else:
                service = _build_scan_service(
                    settings,
                    selected_period,
                    root_only,
                    harness=harness,
                    progress=progress,
                )
            result = service.scan()
            if result.loaded_session_count == 0:
                raise NoSessionsError(
                    _no_sessions_message(
                        harness,
                        excluded=result.excluded_session_count > 0,
                        failed=result.failed_session_count > 0,
                    )
                )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    except NoSessionsError as exc:
        _handle_expected_error(exc, code=4)
        return
    except HarnessSourceError as exc:
        _handle_expected_error(exc, code=5)
        return
    if _json_mode(json, quiet=quiet):
        typer.echo(scan_result_to_json(result))
    else:
        reporter.scan_result(result)


@app.command()
def report(
    days: int | None = typer.Option(None, "--days"),
    period: str | None = typer.Option(None, "--period"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    root_only: bool = typer.Option(
        False,
        "--root-only",
        help="Exclude child/subagent sessions.",
    ),
    output: Annotated[Path | None, typer.Option("--output")] = None,
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help=(
            "Skip the narrative report; emit the structured report without "
            "calling a narration CLI."
        ),
    ),
    sanitize: bool | None = typer.Option(
        None,
        "--sanitize/--no-sanitize",
        help=(
            "Ask OpenCode to redact exported session content. "
            "Disabled by default. OpenCode only."
        ),
    ),
    force: bool = typer.Option(False, "--force"),
    harness: Harness | None = _HARNESS_OPTION,
    detail: DetailLevel = _DETAIL_OPTION,
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Generate a Markdown engineering worklog."""

    _validate_output_mode(quiet=quiet, verbose=verbose)
    reporter = ConsoleReporter(quiet=quiet, verbose=verbose)
    try:
        settings = _load_settings()
        harness = harness or _default_harness(settings)
        _validate_privacy_options(harness=harness, sanitize=sanitize)
        effective_sanitize = _effective_sanitize(settings, harness, sanitize)
        now = _now_in_timezone(settings.report.timezone)
        selected_period = _resolve_period(
            days=days,
            period=period,
            since=since,
            until=until,
            timezone=settings.report.timezone,
            now=now,
        )
        output_path = output or _default_output_path(settings, selected_period)
        with reporter.progress() as progress:
            service = _build_report_service(
                settings,
                selected_period,
                output_path,
                no_llm,
                root_only,
                now=now,
                harness=harness,
                sanitize=effective_sanitize,
                detail=detail,
                progress=progress,
            )
            result = service.generate(force=force, dry_run=dry_run)
            if not result.report.repositories and not result.report.narrative_text:
                raise NoSessionsError(
                    _no_sessions_message(
                        harness,
                        excluded=result.scan.excluded_session_count > 0,
                        failed=result.scan.failed_session_count > 0,
                    )
                )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    except NoSessionsError as exc:
        _handle_expected_error(exc, code=4)
        return
    except HarnessSourceError as exc:
        _handle_expected_error(exc, code=5)
        return
    except ReportOutputError as exc:
        _handle_expected_error(exc, code=7)
        return

    if not dry_run:
        _record_history(
            harness=harness,
            period=selected_period,
            output_path=result.output_path,
            repository_count=len(result.report.repositories),
            session_count=result.scan.loaded_session_count,
            narrative=bool(result.report.narrative_text),
            detail=detail,
            now=now,
            reporter=reporter,
        )

    if dry_run:
        typer.echo(result.content, nl=False)
    elif quiet:
        reporter.output_path(result.output_path)
    else:
        reporter.message(f"Report written to {result.output_path}")
        if verbose:
            for warning in result.report.warnings:
                reporter.message(f"Warning: {warning}")


@app.command()
def history(
    json: bool | None = typer.Option(
        None,
        "--json/--no-json",
        help=(
            "Emit machine-readable JSON. When stdout is piped, JSON is the "
            "default; --no-json forces the human output."
        ),
    ),
) -> None:
    """List the reports this tool has written."""

    reporter = ConsoleReporter()
    entries = read_history()
    if not entries:
        if _json_mode(json, quiet=False):
            typer.echo("[]")
        else:
            reporter.message("No reports generated yet.")
        return
    if _json_mode(json, quiet=False):
        typer.echo(history_to_json(entries))
    else:
        reporter.history_table(entries)


@app.command()
def update(
    json: bool | None = typer.Option(
        None,
        "--json/--no-json",
        help=(
            "Emit machine-readable JSON. When stdout is piped, JSON is the "
            "default; --no-json forces the human output."
        ),
    ),
) -> None:
    """Check PyPI for a newer release.

    This is the only command that touches the network, and it only does so when
    run: nothing leaves the machine otherwise. An unreachable index is not an
    error — offline machines are legitimate — but an available update exits
    with code 8 so scripts can tell the two apart.
    """

    reporter = ConsoleReporter()
    try:
        info = check_for_update()
    except UpdateCheckError as exc:
        if _json_mode(json, quiet=False):
            typer.echo(update_error_to_json(str(exc)))
        else:
            reporter.message(f"Could not check for updates: {exc}")
        return
    if _json_mode(json, quiet=False):
        typer.echo(update_to_json(info))
        if info.update_available:
            raise typer.Exit(code=8)
        return
    if info.update_available:
        reporter.message(
            f"Version {info.latest} is available (you have {info.current}).\n"
            f"Upgrade with: {info.upgrade_command}"
        )
        raise typer.Exit(code=8)
    reporter.message(f"You are up to date ({info.current}).")


config_app = typer.Typer(
    no_args_is_help=True,
    help="Show and edit the settings file.",
)
app.add_typer(config_app, name="config")


@config_app.command("path")
def config_path() -> None:
    """Print the settings file location."""

    typer.echo(str(config_store.config_file_path()))


@config_app.command("list")
def config_list() -> None:
    """Show every setting, the value in force, and where it comes from."""

    path = config_store.config_file_path()
    try:
        rows = config_store.describe_settings(path)
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    ConsoleReporter().settings_table(rows, path=path)


def _default_restored(setting: config_store.SettingKey, removed: bool) -> str:
    if removed:
        return f"Removed {setting.key}; using default: {setting.default}"
    return f"{setting.key} was not set; already using default: {setting.default}"


def _warn_if_shadowed(
    reporter: ConsoleReporter, setting: config_store.SettingKey
) -> None:
    """Say so when an exported variable overrides what was just written.

    The environment wins over the file, so without this the command reports
    success on a change the next run will ignore.
    """

    if os.environ.get(setting.variable) is not None:
        reporter.message(
            f"Note: {setting.variable} is set in the environment "
            "and takes precedence."
        )


def _stdin_is_a_terminal() -> bool:
    """Whether anyone is on the other end to answer a prompt."""

    return sys.stdin.isatty()


def _supports_key_navigation() -> bool:
    """Whether the real stdin can supply one-key terminal navigation.

    Tests can force the prompt guard while still using CliRunner's pipe. Keeping
    this capability check separate lets those legacy prompt tests exercise their
    fallback without changing what a real TTY sees.
    """

    return sys.stdin.isatty()


def _require_a_terminal(message: str) -> None:
    """Refuse to prompt into a pipe.

    In CI or a shell pipeline nobody can answer, and quietly eating piped
    stdin would be a stranger failure than saying so. The caller supplies
    the whole message because the way out differs per command.
    """

    if not _stdin_is_a_terminal():
        raise ConfigurationError(message)


def _values_in_force(path: Path) -> dict[str, str]:
    """The value each setting currently resolves to, whatever its source."""

    return {row.key: row.value for row in config_store.describe_settings(path)}


def _ask_for_value(setting: config_store.SettingKey, current: str) -> str | None:
    """Prompt for one setting, returning None when the user leaves it alone.

    Every setting is optional, so an empty answer means "no change" rather
    than "store an empty value" — `config unset` is how a setting goes back
    to its default. A rejected answer re-asks instead of aborting: a typo
    partway through `config init` must not discard the answers before it.
    """

    while True:
        answer = typer.prompt(f"{setting.key} [{current}]", default="", show_default=False)
        answer = answer.strip()
        if not answer:
            return None
        try:
            config_store.validate_value(setting, answer)
        except ConfigurationError as exc:
            typer.echo(f"  {exc}")
            continue
        return answer


@config_app.command("init")
def config_init() -> None:
    """Walk every setting, keeping what is in force unless you type a new value."""

    reporter = ConsoleReporter()
    path = config_store.config_file_path()
    written = 0
    try:
        _require_a_terminal(
            "config init needs a terminal; use config set to write settings non-interactively"
        )
        reporter.message(f"Settings file: {path}")
        reporter.message(
            "Press Enter to keep the value in brackets. Every setting is optional."
        )
        current = _values_in_force(path)
        for setting in config_store.setting_keys():
            answer = _ask_for_value(setting, current.get(setting.key, setting.default))
            if answer is None:
                continue
            config_store.set_value(setting.key, answer, path=path)
            _warn_if_shadowed(reporter, setting)
            written += 1
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    reporter.message(f"Wrote {written} setting{'' if written == 1 else 's'} to {path}")


@config_app.command("set")
def config_set(
    key: str,
    value: Annotated[str | None, typer.Argument()] = None,
) -> None:
    """Set one setting. Omit the value to be asked for it; an empty value restores
    the default."""

    reporter = ConsoleReporter()
    path = config_store.config_file_path()
    try:
        if value is None:
            # Resolve the key before prompting: asking for a value and only
            # then rejecting the key wastes the answer.
            setting = config_store.resolve_key(key)
            _require_a_terminal(
                f"asking for {setting.key} needs a terminal; "
                "pass the value as an argument instead"
            )
            current = _values_in_force(path).get(setting.key, setting.default)
            answer = _ask_for_value(setting, current)
            if answer is None:
                reporter.message(f"{setting.key} unchanged; still {current}")
                return
            value = answer
        if value == "":
            # Every setting is optional, so "no value" is a real answer: drop
            # the entry rather than storing an empty string the model would
            # then have to interpret.
            setting, removed = config_store.unset_value(key, path=path)
            reporter.message(_default_restored(setting, removed))
        else:
            setting = config_store.set_value(key, value, path=path)
            reporter.message(f"{setting.key} = {value} ({path})")
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    _warn_if_shadowed(reporter, setting)


@config_app.command("unset")
def config_unset(key: str) -> None:
    """Remove one setting so its default applies again."""

    reporter = ConsoleReporter()
    try:
        setting, removed = config_store.unset_value(key)
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    reporter.message(_default_restored(setting, removed))
    _warn_if_shadowed(reporter, setting)


def _prompt(prompt: str) -> str:
    """Ask one free-form question, returning the trimmed answer (empty on Enter)."""

    return typer.prompt(prompt, default="", show_default=False).strip()


def _ask_yes(prompt: str, *, default: bool) -> bool:
    """Ask a yes/no question; Enter keeps the default and a bad answer re-asks."""

    suffix = "Y/n" if default else "y/N"
    while True:
        answer = _prompt(f"{prompt} [{suffix}]").casefold()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        typer.echo("  answer y or n")


def _enabled_harnesses(settings: AppSettings) -> list[Harness]:
    """The harnesses this machine has not switched off."""

    enabled = [h for h in Harness if getattr(settings.harnesses, h.name.lower()).enabled]
    if not enabled:
        raise ConfigurationError("every harness is disabled by configuration")
    return enabled


def _harness_is_available(settings: AppSettings, harness: Harness) -> bool:
    if harness is Harness.CLAUDE_CODE:
        return claude_code_is_available(settings.harnesses.claude_code.projects_directory)
    if harness is Harness.CODEX:
        return codex_is_available(settings.harnesses.codex.home_directory)
    return opencode_is_available(settings.harnesses.opencode.cli.executable)


def _harness_availability_detail(settings: AppSettings, harness: Harness) -> str:
    if harness is Harness.CLAUDE_CODE:
        return str(settings.harnesses.claude_code.projects_directory)
    if harness is Harness.CODEX:
        return str(settings.harnesses.codex.home_directory)
    return settings.harnesses.opencode.cli.executable


def _available_harnesses(settings: AppSettings) -> list[Harness]:
    """The enabled harnesses whose sessions this machine can actually read."""

    return [
        harness
        for harness in _enabled_harnesses(settings)
        if _harness_is_available(settings, harness)
    ]


def _default_harness(settings: AppSettings) -> Harness:
    """Pick a harness that works, preferring OpenCode so existing setups do not move."""

    available = _available_harnesses(settings)
    if Harness.OPENCODE in available:
        return Harness.OPENCODE
    if available:
        return available[0]
    checked = ", ".join(
        f"{harness.value} ({_harness_availability_detail(settings, harness)})"
        for harness in _enabled_harnesses(settings)
    )
    raise ConfigurationError(f"no harness is available; checked {checked}")


def _doctor_default_harness(settings: AppSettings) -> Harness:
    """Pick a harness for `doctor` to check, without ever raising.

    `_default_harness` raises when no harness is available — the exact state
    `doctor` exists to diagnose. Failing before any check runs loses the git
    check and the narrator row too, and breaks `doctor --json` for scripts, so
    this falls back to the first enabled harness (or OpenCode, if a machine
    somehow has every harness disabled) and lets the checks themselves report
    what is missing.
    """

    try:
        return _default_harness(settings)
    except ConfigurationError:
        pass
    enabled = [h for h in Harness if getattr(settings.harnesses, h.name.lower()).enabled]
    return enabled[0] if enabled else Harness.OPENCODE


def _ask_harness(settings: AppSettings) -> Harness:
    """Offer only the harnesses that work here; Enter keeps the default."""

    available = _available_harnesses(settings)
    default = _default_harness(settings)
    names = [harness.value for harness in available]
    typer.echo(f"Available harnesses: {', '.join(names)}")
    while True:
        answer = _prompt(f"Harness [{default.value}]")
        if not answer:
            return default
        for harness in available:
            if harness == answer:
                return harness
        typer.echo(f"  choose from: {', '.join(names)}")


def _ask_period(timezone: str, now: datetime) -> DateRange:
    """Ask which window to report; Enter chooses the last full week."""

    while True:
        answer = _prompt("Period [1=last week, 2=last N days, 3=custom range]")
        if not answer:
            return DateRange.previous_week(now=now)
        if answer == "1":
            return DateRange.previous_week(now=now)
        if answer == "2":
            return DateRange.from_days(days=_ask_int("Days", default=7), now=now)
        if answer == "3":
            default_since = (now - timedelta(days=7)).isoformat()
            since = _prompt(f"Since [{default_since}]") or default_since
            until = _prompt(f"Until [{now.isoformat()}]") or now.isoformat()
            try:
                start = _parse_iso_datetime(since, timezone=timezone)
                end = _parse_iso_datetime(until, timezone=timezone)
                return DateRange(since=start, until=end)
            except (ConfigurationError, typer.BadParameter, ValueError) as exc:
                typer.echo(f"  {exc}")
                continue
        typer.echo("  choose 1, 2, or 3")


def _ask_int(prompt: str, *, default: int) -> int:
    """Ask a whole positive number; Enter keeps the default."""

    while True:
        answer = _prompt(f"{prompt} [{default}]")
        if not answer:
            return default
        try:
            value = int(answer)
        except ValueError:
            typer.echo("  enter a whole number")
            continue
        if value < 1:
            typer.echo("  must be at least 1")
            continue
        return value


def _ask_detail() -> DetailLevel:
    """Ask how much detail the report should carry."""

    while True:
        answer = _prompt("Detail [full/brief]")
        if not answer:
            return DetailLevel.FULL
        answer = answer.casefold()
        if answer in {DetailLevel.FULL, DetailLevel.BRIEF}:
            return DetailLevel(answer)
        typer.echo("  choose full or brief")


def _ask_output_path(settings: AppSettings, period: DateRange) -> tuple[Path, bool]:
    """Ask where to write, and whether to overwrite, offering the default path.

    Returns the chosen path and whether to force an overwrite.
    """

    default = _default_output_path(settings, period)
    answer = _prompt(f"Output [{default}]")
    path = Path(answer).expanduser() if answer else default
    force = _ask_yes(f"{path} exists — overwrite?", default=False) if path.exists() else False
    return path, force


@app.command()
def daily() -> None:
    """Draft a standup with yesterday, today and blockers from available coding agents."""

    reporter = ConsoleReporter()
    try:
        _require_a_terminal(
            "daily needs a terminal; run `iiwi daily` from an interactive terminal"
        )
        run_interactive(
            actions=build_interactive_actions(),
            input_source=TerminalInput(),
            console=reporter.console,
            initial_screen=Screen.DAILY_REVIEW,
        )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)


@app.command()
def run(
    verbose: bool = typer.Option(False, "--verbose"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    detail: DetailLevel | None = _RUN_DETAIL_OPTION,
) -> None:
    """Answer a few questions, preview the scan, and generate a worklog.

    Everything `report` takes as flags is asked one by one, the sessions are
    scanned and shown for a yes-or-no review, and only then is the report
    written. Useful when a manager wants a report from a machine you are
    already facing instead of you re-typing a long command line.
    `--dry-run` prints the report instead of writing a file.
    """

    reporter = ConsoleReporter(verbose=verbose)
    try:
        _require_a_terminal(
            "run needs a terminal; use scan and report to work non-interactively"
        )
        settings = _load_settings()
        now = _now_in_timezone(settings.report.timezone)
        harness = _ask_harness(settings)
        sanitize = (
            _ask_yes("Ask OpenCode to redact exported session content?", default=False)
            if harness is Harness.OPENCODE
            else False
        )
        include_children = _ask_yes("Include child/subagent sessions?", default=True)
        period = _ask_period(settings.report.timezone, now)
        detail = detail or _ask_detail()
        # `report`'s default is the narrative review, so the wizard's default is
        # too. Answering no is what `--no-llm` does: the deterministic structured
        # report, which is also the answer when no narration provider is installed.
        # The prompt names no specific CLI: the harness picked above decides which
        # one `_build_report_service` actually invokes (opencode/claude/codex).
        narrative = _ask_yes(
            "Write the narrative review with the local AI CLI?", default=True
        )
        _validate_privacy_options(
            harness=harness,
            sanitize=sanitize if harness is Harness.OPENCODE else None,
        )
        if dry_run:
            # A dry run writes nothing, so asking where to write it — and
            # whether to overwrite a file it will never touch — is a question
            # with no answer that matters. A path is still needed downstream, so
            # take the default one, unforced.
            output_path, force = _default_output_path(settings, period), False
        else:
            output_path, force = _ask_output_path(settings, period)

        with reporter.progress() as progress:
            scan_service = _build_scan_service(
                settings,
                period,
                not include_children,
                harness=harness,
                sanitize=sanitize,
                progress=progress,
            )
            scan = scan_service.scan()
            if scan.loaded_session_count == 0:
                raise NoSessionsError(
                    _no_sessions_message(
                        harness,
                        excluded=scan.excluded_session_count > 0,
                        failed=scan.failed_session_count > 0,
                    )
                )
        reporter.scan_result(scan)
        for warning in scan.warnings:
            reporter.message(f"Warning: {warning}")
        if not _ask_yes(
            f"Generate the report for {len(scan.sessions_by_repository)} repositories?",
            default=True,
        ):
            reporter.message("Aborted; nothing was written.")
            return

        with reporter.progress() as progress:
            service = _build_report_service(
                settings,
                period,
                output_path,
                no_llm=not narrative,
                root_only=not include_children,
                now=now,
                harness=harness,
                sanitize=sanitize,
                detail=detail,
                progress=progress,
            )
            result = service.generate(force=force, dry_run=dry_run, scan=scan)
            if not result.report.repositories and not result.report.narrative_text:
                raise NoSessionsError(
                    _no_sessions_message(
                        harness,
                        excluded=result.scan.excluded_session_count > 0,
                        failed=result.scan.failed_session_count > 0,
                    )
                )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return
    except NoSessionsError as exc:
        _handle_expected_error(exc, code=4)
        return
    except HarnessSourceError as exc:
        _handle_expected_error(exc, code=5)
        return
    except ReportOutputError as exc:
        _handle_expected_error(exc, code=7)
        return
    if not dry_run:
        _record_history(
            harness=harness,
            period=period,
            output_path=result.output_path,
            repository_count=len(result.report.repositories),
            session_count=result.scan.loaded_session_count,
            narrative=bool(result.report.narrative_text),
            detail=detail,
            now=now,
            reporter=reporter,
        )
    if dry_run:
        typer.echo(result.content, nl=False)
    else:
        reporter.message(f"Report written to {result.output_path}")
    for warning in result.report.warnings:
        reporter.message(f"Warning: {warning}")


# Ordered by how often each is reached for: the report first, then the scan
# that previews what would go into one, then the two setup commands.
_MENU_CHOICES = """What do you want to do?
  1  Generate a report
  2  Scan sessions
  3  Check setup (doctor)
  4  Edit settings
  q  Quit"""


def _interactive_menu() -> None:
    """Run the key-driven menu on a real TTY, with a prompt fallback for tests."""

    try:
        _require_a_terminal(
            "iiwi needs a terminal to show the menu; "
            "run a subcommand directly instead"
        )
        if _supports_key_navigation():
            reporter = ConsoleReporter()
            run_interactive(
                actions=build_interactive_actions(),
                input_source=TerminalInput(),
                console=reporter.console,
            )
            return

        # CliRunner replaces stdin with a pipe. Existing integration tests can
        # deliberately force the terminal guard while still exercising this
        # old prompt seam; real TTYs always take the key-driven branch above.
        while True:
            typer.echo(_MENU_CHOICES)
            answer = _prompt("Choice").casefold()
            if not answer or answer == "q":
                return
            if answer == "1":
                dry_run = _ask_yes(
                    "Dry run - print the report instead of writing a file?",
                    default=False,
                )
                run(verbose=False, dry_run=dry_run, detail=None)
                return
            if answer in {"2", "3"}:
                settings = _load_settings()
                harness = _ask_harness(settings)
                # The menu is a person-facing surface, so the commands it
                # dispatches must stay human-readable even when their stdout
                # would otherwise auto-switch to JSON.
                if answer == "2":
                    scan(
                        days=None,
                        period="last-week",
                        since=None,
                        until=None,
                        root_only=False,
                        sanitize=None,
                        harness=harness,
                        verbose=False,
                        quiet=False,
                        json=False,
                    )
                else:
                    doctor(harness=harness, verbose=False, quiet=False, json=False)
                return
            if answer == "4":
                config_init()
                return
            typer.echo("  choose one of the listed options")
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
        return


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the version and exit.",
    ),
) -> None:
    """Open the menu when no subcommand was named."""

    if version:
        typer.echo(f"iiwi {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _interactive_menu()
