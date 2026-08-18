import inspect
import json
import os
import sys
from datetime import datetime, timedelta
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console
from typer.testing import CliRunner

import iiwi.cli as cli
import iiwi.history as history_module
from iiwi import config_store
from iiwi.errors import ConfigurationError, ReportOutputError
from iiwi.history import HistoryEntry, append_history, read_history
from iiwi.models.report import RepositorySummary, WorklogReport
from iiwi.models.time_range import DateRange
from iiwi.progress import NullProgressReporter, ProgressStage
from iiwi.renderers.markdown import MarkdownRenderer
from iiwi.services.report import ReportService
from iiwi.services.scan import ScanService
from iiwi.summarizers.narrator import NarrativeRunner
from iiwi.summarizers.rule_based import RuleBasedSummarizer
from tests.integration.test_scan_service import FakeSource, StaticResolver

runner = CliRunner()
TZ = ZoneInfo("Asia/Taipei")


class StubReportService:
    def __init__(self, output_path: Path, period: DateRange) -> None:
        self.output_path = output_path
        self.period = period

    def generate(self, *, force: bool = False, dry_run: bool = False):
        if self.output_path.exists() and not force:
            raise ReportOutputError(f"report already exists: {self.output_path}")
        report = WorklogReport(
            generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
            period=self.period,
            repositories=[
                RepositorySummary(
                    repository_id="git:github.com/mike/iiwi",
                    display_name="Iiwi",
                )
            ],
        )
        return SimpleNamespace(
            output_path=self.output_path,
            content="# Engineering Worklog\n",
            report=report,
        )


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )


def test_history_json_normalizes_legacy_reports_and_daily_standups(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-12T09:00:00+08:00",
                "harness": "opencode",
                "since": "2026-08-11T00:00:00+08:00",
                "until": "2026-08-12T00:00:00+08:00",
                "output_path": "reports/legacy.md",
                "repository_count": 2,
                "session_count": 5,
                "narrative": True,
                "detail": "full",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    append_history(
        HistoryEntry(
            generated_at=datetime(2026, 8, 13, 9, 0, tzinfo=TZ),
            since=datetime(2026, 8, 12, tzinfo=TZ),
            until=datetime(2026, 8, 13, tzinfo=TZ),
            output_path=Path("reports/daily.md"),
            repository_count=3,
            session_count=8,
            kind=history_module.HistoryKind.DAILY_STANDUP,
            harnesses=("opencode", "codex"),
            unavailable_harnesses=("claude-code",),
        ),
        path=path,
    )

    result = runner.invoke(cli.app, ["history", "--json"])

    assert result.exit_code == 0, result.stdout
    daily, legacy = json.loads(result.stdout)
    assert {
        "kind": daily["kind"],
        "harnesses": daily["harnesses"],
        "unavailable_harnesses": daily["unavailable_harnesses"],
    } == {
        "kind": "daily_standup",
        "harnesses": ["opencode", "codex"],
        "unavailable_harnesses": ["claude-code"],
    }
    assert {
        "kind": legacy["kind"],
        "harnesses": legacy["harnesses"],
        "unavailable_harnesses": legacy["unavailable_harnesses"],
    } == {
        "kind": "report",
        "harnesses": ["opencode"],
        "unavailable_harnesses": [],
    }


def test_report_refuses_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_report = tmp_path / "report.md"
    existing_report.write_text("existing")

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        ["report", "--days", "7", "--output", str(existing_report), "--harness", "opencode"],
    )

    assert result.exit_code == 7
    assert "already exists" in result.stdout


def test_report_supports_previous_calendar_week(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, DateRange] = {}

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        captured["period"] = period
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--period",
            "last-week",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 0
    assert captured["period"].since == datetime(2026, 7, 20, 0, 0, tzinfo=TZ)
    assert captured["period"].until == datetime(2026, 7, 27, 0, 0, tzinfo=TZ)
    assert "# Engineering Worklog" in result.stdout


def test_report_rejects_days_and_period_together() -> None:
    result = runner.invoke(
        cli.app,
        ["report", "--days", "7", "--period", "last-week", "--harness", "opencode"],
    )

    assert result.exit_code == 2


def test_until_requires_since() -> None:
    result = runner.invoke(
        cli.app,
        ["scan", "--until", "2026-07-27T00:00:00+08:00", "--harness", "opencode"],
    )

    assert result.exit_code == 2


def test_scan_rejects_a_reversed_custom_range() -> None:
    result = runner.invoke(
        cli.app,
        [
            "scan",
            "--since",
            "2026-07-10T00:00:00+08:00",
            "--until",
            "2026-07-01T00:00:00+08:00",
            "--harness",
            "codex",
        ],
    )

    assert result.exit_code == 2
    assert "earlier than" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_scan_rejects_an_equal_custom_range() -> None:
    result = runner.invoke(
        cli.app,
        [
            "scan",
            "--since",
            "2026-07-10T00:00:00+08:00",
            "--until",
            "2026-07-10T00:00:00+08:00",
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 2
    assert "earlier than" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_report_rejects_a_reversed_custom_range() -> None:
    result = runner.invoke(
        cli.app,
        [
            "report",
            "--since",
            "2026-07-10T00:00:00+08:00",
            "--until",
            "2026-07-01T00:00:00+08:00",
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 2
    assert "earlier than" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_scan_accepts_a_valid_aware_custom_range(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "scan",
            "--since",
            "2026-07-01T00:00:00+08:00",
            "--until",
            "2026-07-08T00:00:00+08:00",
            "--harness",
            "claude-code",
        ],
        env={
            "IIWI_HARNESSES__CLAUDE_CODE__ENABLED": "true",
            "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY": str(tmp_path),
        },
    )

    assert result.exit_code == 4  # reaches scanning; an empty directory has no sessions


def test_scan_accepts_a_valid_naive_custom_range(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "scan",
            "--since",
            "2026-07-01T00:00:00",
            "--until",
            "2026-07-08T00:00:00",
            "--harness",
            "claude-code",
        ],
        env={
            "IIWI_HARNESSES__CLAUDE_CODE__ENABLED": "true",
            "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY": str(tmp_path),
        },
    )

    assert result.exit_code == 4  # reaches scanning; an empty directory has no sessions


def test_no_llm_builds_a_deterministic_report_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_scan(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
    ):
        return object()

    monkeypatch.setattr(cli, "_build_scan_service", build_scan)

    no_llm_service = cli._build_report_service(
        cli.AppSettings(),
        DateRange.previous_week(now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)),
        tmp_path / "report.md",
        True,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )

    assert no_llm_service._narrative is False

    narrative_service = cli._build_report_service(
        cli.AppSettings(),
        DateRange.previous_week(now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)),
        tmp_path / "report.md",
        False,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )

    assert narrative_service._narrative is True
    assert narrative_service._narrator is not None


def test_days_window_uses_a_single_clock_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second clock read widens `--days 7` into an eight-day usage window."""

    reads = count()
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: (
            datetime(2026, 7, 29, 20, 0, tzinfo=TZ) + timedelta(microseconds=next(reads))
        ),
    )
    captured: dict[str, object] = {}

    class CapturingReportService:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def generate(self, *, force: bool = False, dry_run: bool = False):
            return SimpleNamespace(
                output_path=captured["output_path"],
                content="# Engineering Worklog\n",
                report=WorklogReport(
                    generated_at=captured["now_factory"](),
                    period=captured["period"],
                    repositories=[
                        RepositorySummary(
                            repository_id="git:github.com/mike/iiwi",
                            display_name="Iiwi",
                        )
                    ],
                ),
            )

    monkeypatch.setattr(cli, "ReportService", CapturingReportService)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["usage_days"] == 7
    period = captured["period"]
    assert period.until - period.since == timedelta(days=7)
    assert captured["now_factory"]() == period.until


def test_scan_says_sessions_were_excluded_when_configuration_drops_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An all-excluded scan is not a "nothing happened" scan and must not say so."""

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=0,
                sessions_by_repository={},
                excluded_session_count=1,
                failed_session_count=0,
                warnings=[],
            )

    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda settings, period, root_only=False, *, harness, progress: StubScanService(),
    )

    result = runner.invoke(cli.app, ["scan", "--days", "7", "--harness", "opencode"])

    assert result.exit_code == 4
    assert "excluded by configuration" in result.stdout
    assert "activity found" not in result.stdout


def test_report_says_sessions_were_excluded_when_configuration_drops_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubReportService:
        def __init__(self, output_path: Path, period: DateRange) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False):
            report = WorklogReport(
                generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                period=self.period,
                repositories=[],
            )
            return SimpleNamespace(
                output_path=self.output_path,
                content="",
                report=report,
                scan=SimpleNamespace(excluded_session_count=1, failed_session_count=0),
            )

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--output",
            str(tmp_path / "report.md"),
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 4
    assert "excluded by configuration" in result.stdout
    assert "activity found" not in result.stdout


def test_report_passes_root_only_to_the_report_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        captured["root_only"] = root_only
        captured["progress"] = progress
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--root-only",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["root_only"] is True
    assert captured["progress"] is not None


def test_scan_passes_root_only_to_the_scan_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                candidate_session_count=1,
                loaded_session_count=1,
                failed_session_count=0,
                excluded_session_count=0,
                sessions_by_repository={},
                warnings=[],
                period=DateRange(
                    since=datetime(2026, 7, 20, tzinfo=TZ),
                    until=datetime(2026, 7, 27, tzinfo=TZ),
                ),
            )

    def build(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
        captured["root_only"] = root_only
        captured["progress"] = progress
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)

    result = runner.invoke(
        cli.app, ["scan", "--days", "7", "--root-only", "--harness", "opencode"]
    )

    assert result.exit_code == 0
    assert captured["root_only"] is True
    assert captured["progress"] is not None


def test_quiet_scan_passes_a_null_progress_reporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={},
                warnings=[],
            )

    def build(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        progress=None,
    ):
        captured["progress"] = progress
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)

    result = runner.invoke(cli.app, ["scan", "--days", "7", "--quiet", "--harness", "opencode"])

    assert result.exit_code == 0
    assert isinstance(captured["progress"], NullProgressReporter)
    assert result.stdout.strip() == "1"


def test_dry_run_keeps_progress_out_of_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    original_console_reporter = cli.ConsoleReporter

    def build_reporter(**kwargs):
        return original_console_reporter(
            **kwargs,
            progress_console=Console(
                file=sys.stderr,
                force_terminal=True,
                color_system=None,
            ),
        )

    class ProgressReportService(StubReportService):
        def __init__(self, output_path, period, progress) -> None:
            super().__init__(output_path, period)
            self.progress = progress

        def generate(self, *, force: bool = False, dry_run: bool = False):
            self.progress.start(ProgressStage.RENDERING_REPORT)
            return super().generate(force=force, dry_run=dry_run)

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        return ProgressReportService(output_path, period, progress)

    monkeypatch.setattr(cli, "ConsoleReporter", build_reporter)
    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 0
    assert "# Engineering Worklog" in result.stdout
    assert "Rendering report" not in result.stdout
    assert "Rendering report" in result.stderr


def test_disabled_codex_harness_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__ENABLED", "false")

    result = CliRunner().invoke(cli.app, ["doctor", "--harness", "codex"])

    assert result.exit_code == 3
    assert "IIWI_HARNESSES__CODEX__ENABLED" in result.stdout
def test_report_passes_the_detail_level_to_the_report_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        captured["detail"] = detail
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--detail",
            "brief",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["detail"] is cli.DetailLevel.BRIEF


def test_report_defaults_to_full_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def build(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
        detail=cli.DetailLevel.FULL,
    ):
        captured["detail"] = detail
        return StubReportService(output_path, period)

    monkeypatch.setattr(cli, "_build_report_service", build)

    result = runner.invoke(
        cli.app,
        [
            "report",
            "--days",
            "7",
            "--dry-run",
            "--output",
            str(tmp_path / "report.md"),
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["detail"] is cli.DetailLevel.FULL


def test_report_rejects_an_unknown_detail_level(tmp_path: Path) -> None:
    output_path = tmp_path / "report.md"

    result = runner.invoke(
        cli.app,
        ["report", "--days", "7", "--detail", "medium", "--output", str(output_path)],
    )

    assert result.exit_code == 2
    assert not output_path.exists()


def test_config_path_prints_the_settings_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))

    result = CliRunner().invoke(cli.app, ["config", "path"])

    assert result.exit_code == 0
    assert result.stdout.strip() == str(tmp_path / "config.env")


def test_config_list_shows_the_value_in_force_and_its_source(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    path.write_text(
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL='stored-model'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv(
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False
    )
    # A second setting, set through the environment rather than the file, so the
    # source column is pinned independently: "environment" collides with nothing
    # else in the output, unlike "file" which also appears in the footer's
    # "Settings file: ..." line.
    monkeypatch.setenv("IIWI_REPORT__TIMEZONE", "UTC")
    # Rich wraps to 80 columns when stdout is not a terminal, which would split
    # the longer settings across lines and break these substring assertions.
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "list"])

    assert result.exit_code == 0
    assert "Every setting is optional" in result.stdout

    model_row = next(
        line for line in result.stdout.splitlines() if "harnesses.opencode.cli.model" in line
    )
    assert "stored-model" in model_row
    assert "file" in model_row

    timezone_row = next(
        line for line in result.stdout.splitlines() if "report.timezone" in line
    )
    assert "UTC" in timezone_row
    assert "environment" in timezone_row


def test_help_lists_the_config_command() -> None:
    result = CliRunner().invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "config" in result.stdout


def test_config_set_writes_the_value_and_the_next_load_reads_it(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)

    result = CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"])

    assert result.exit_code == 0
    assert cli._load_settings().harnesses.opencode.cli.model == "gpt-5"


def test_config_set_accepts_a_comma_separated_exclusion_list(
    monkeypatch, tmp_path
) -> None:
    """The exclusion setting is a string so `config set` can store it verbatim."""

    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_REPORT__EXCLUDE_REPOSITORIES", raising=False)

    result = CliRunner().invoke(
        cli.app,
        ["config", "set", "report.exclude_repositories", "dotfiles, notes-vault"],
    )

    assert result.exit_code == 0
    assert cli._load_settings().report.exclude_repositories == "dotfiles, notes-vault"


def test_config_set_rejects_an_unknown_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))

    result = CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.mdoel", "gpt-5"])

    assert result.exit_code == 3
    assert "did you mean harnesses.opencode.cli.model" in result.stdout


def test_config_set_rejects_a_value_the_settings_model_would_reject(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.run_timeout_seconds", "abc"]
    )

    assert result.exit_code == 3
    assert "invalid value for harnesses.opencode.cli.run_timeout_seconds" in result.stdout
    assert not path.exists()


def test_config_set_rejects_a_nan_timeout_without_writing_the_file(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.timeout_seconds", "nan"]
    )

    assert result.exit_code == 3
    assert "invalid value for harnesses.opencode.cli.timeout_seconds" in result.stdout
    assert not path.exists()


def test_config_set_rejects_an_unknown_timezone_without_writing_the_file(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))

    result = CliRunner().invoke(
        cli.app, ["config", "set", "report.timezone", "Mars/Olympus"]
    )

    assert result.exit_code == 3
    assert "unknown timezone" in result.stdout
    assert not path.exists()


def test_config_set_accepts_a_known_timezone(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_REPORT__TIMEZONE", raising=False)

    result = CliRunner().invoke(cli.app, ["config", "set", "report.timezone", "UTC"])

    assert result.exit_code == 0
    assert cli._load_settings().report.timezone == "UTC"


# A negative value needs `--` to reach the command at all; typer would read a
# bare `-1` as an option.
@pytest.mark.parametrize("arguments", [["0"], ["--", "-1"]])
def test_config_set_rejects_a_too_small_evidence_budget_without_writing_the_file(
    monkeypatch, tmp_path, arguments: list[str]
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))

    result = CliRunner().invoke(
        cli.app, ["config", "set", "report.quick_review_max_evidence_bytes", *arguments]
    )

    assert result.exit_code == 3
    assert "invalid value for report.quick_review_max_evidence_bytes" in result.stdout
    assert "greater than or equal to 1000" in result.stdout
    assert not path.exists()


def test_config_set_accepts_the_smallest_evidence_budget(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_REPORT__QUICK_REVIEW_MAX_EVIDENCE_BYTES", raising=False)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "report.quick_review_max_evidence_bytes", "1000"]
    )

    assert result.exit_code == 0
    assert cli._load_settings().report.quick_review_max_evidence_bytes == 1000


def test_config_set_with_an_empty_value_restores_the_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"])

    result = CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", ""])

    assert result.exit_code == 0
    assert "using default" in result.stdout
    assert cli._load_settings().harnesses.opencode.cli.model == ""


def test_config_unset_restores_the_default(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"])

    result = CliRunner().invoke(cli.app, ["config", "unset", "harnesses.opencode.cli.model"])

    assert result.exit_code == 0
    assert cli._load_settings().harnesses.opencode.cli.model == ""


def test_config_unset_of_an_unset_key_says_the_default_is_already_in_use(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "unset", "harnesses.opencode.cli.model"])

    assert result.exit_code == 0
    assert "already using default" in result.stdout


def test_config_set_warns_when_the_environment_overrides_the_write(
    monkeypatch, tmp_path
) -> None:
    """Without this note the write is a silent no-op for the whole shell."""

    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "from-environment")
    monkeypatch.setenv("COLUMNS", "200")

    result = CliRunner().invoke(cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"])

    assert result.exit_code == 0
    assert "IIWI_HARNESSES__OPENCODE__CLI__MODEL" in result.stdout
    assert "takes precedence" in result.stdout


# chmod-based permission denial does not bite on Windows, and root ignores file
# permission bits entirely, so both would make these tests spuriously fail to
# reproduce the OSError-turned-exit-3 behavior they exist to catch.
skip_unless_permissions_enforced = pytest.mark.skipif(
    sys.platform.startswith("win") or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="chmod-based permission denial does not apply on Windows or as root",
)


@skip_unless_permissions_enforced
def test_config_set_exits_3_instead_of_a_traceback_on_an_unwritable_directory(
    monkeypatch, tmp_path
) -> None:
    """Filesystem errors must honor the exit-3 contract, not dump a traceback."""

    directory = tmp_path / "unwritable"
    directory.mkdir()
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(directory / "config.env"))
    directory.chmod(0o500)
    try:
        result = CliRunner().invoke(
            cli.app, ["config", "set", "harnesses.opencode.cli.model", "gpt-5"]
        )
    finally:
        directory.chmod(0o700)  # restore so pytest can clean up tmp_path

    assert result.exit_code == 3
    assert result.exception is None or isinstance(result.exception, SystemExit)


@skip_unless_permissions_enforced
def test_config_list_exits_3_instead_of_a_traceback_on_an_unreadable_file(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    path.write_text(
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL='gpt-5'\n", encoding="utf-8"
    )
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    path.chmod(0o000)
    try:
        result = CliRunner().invoke(cli.app, ["config", "list"])
    finally:
        path.chmod(0o600)  # restore so pytest can clean up tmp_path

    assert result.exit_code == 3
    assert result.exception is None or isinstance(result.exception, SystemExit)


def _as_a_terminal(monkeypatch) -> None:
    """Pretend stdin is a terminal.

    CliRunner feeds stdin through a pipe, so the real `isatty()` is False and
    every prompting test would hit the non-terminal guard instead of the
    behavior it means to exercise.
    """

    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)


def test_config_set_prompts_when_the_value_is_omitted(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__EXECUTABLE", raising=False)
    _as_a_terminal(monkeypatch)

    result = CliRunner().invoke(
        cli.app,
        ["config", "set", "harnesses.opencode.cli.executable"],
        input="opencode-dev\n",
    )

    assert result.exit_code == 0
    assert "opencode" in result.stdout  # the prompt shows the value in force
    assert cli._load_settings().harnesses.opencode.cli.executable == "opencode-dev"


def test_config_set_prompt_leaves_the_setting_alone_on_an_empty_answer(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__EXECUTABLE", raising=False)
    _as_a_terminal(monkeypatch)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.executable"], input="\n"
    )

    assert result.exit_code == 0
    assert "unchanged" in result.stdout
    assert not path.exists()


def test_config_set_prompt_rejects_a_bad_value_and_asks_again(monkeypatch, tmp_path) -> None:
    """A typo must not abort the prompt — the point of prompting is to fix it."""

    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    _as_a_terminal(monkeypatch)

    result = CliRunner().invoke(
        cli.app,
        ["config", "set", "harnesses.opencode.cli.timeout_seconds"],
        input="abc\n45\n",
    )

    assert result.exit_code == 0
    assert "invalid value for harnesses.opencode.cli.timeout_seconds" in result.stdout
    assert cli._load_settings().harnesses.opencode.cli.timeout_seconds == 45.0


def test_config_set_rejects_an_unknown_key_before_prompting(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    _as_a_terminal(monkeypatch)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.mdoel"], input="deepseek-r1\n"
    )

    assert result.exit_code == 3
    assert "did you mean harnesses.opencode.cli.model" in result.stdout


def test_config_set_without_a_value_needs_a_terminal(monkeypatch, tmp_path) -> None:
    """In a pipe or in CI there is nobody to answer, so fail instead of reading stdin."""

    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.model"], input="deepseek-r1\n"
    )

    assert result.exit_code == 3
    assert "needs a terminal" in result.stdout


def test_config_set_with_a_value_still_works_without_a_terminal(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = CliRunner().invoke(
        cli.app, ["config", "set", "harnesses.opencode.cli.model", "deepseek-r1"]
    )

    assert result.exit_code == 0
    assert cli._load_settings().harnesses.opencode.cli.model == "deepseek-r1"


def test_config_init_walks_every_setting_and_writes_only_the_answers(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    monkeypatch.delenv("IIWI_REPORT__TIMEZONE", raising=False)
    _as_a_terminal(monkeypatch)
    settings = config_store.setting_keys()
    answers = {
        "report.timezone": "Europe/Berlin",
        "harnesses.opencode.cli.model": "deepseek-r1",
    }
    keystrokes = "".join(f"{answers.get(setting.key, '')}\n" for setting in settings)

    result = CliRunner().invoke(cli.app, ["config", "init"], input=keystrokes)

    assert result.exit_code == 0, result.stdout
    # Every setting was offered, not just the two that were answered.
    for setting in settings:
        assert setting.key in result.stdout
    assert config_store.stored_values(path) == {
        "IIWI_REPORT__TIMEZONE": "Europe/Berlin",
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL": "deepseek-r1",
    }
    assert "Wrote 2 settings" in result.stdout


def test_config_init_writes_nothing_when_every_answer_is_empty(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    _as_a_terminal(monkeypatch)
    keystrokes = "\n" * len(config_store.setting_keys())

    result = CliRunner().invoke(cli.app, ["config", "init"], input=keystrokes)

    assert result.exit_code == 0
    assert not path.exists()
    assert "Wrote 0 settings" in result.stdout


def test_config_init_needs_a_terminal(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = CliRunner().invoke(cli.app, ["config", "init"], input="\n" * 20)

    assert result.exit_code == 3
    assert "needs a terminal" in result.stdout
    # The way out of a non-interactive shell differs per command, so the
    # message must point at `config set`, not at "pass the value".
    assert "config set" in result.stdout


def _answer_for_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_path: Path,
    period: DateRange,
    final_accept: bool,
) -> None:
    """Wire the run wizard's questions to fixed answers.

    sanitize/children/remote-LLM are all answered with their defaults kept by
    returning False for anything that is not the final preview review.
    """

    def ask_yes(prompt, *, default):
        return final_accept and "Generate the report" in prompt

    def ask_harness(settings):
        return cli.Harness.OPENCODE

    def ask_detail():
        return cli.DetailLevel.FULL

    def ask_output_path(settings, asked_period):
        return output_path, False

    monkeypatch.setattr(cli, "_ask_yes", ask_yes)
    monkeypatch.setattr(cli, "_ask_harness", ask_harness)
    monkeypatch.setattr(cli, "_ask_period", lambda settings_tz, now: period)
    monkeypatch.setattr(cli, "_ask_detail", ask_detail)
    monkeypatch.setattr(cli, "_ask_output_path", ask_output_path)
    _as_a_terminal(monkeypatch)


def test_run_refuses_a_non_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 3
    # The message must name the non-interactive route, not ask for a terminal.
    assert "needs a terminal" in result.stdout
    assert "scan" in result.stdout
    assert "report" in result.stdout


def test_run_scans_once_then_generates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )
    output_path = tmp_path / "worklog.md"
    scan = SimpleNamespace(
        loaded_session_count=2,
        sessions_by_repository={
            "git:github.com/mike/iiwi": [
                SimpleNamespace(repository=SimpleNamespace(display_name="Iiwi"))
            ]
        },
        warnings=[],
    )
    seen: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return scan

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            seen["scan"] = scan
            self.output_path.write_text("# Engineering Worklog\n")
            report = WorklogReport(
                generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                period=self.period,
                repositories=[
                    RepositorySummary(
                        repository_id="git:github.com/mike/iiwi",
                        display_name="Iiwi",
                    )
                ],
            )
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=report,
                scan=scan,
            )

    def build_scan(settings, period, root_only=False, *, harness, sanitize, progress):
        seen["root_only"] = root_only
        return StubScanService()

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        seen["root_only"] = root_only
        return StubReportService(output_path, period)

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=True,
    )
    monkeypatch.setattr(cli, "_build_scan_service", build_scan)
    monkeypatch.setattr(cli, "_build_report_service", build_report)

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0, result.stdout
    assert output_path.exists()
    assert "Report written to" in result.stdout
    # The preview scan is reused for generation, not re-run.
    assert seen["scan"] is scan
    # The wizard answered "no" to including child sessions, so both the scan
    # and the report were told to keep to root sessions.
    assert seen["root_only"] is True


def test_run_detail_flags_keep_session_reports_and_bypass_outcome_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )
    mode = {"narrative": True}
    built: list[tuple[cli.DetailLevel, bool]] = []
    narrative_calls: list[dict[str, str]] = []

    class StaticNarrativeRunner:
        def run(self, *, transcript: str, prompt: str, title: str) -> str:
            narrative_calls.append(
                {"transcript": transcript, "prompt": prompt, "title": title}
            )
            return "Narrative summary"

    def ask_yes(prompt: str, *, default: bool) -> bool:
        del default
        if "narrative review" in prompt:
            return mode["narrative"]
        return "Generate the report" in prompt

    def build_report(
        settings,
        asked_period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        del settings, harness, progress
        built.append((detail, no_llm))
        return ReportService(
            scan_service=ScanService(
                source=FakeSource(),
                period=asked_period,
                resolver=StaticResolver(),
            ),
            summarizer=RuleBasedSummarizer(),
            renderer=MarkdownRenderer(),
            period=asked_period,
            output_path=output_path,
            now_factory=lambda: now,
            detail=detail,
            narrative=not no_llm,
            narrator=(
                None
                if no_llm
                else cast(NarrativeRunner, StaticNarrativeRunner())
            ),
            include_subagents=not root_only,
            sanitized=sanitize,
        )

    outputs = iter([tmp_path / "brief.md", tmp_path / "full.md"])
    monkeypatch.setattr(cli, "_ask_yes", ask_yes)
    monkeypatch.setattr(cli, "_ask_harness", lambda settings: cli.Harness.OPENCODE)
    monkeypatch.setattr(cli, "_ask_period", lambda timezone, now: period)
    monkeypatch.setattr(
        cli,
        "_ask_detail",
        lambda: pytest.fail("an explicit --detail must not prompt for detail"),
    )
    monkeypatch.setattr(
        cli,
        "_ask_output_path",
        lambda settings, asked_period: (next(outputs), False),
    )
    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda *args, **kwargs: ScanService(
            source=FakeSource(),
            period=period,
            resolver=StaticResolver(),
        ),
    )
    monkeypatch.setattr(cli, "_build_report_service", build_report)
    monkeypatch.setattr(
        cli,
        "build_interactive_actions",
        lambda: pytest.fail("the legacy run command must not enter Quick Review"),
    )
    _as_a_terminal(monkeypatch)

    brief = runner.invoke(cli.app, ["run", "--detail", "brief"])
    mode["narrative"] = False
    full = runner.invoke(cli.app, ["run", "--detail", "full"])

    assert brief.exit_code == 0, brief.stdout
    assert full.exit_code == 0, full.stdout
    assert built == [
        (cli.DetailLevel.BRIEF, False),
        (cli.DetailLevel.FULL, True),
    ]
    assert "Narrative summary" in (tmp_path / "brief.md").read_text(encoding="utf-8")
    assert "Do not include session IDs, file lists, command lists, or Usage." in (
        narrative_calls[0]["prompt"]
    )
    full_content = (tmp_path / "full.md").read_text(encoding="utf-8")
    assert "#### Sessions" in full_content
    assert "Narrative summary" not in full_content
    history = read_history(path=tmp_path / "history.jsonl")
    assert [(entry.narrative, entry.detail) for entry in history] == [
        (True, "brief"),
        (False, "full"),
    ]


def test_run_aborts_when_the_preview_is_declined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "worklog.md"
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={
                    "git:github.com/mike/iiwi": [
                        SimpleNamespace(repository=SimpleNamespace(display_name="Iiwi"))
                    ]
                },
                warnings=[],
            )

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=False,
    )
    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda settings, period, root_only=False, *, harness, sanitize, progress: StubScanService(),
    )

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0
    assert "Aborted" in result.stdout
    assert not output_path.exists()


def test_run_preview_says_sessions_were_excluded_when_configuration_drops_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "worklog.md"
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=0,
                sessions_by_repository={},
                excluded_session_count=1,
                failed_session_count=0,
                warnings=[],
            )

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=False,
    )
    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda settings, period, root_only=False, *, harness, sanitize, progress: StubScanService(),
    )

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 4
    assert "excluded by configuration" in result.stdout
    assert "activity found" not in result.stdout


def test_run_generation_says_sessions_were_excluded_when_configuration_drops_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "worklog.md"
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={
                    "git:github.com/mike/iiwi": [
                        SimpleNamespace(repository=SimpleNamespace(display_name="Iiwi"))
                    ]
                },
                warnings=[],
            )

    class StubReportService:
        def __init__(self, output_path: Path, period: DateRange) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            report = WorklogReport(
                generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                period=self.period,
                repositories=[],
            )
            return SimpleNamespace(
                output_path=self.output_path,
                content="",
                report=report,
                scan=SimpleNamespace(excluded_session_count=1, failed_session_count=0),
            )

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=True,
    )
    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda *args, **kwargs: StubScanService(),
    )
    monkeypatch.setattr(
        cli,
        "_build_report_service",
        lambda settings, period, output_path, no_llm, root_only=False, **kwargs: StubReportService(
            output_path, period
        ),
    )

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 4
    assert "excluded by configuration" in result.stdout
    assert "activity found" not in result.stdout


def test_run_accepts_a_non_opencode_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-OpenCode harness must not trip the sanitize-only-for-OpenCode guard."""

    output_path = tmp_path / "worklog.md"
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )
    seen: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={
                    "git:github.com/mike/iiwi": [
                        SimpleNamespace(repository=SimpleNamespace(display_name="Iiwi"))
                    ]
                },
                warnings=[],
            )

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            self.output_path.write_text("# Engineering Worklog\n")
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=WorklogReport(
                    generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                    period=self.period,
                    repositories=[
                        RepositorySummary(
                            repository_id="git:github.com/mike/iiwi",
                            display_name="Iiwi",
                        )
                    ],
                ),
                scan=scan,
            )

    def build_scan(settings, period, root_only=False, *, harness, sanitize, progress):
        seen["harness"] = harness
        seen["sanitize"] = sanitize
        return StubScanService()

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        return StubReportService(output_path, period)

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=True,
    )
    monkeypatch.setattr(cli, "_ask_harness", lambda settings: cli.Harness.CLAUDE_CODE)
    monkeypatch.setattr(cli, "_build_scan_service", build_scan)
    monkeypatch.setattr(cli, "_build_report_service", build_report)

    result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0, result.stdout
    assert output_path.exists()
    assert seen["harness"] is cli.Harness.CLAUDE_CODE
    assert seen["sanitize"] is False


def test_run_dry_run_prints_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )
    output_path = tmp_path / "worklog.md"
    scan = SimpleNamespace(
        loaded_session_count=2,
        sessions_by_repository={
            "git:github.com/mike/iiwi": [
                SimpleNamespace(repository=SimpleNamespace(display_name="Iiwi"))
            ]
        },
        warnings=[],
    )
    seen: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return scan

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            seen["dry_run"] = dry_run
            if not dry_run:
                self.output_path.write_text("# Engineering Worklog\n")
            report = WorklogReport(
                generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                period=self.period,
                repositories=[
                    RepositorySummary(
                        repository_id="git:github.com/mike/iiwi",
                        display_name="Iiwi",
                    )
                ],
            )
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=report,
                scan=scan,
            )

    def build_scan(settings, period, root_only=False, *, harness, sanitize, progress):
        return StubScanService()

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        return StubReportService(output_path, period)

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=True,
    )
    monkeypatch.setattr(cli, "_build_scan_service", build_scan)
    monkeypatch.setattr(cli, "_build_report_service", build_report)

    result = runner.invoke(cli.app, ["run", "--dry-run"])

    assert result.exit_code == 0, result.stdout
    assert seen["dry_run"] is True
    # A dry run prints the report instead of writing it.
    assert not output_path.exists()
    assert "# Engineering Worklog" in result.stdout
    assert "Report written to" not in result.stdout


def test_a_dry_run_does_not_ask_where_to_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dry run writes nothing, so the output question has no answer that matters.

    Asking it would have the user decide whether to overwrite a file the command
    is never going to touch.
    """

    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ), until=datetime(2026, 7, 27, tzinfo=TZ)
    )
    output_path = tmp_path / "worklog.md"
    seen: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=2,
                sessions_by_repository={
                    "git:github.com/mike/iiwi": [
                        SimpleNamespace(repository=SimpleNamespace(display_name="Iiwi"))
                    ]
                },
                warnings=[],
            )

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            seen["force"] = force
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=WorklogReport(
                    generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                    period=self.period,
                    repositories=[
                        RepositorySummary(
                            repository_id="git:github.com/mike/iiwi",
                            display_name="Iiwi",
                        )
                    ],
                ),
                scan=scan,
            )

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        seen["output_path"] = output_path
        return StubReportService(output_path, period)

    _answer_for_run(
        monkeypatch,
        output_path=output_path,
        period=period,
        final_accept=True,
    )
    # `_answer_for_run` wires the output question to an answer; replace that with
    # a failure, since a dry run must not reach it at all.
    monkeypatch.setattr(
        cli,
        "_ask_output_path",
        lambda settings, period: pytest.fail("a dry run must not ask where to write"),
    )
    monkeypatch.setattr(cli, "_default_output_path", lambda settings, period: output_path)
    monkeypatch.setattr(
        cli, "_build_scan_service", lambda *args, **kwargs: StubScanService()
    )
    monkeypatch.setattr(cli, "_build_report_service", build_report)

    result = runner.invoke(cli.app, ["run", "--dry-run"])

    assert result.exit_code == 0, result.stdout
    # The default path is used, unforced, and the report is printed not written.
    assert seen["output_path"] == output_path
    assert seen["force"] is False
    assert not output_path.exists()
    assert "# Engineering Worklog" in result.stdout


def test_bare_invocation_runs_the_report_wizard(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def stub_run(
        *, verbose: bool, dry_run: bool, detail: cli.DetailLevel | None
    ) -> None:
        seen["verbose"] = verbose
        seen["dry_run"] = dry_run
        seen["detail"] = detail

    monkeypatch.setattr(cli, "run", stub_run)
    _as_a_terminal(monkeypatch)

    # "1" chooses the report, "n" declines the dry run.
    result = runner.invoke(cli.app, [], input="1\nn\n")

    assert result.exit_code == 0, result.stdout
    assert seen == {"verbose": False, "dry_run": False, "detail": None}


def test_bare_invocation_can_ask_the_report_wizard_for_a_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def stub_run(
        *, verbose: bool, dry_run: bool, detail: cli.DetailLevel | None
    ) -> None:
        seen["dry_run"] = dry_run
        seen["detail"] = detail

    monkeypatch.setattr(cli, "run", stub_run)
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="1\ny\n")

    assert result.exit_code == 0, result.stdout
    assert seen["dry_run"] is True
    assert seen["detail"] is None


def test_bare_invocation_runs_the_settings_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(cli, "config_init", lambda: called.append(True))
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="4\n")

    assert result.exit_code == 0, result.stdout
    assert called == [True]


def test_the_menu_asks_again_after_an_answer_it_does_not_know(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must not end the session; the choices are shown again."""

    called: list[bool] = []
    monkeypatch.setattr(cli, "config_init", lambda: called.append(True))
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="banana\n4\n")

    assert result.exit_code == 0, result.stdout
    assert called == [True]
    assert "choose one of the listed options" in result.stdout
    # The choices are printed again, so the second answer is an informed one.
    assert result.stdout.count("Generate a report") >= 2


def _nothing_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on any dispatched command, so a mis-routed answer cannot slip past.

    Guarding only one of the four would let a quit answer that reached a
    different entry pass the test.
    """

    for name in ("config_init", "run", "doctor", "scan"):
        monkeypatch.setattr(
            cli, name, lambda *args, **kwargs: pytest.fail("nothing should run")
        )


def test_the_menu_quits_without_doing_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    _nothing_dispatches(monkeypatch)
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="q\n")

    assert result.exit_code == 0, result.stdout


def test_an_empty_answer_quits_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    _nothing_dispatches(monkeypatch)
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="\n")

    assert result.exit_code == 0, result.stdout


def test_the_menu_needs_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = runner.invoke(cli.app, [], input="1\n")

    assert result.exit_code == 3
    assert "needs a terminal" in result.stdout
    # The way out is naming a subcommand, not a different interactive command.
    assert "subcommand" in result.stdout


def test_naming_a_subcommand_does_not_open_the_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The callback must stand aside whenever Typer has a command to run."""

    monkeypatch.setattr(
        cli, "_interactive_menu", lambda: pytest.fail("the menu must not open")
    )

    result = runner.invoke(cli.app, ["config", "path"])

    assert result.exit_code == 0, result.stdout


def test_help_still_works_without_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "_interactive_menu", lambda: pytest.fail("the menu must not open")
    )

    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0, result.stdout
    assert "Usage" in result.stdout


def test_run_walks_the_real_prompts_on_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the wizard through its actual prompts, answering nothing.

    Pressing Enter at every question must accept the defaults, which is the
    interactive equivalent of `report --days 7 --no-llm`.
    """

    output_path = tmp_path / "worklog.md"
    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                loaded_session_count=1,
                sessions_by_repository={
                    "git:github.com/mike/iiwi": [
                        SimpleNamespace(repository=SimpleNamespace(display_name="Iiwi"))
                    ]
                },
                warnings=[],
            )

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False, scan=None):
            self.output_path.write_text("# Engineering Worklog\n")
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=WorklogReport(
                    generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
                    period=self.period,
                    repositories=[
                        RepositorySummary(
                            repository_id="git:github.com/mike/iiwi",
                            display_name="Iiwi",
                        )
                    ],
                ),
                scan=scan,
            )

    def build_scan(settings, period, root_only=False, *, harness, sanitize, progress):
        captured["harness"] = harness
        captured["sanitize"] = sanitize
        captured["root_only"] = root_only
        return StubScanService()

    def build_report(
        settings,
        period,
        output_path,
        no_llm,
        root_only=False,
        *,
        now,
        harness,
        sanitize,
        detail,
        progress,
    ):
        captured["no_llm"] = no_llm
        captured["detail"] = detail
        return StubReportService(output_path, period)

    _as_a_terminal(monkeypatch)
    monkeypatch.setattr(cli, "_default_output_path", lambda settings, period: output_path)
    monkeypatch.setattr(cli, "_build_scan_service", build_scan)
    monkeypatch.setattr(cli, "_build_report_service", build_report)
    # `run` has no --harness flag; Enter accepts _ask_harness's default, which
    # is _default_harness. Fixing it here keeps the wizard's real prompt-answering
    # flow under test without depending on this machine's installed harnesses.
    monkeypatch.setattr(cli, "_default_harness", lambda settings: cli.Harness.OPENCODE)

    result = runner.invoke(cli.app, ["run"], input="\n" * 8)

    assert result.exit_code == 0, result.stdout
    assert output_path.exists()
    assert "Report written to" in result.stdout
    assert captured["harness"] is cli.Harness.OPENCODE
    assert captured["sanitize"] is False
    # Enter at the narrative question keeps `report`'s default: the narrative
    # review, which is `no_llm=False`.
    assert captured["no_llm"] is False
    assert captured["root_only"] is False
    assert captured["detail"] is cli.DetailLevel.FULL


def test_bare_invocation_runs_doctor_against_the_chosen_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def stub_doctor(*, harness, verbose: bool, quiet: bool, json) -> None:
        seen["harness"] = harness
        seen["verbose"] = verbose
        seen["quiet"] = quiet
        seen["json"] = json

    monkeypatch.setattr(cli, "doctor", stub_doctor)
    monkeypatch.setattr(cli, "_ask_harness", lambda settings: cli.Harness.OPENCODE)
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="3\n")

    assert result.exit_code == 0, result.stdout
    assert seen == {
        "harness": cli.Harness.OPENCODE,
        "verbose": False,
        "quiet": False,
        "json": False,
    }


def test_bare_invocation_runs_scan_against_the_chosen_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def stub_scan(
        *, days, period, since, until, root_only, sanitize, harness, verbose, quiet, json
    ) -> None:
        seen["harness"] = harness
        seen["days"] = days
        seen["period"] = period
        seen["since"] = since
        seen["until"] = until
        seen["root_only"] = root_only
        seen["sanitize"] = sanitize
        seen["json"] = json

    monkeypatch.setattr(cli, "scan", stub_scan)
    monkeypatch.setattr(cli, "_ask_harness", lambda settings: cli.Harness.CLAUDE_CODE)
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="2\n")

    assert result.exit_code == 0, result.stdout
    assert seen["harness"] is cli.Harness.CLAUDE_CODE
    # `scan` has no default period — leaving days/period/since all unset is a
    # usage error — so the menu names the last full week, as `run` does when its
    # period question is answered with Enter. Everything else keeps the
    # command-line default; the period questions belong to `run`, not here.
    assert seen["days"] is None
    assert seen["period"] == "last-week"
    assert seen["since"] is None
    assert seen["until"] is None
    assert seen["root_only"] is False
    assert seen["sanitize"] is None
    # The menu is a person-facing surface, so its dispatch forces human output
    # even though CliRunner's piped stdout would otherwise auto-switch to JSON.
    assert seen["json"] is False


def test_the_menu_runs_the_real_scan_command_over_the_last_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the real `scan` from the menu, stubbing only the service layer.

    The other menu tests replace the dispatched command with a stub, so they
    assert the argument list but never execute it. That cannot catch an argument
    list `scan` itself rejects — and `scan` has no default period, so an
    all-`None` period is a `typer.BadParameter`, not a default. Patching
    `_build_scan_service` is the seam the non-menu `scan` tests already use.
    """

    captured: dict[str, object] = {}

    class StubScanService:
        def scan(self):
            return SimpleNamespace(
                candidate_session_count=1,
                loaded_session_count=1,
                failed_session_count=0,
                excluded_session_count=0,
                sessions_by_repository={
                    "git:github.com/mike/iiwi": [
                        SimpleNamespace(
                            session=SimpleNamespace(
                                session_id="ses-1",
                                title="Menu scan",
                                working_directory="/tmp/iiwi",
                                activities=[],
                            ),
                            repository=SimpleNamespace(display_name="Iiwi"),
                        )
                    ]
                },
                warnings=[],
                period=DateRange(
                    since=datetime(2026, 7, 20, tzinfo=TZ),
                    until=datetime(2026, 7, 27, tzinfo=TZ),
                ),
            )

    def build(
        settings,
        period,
        root_only=False,
        *,
        harness=cli.Harness.OPENCODE,
        sanitize=False,
        progress=None,
    ):
        captured["period"] = period
        captured["harness"] = harness
        return StubScanService()

    monkeypatch.setattr(cli, "_build_scan_service", build)
    _as_a_terminal(monkeypatch)
    # The menu has no --harness flag either; see test_run_walks_the_real_prompts_on_defaults.
    monkeypatch.setattr(cli, "_default_harness", lambda settings: cli.Harness.OPENCODE)

    # "2" chooses the scan; the empty answer keeps the default harness.
    result = runner.invoke(cli.app, [], input="2\n\n")

    assert result.exit_code == 0, result.stdout
    assert captured["harness"] is cli.Harness.OPENCODE
    assert captured["period"] == DateRange.previous_week(
        now=datetime(2026, 7, 29, 20, 0, tzinfo=TZ)
    )
    # The scan ran to completion and rendered its table.
    assert "Iiwi Scan" in result.stdout


def test_the_menu_passes_every_parameter_of_the_commands_it_dispatches() -> None:
    """Guard against signature drift in the commands the menu calls directly.

    Calling a Typer command function in Python bypasses Typer's parameter
    processing, so any argument the menu leaves out arrives as a
    `typer.OptionInfo` rather than a value. Typer types `typer.Option` as `Any`
    and every parameter has a default, so neither pyright nor ruff notices.
    Adding an option to one of these commands must therefore fail here until the
    menu's call is updated too.
    """

    assert set(inspect.signature(cli.scan).parameters) == {
        "days",
        "period",
        "since",
        "until",
        "root_only",
        "sanitize",
        "harness",
        "verbose",
        "quiet",
        "json",
    }
    assert set(inspect.signature(cli.doctor).parameters) == {
        "harness",
        "verbose",
        "quiet",
        "json",
    }
    assert set(inspect.signature(cli.run).parameters) == {
        "verbose",
        "dry_run",
        "detail",
    }


def test_the_menu_reports_a_configuration_error_from_the_harness_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every harness disabled must exit 3, not raise through the callback."""

    def refuse(settings):
        raise ConfigurationError("every harness is disabled by configuration")

    monkeypatch.setattr(cli, "_ask_harness", refuse)
    monkeypatch.setattr(cli, "doctor", lambda **kwargs: pytest.fail("must not run"))
    _as_a_terminal(monkeypatch)

    result = runner.invoke(cli.app, [], input="3\n")

    assert result.exit_code == 3
    assert "every harness is disabled by configuration" in result.stdout
