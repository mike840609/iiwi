from pathlib import Path

from typer.testing import CliRunner

from iiwi.cli import app

runner = CliRunner()


def test_help_lists_core_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "scan" in result.stdout
    assert "report" in result.stdout
    assert "daily" in result.stdout


def test_daily_help_describes_standup_without_report_selection_options() -> None:
    result = runner.invoke(app, ["daily", "--help"])

    assert result.exit_code == 0
    assert "standup" in result.stdout.casefold()
    for prohibited in ("--harness", "--period", "--days", "--no-review"):
        assert prohibited not in result.stdout


def test_daily_refuses_non_terminal_input(monkeypatch) -> None:
    import iiwi.cli as cli

    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = CliRunner().invoke(cli.app, ["daily"])

    assert result.exit_code == 3
    assert "daily needs a terminal" in result.stdout.casefold()


def test_daily_dispatches_directly_to_the_daily_review_screen(monkeypatch) -> None:
    import iiwi.cli as cli
    from iiwi.interactive.models import Screen

    captured: dict[str, object] = {}
    fake_input = object()
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(cli, "TerminalInput", lambda: fake_input)
    monkeypatch.setattr(cli, "build_interactive_actions", lambda: object())
    monkeypatch.setattr(cli, "run_interactive", lambda **kwargs: captured.update(kwargs))

    result = CliRunner().invoke(cli.app, ["daily"])

    assert result.exit_code == 0
    assert captured["input_source"] is fake_input
    assert captured["initial_screen"] is Screen.DAILY_REVIEW


def test_scan_rejects_an_unknown_harness() -> None:
    from typer.testing import CliRunner

    import iiwi.cli as cli

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7", "--harness", "unknown"])

    assert result.exit_code == 2


def test_build_scan_service_selects_the_claude_code_source(tmp_path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import iiwi.cli as cli
    from iiwi.config import AppSettings
    from iiwi.harnesses.claude_code.source import ClaudeCodeFileSource
    from iiwi.models.time_range import DateRange

    tz = ZoneInfo("Asia/Taipei")
    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=tz),
        until=datetime(2026, 7, 27, tzinfo=tz),
    )

    service = cli._build_scan_service(
        settings,
        period,
        harness=cli.Harness.CLAUDE_CODE,
    )

    assert isinstance(service._source, ClaudeCodeFileSource)


def test_build_scan_service_drops_sessions_from_a_configured_excluded_repository(
    tmp_path, monkeypatch
) -> None:
    """The exclude setting takes effect through `_build_scan_service`: a scan
    built from it omits the configured repository's sessions, rather than just
    wiring a private field that nothing observable depends on.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import iiwi.cli as cli
    from iiwi.config import AppSettings
    from iiwi.models.repository import (
        RepositoryIdentity,
        RepositoryIdentityType,
    )
    from iiwi.models.session import (
        ActivityType,
        AgentSession,
        SessionActivity,
        SessionDescriptor,
    )
    from iiwi.models.time_range import DateRange

    tz = ZoneInfo("Asia/Taipei")
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=tz),
        until=datetime(2026, 7, 27, tzinfo=tz),
    )

    def session(session_id: str, directory: str) -> AgentSession:
        return AgentSession(
            harness="claude-code",
            session_id=session_id,
            working_directory=directory,
            activities=[
                SessionActivity(
                    activity_id=session_id,
                    activity_type=ActivityType.USER_MESSAGE,
                    timestamp=datetime(2026, 7, 21, tzinfo=tz),
                    content="hi",
                )
            ],
        )

    sessions = {
        "dotfiles-1": session("dotfiles-1", "/tmp/dotfiles"),
        "notes-1": session("notes-1", "/tmp/notes"),
        "work-1": session("work-1", "/tmp/work"),
    }

    class StubSource:
        def discover(self, _period: DateRange) -> list[SessionDescriptor]:
            return [
                SessionDescriptor(harness="claude-code", session_id=session_id)
                for session_id in sessions
            ]

        def load(self, descriptor: SessionDescriptor) -> AgentSession:
            return sessions[descriptor.session_id]

    class StubResolver:
        def __init__(self, runner=None) -> None:
            self._runner = runner

        def resolve(self, agent_session: AgentSession) -> RepositoryIdentity:
            repository_name = agent_session.session_id.split("-", 1)[0]
            return RepositoryIdentity(
                repository_id=f"git:github.com/mike/{repository_name}",
                display_name=repository_name.capitalize(),
                identity_type=RepositoryIdentityType.GIT_REMOTE,
                resolution_method="stub",
            )

    def make_source(**kwargs) -> StubSource:
        return StubSource()

    monkeypatch.setattr(cli, "ClaudeCodeFileSource", make_source)
    monkeypatch.setattr(cli, "RepositoryResolver", StubResolver)

    settings = AppSettings()
    settings.report.exclude_repositories = "git:github.com/mike/dotfiles"
    settings.harnesses.claude_code.projects_directory = tmp_path

    service = cli._build_scan_service(
        settings,
        period,
        harness=cli.Harness.CLAUDE_CODE,
    )
    result = service.scan()

    assert [item.session.session_id for item in result.resolved_sessions] == [
        "notes-1",
        "work-1",
    ]
    assert result.excluded_session_count == 1
    assert result.loaded_session_count == 2
    assert any("Dotfiles" in warning for warning in result.warnings)


def test_build_report_service_carries_the_detail_level(tmp_path) -> None:
    """Closes a seam a mutation test found: deleting `detail=detail,` from the
    `ReportService(...)` call in `_build_report_service` left the full suite
    green, so `--detail brief` could silently become a no-op end to end.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import iiwi.cli as cli
    from iiwi.config import AppSettings
    from iiwi.models.time_range import DateRange
    from iiwi.renderers.markdown import DetailLevel

    tz = ZoneInfo("Asia/Taipei")
    settings = AppSettings()
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=tz),
        until=datetime(2026, 7, 27, tzinfo=tz),
    )

    service = cli._build_report_service(
        settings,
        period,
        tmp_path / "report.md",
        no_llm=True,
        now=datetime(2026, 7, 29, 20, 0, tzinfo=tz),
        detail=DetailLevel.BRIEF,
    )

    assert service._detail is DetailLevel.BRIEF


def test_a_disabled_harness_is_refused_with_a_configuration_error(tmp_path) -> None:
    """An off switch a privacy tool advertises has to actually turn something off."""

    import iiwi.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["scan", "--days", "7", "--harness", "claude-code"],
        env={"IIWI_HARNESSES__CLAUDE_CODE__ENABLED": "false"},
    )

    assert result.exit_code == 3
    assert "IIWI_HARNESSES__CLAUDE_CODE__ENABLED" in result.stdout


def test_doctor_refuses_a_disabled_harness() -> None:
    import iiwi.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["doctor", "--harness", "opencode"],
        env={"IIWI_HARNESSES__OPENCODE__ENABLED": "false"},
    )

    assert result.exit_code == 3
    assert "disabled by configuration" in result.stdout


def test_report_still_runs_when_the_harness_is_enabled(tmp_path) -> None:
    import iiwi.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["scan", "--days", "7", "--harness", "claude-code"],
        env={
            "IIWI_HARNESSES__CLAUDE_CODE__ENABLED": "true",
            "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY": str(tmp_path),
        },
    )

    assert result.exit_code == 4  # no sessions in an empty directory, not a config error


def test_no_sessions_message_only_claims_exclusion_when_it_is_the_whole_story() -> None:
    """A scan emptied by load failures must not be blamed on the config: the
    exclusion explanation is claimed only when exclusion removed every session
    and something else did not eat the rest.
    """
    import iiwi.cli as cli

    neutral = (
        (cli.Harness.OPENCODE, "no opencode activity found in the requested period"),
        (cli.Harness.CODEX, "no codex activity found in the requested period"),
    )
    excluded = (
        (
            cli.Harness.OPENCODE,
            "all opencode sessions in the requested period were excluded by configuration",
        ),
        (
            cli.Harness.CODEX,
            "all codex sessions in the requested period were excluded by configuration",
        ),
    )

    for harness, message in excluded:
        assert cli._no_sessions_message(harness, excluded=True, failed=False) == message
    for harness, message in neutral:
        assert cli._no_sessions_message(harness, excluded=False, failed=False) == message
        assert cli._no_sessions_message(harness, excluded=False, failed=True) == message
        assert cli._no_sessions_message(harness, excluded=True, failed=True) == message


def test_load_settings_reads_the_settings_file(monkeypatch, tmp_path) -> None:
    import iiwi.cli as cli

    path = tmp_path / "config.env"
    path.write_text("IIWI_HARNESSES__OPENCODE__CLI__MODEL='from-file'\n", encoding="utf-8")
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)

    assert cli._load_settings().harnesses.opencode.cli.model == "from-file"


def test_the_environment_beats_the_settings_file(monkeypatch, tmp_path) -> None:
    """The file is a default store, not an override: an exported variable wins."""

    import iiwi.cli as cli

    path = tmp_path / "config.env"
    path.write_text("IIWI_HARNESSES__OPENCODE__CLI__MODEL='from-file'\n", encoding="utf-8")
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "from-environment")

    assert cli._load_settings().harnesses.opencode.cli.model == "from-environment"


def test_load_settings_points_at_the_file_when_it_holds_a_bad_value(
    monkeypatch, tmp_path
) -> None:
    import pytest

    import iiwi.cli as cli
    from iiwi.errors import ConfigurationError

    path = tmp_path / "config.env"
    path.write_text(
        "IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS='abc'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))

    with pytest.raises(ConfigurationError) as error:
        cli._load_settings()

    assert str(path) in str(error.value)


def test_load_settings_ignores_a_foreign_variable_in_the_settings_file(
    monkeypatch, tmp_path
) -> None:
    """A line another tool owns must not make every command reject the file.

    `DotEnvSettingsSource` sweeps every variable in the file into the model,
    unlike the environment source, which only reads names it owns — so a
    settings file shared with (or leftover from) another tool must not turn
    into a hard `extra_forbidden` failure.
    """

    import iiwi.cli as cli

    path = tmp_path / "config.env"
    path.write_text(
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL='gpt-5'\n"
        "OPENAI_API_KEY='sk-proj-not-a-real-secret-key'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)

    settings = cli._load_settings()

    assert settings.harnesses.opencode.cli.model == "gpt-5"


def test_load_settings_does_not_echo_a_secret_looking_value_in_its_error(
    monkeypatch, tmp_path
) -> None:
    """A bad value in a setting the model DOES own still lands in the message.

    (a) alone (ignoring foreign variables) does not cover this: a malformed
    value for a setting the model owns, such as a base URL with an embedded
    password, still reaches pydantic's validation error text, and that text
    must not echo the secret verbatim.
    """

    import pytest

    import iiwi.cli as cli
    from iiwi.errors import ConfigurationError

    path = tmp_path / "config.env"
    path.write_text(
        "IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS="
        "'sk-proj-not-a-real-secret-key'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))

    with pytest.raises(ConfigurationError) as error:
        cli._load_settings()

    assert "sk-proj-not-a-real-secret-key" not in str(error.value)
    assert "[REDACTED]" in str(error.value)


def _stub_scan_service(monkeypatch, scan):
    """Point `scan`'s service seam at a canned result, keeping the command's
    option plumbing and output handling under test."""

    import iiwi.cli as cli

    class StubScanService:
        def scan(self):
            return scan

    monkeypatch.setattr(
        cli,
        "_build_scan_service",
        lambda *args, **kwargs: StubScanService(),
    )
    return cli


def _stub_scan(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import iiwi.cli as cli
    from iiwi.models.repository import (
        RepositoryIdentity,
        RepositoryIdentityType,
        ResolvedSession,
    )
    from iiwi.models.session import (
        ActivityType,
        AgentSession,
        SessionActivity,
    )
    from iiwi.models.time_range import DateRange
    from iiwi.services.scan import ScanResult

    tz = ZoneInfo("Asia/Taipei")
    session = AgentSession(
        harness="opencode",
        session_id="sess-1",
        title="Tune dotfiles",
        working_directory="/Users/me/dotfiles",
        activities=[
            SessionActivity(
                activity_id="a-1",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=datetime(2026, 7, 21, 8, 0, tzinfo=tz),
                content="hi",
            )
        ],
    )
    resolved = ResolvedSession(
        session=session,
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/dotfiles",
            display_name="Dotfiles",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="stub",
        ),
    )
    _stub_scan_service(
        monkeypatch,
        ScanResult(
            period=DateRange(
                since=datetime(2026, 7, 20, 0, 0, tzinfo=tz),
                until=datetime(2026, 7, 27, 0, 0, tzinfo=tz),
            ),
            candidate_session_count=1,
            loaded_session_count=1,
            failed_session_count=0,
            resolved_sessions=[resolved],
            sessions_by_repository={"git:github.com/mike/dotfiles": [resolved]},
            warnings=[],
            excluded_session_count=0,
        ),
    )
    return cli


def test_scan_json_flag_emits_parsable_json(monkeypatch) -> None:
    import json

    cli = _stub_scan(monkeypatch)

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["loaded_session_count"] == 1
    assert payload["repositories"][0]["sessions"][0]["title"] == "Tune dotfiles"


def test_scan_emits_json_automatically_when_stdout_is_piped(monkeypatch) -> None:
    import json

    cli = _stub_scan(monkeypatch)

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["repositories"][0]["name"] == "Dotfiles"


def test_scan_no_json_forces_the_human_table_when_piped(monkeypatch) -> None:
    cli = _stub_scan(monkeypatch)

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7", "--no-json"])

    assert result.exit_code == 0
    assert "Dotfiles" in result.stdout
    assert result.stdout.strip().startswith("{" ) is False


def test_doctor_json_flag_emits_machine_readable_output(monkeypatch) -> None:
    import json

    import iiwi.cli as cli
    from iiwi.services.doctor import DoctorCheck, DoctorResult

    monkeypatch.setattr(
        cli,
        "run_doctor",
        lambda settings, runner, harness: DoctorResult(
            checks=[DoctorCheck(name="git", ok=True, detail="git version 2.47.0")]
        ),
    )

    result = CliRunner().invoke(cli.app, ["doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["harness"] == "opencode"
    assert payload["ok"] is True
    assert payload["checks"][0]["name"] == "git"


def test_json_and_quiet_are_rejected_together(monkeypatch) -> None:
    cli = _stub_scan(monkeypatch)

    result = CliRunner().invoke(cli.app, ["scan", "--days", "7", "--json", "--quiet"])

    assert result.exit_code == 2


def _seed_history(monkeypatch, tmp_path) -> Path:
    """Point the history log at a temp file holding one entry, and return it."""
    from datetime import datetime
    from pathlib import Path
    from zoneinfo import ZoneInfo

    import iiwi.history as history

    path = tmp_path / "history.jsonl"
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(path))
    history.append_history(
        history.HistoryEntry(
            generated_at=datetime(2026, 8, 3, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            harness="opencode",
            since=datetime(2026, 7, 27, 0, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            until=datetime(2026, 8, 3, 0, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            output_path=Path("reports/worklog.md"),
            repository_count=2,
            session_count=10,
            narrative=True,
            detail="full",
        ),
        path=path,
    )
    return path


def test_history_json_flag_emits_entries(monkeypatch, tmp_path) -> None:
    import json

    import iiwi.cli as cli

    _seed_history(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli.app, ["history", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["harness"] == "opencode"
    assert payload[0]["repository_count"] == 2
    assert payload[0]["session_count"] == 10
    assert payload[0]["narrative"] is True
    assert payload[0]["output_path"] == str(Path("reports/worklog.md").resolve())


def test_history_emits_json_automatically_when_piped(monkeypatch, tmp_path) -> None:
    import json

    import iiwi.cli as cli

    _seed_history(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli.app, ["history"])

    assert result.exit_code == 0
    assert isinstance(json.loads(result.stdout), list)


def test_history_empty_file_prints_a_message(monkeypatch, tmp_path) -> None:
    import iiwi.cli as cli

    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))

    result = CliRunner().invoke(cli.app, ["history", "--no-json"])

    assert result.exit_code == 0
    assert "No reports" in result.stdout


def test_report_records_a_history_entry_after_writing(monkeypatch, tmp_path) -> None:
    from datetime import datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    import iiwi.cli as cli
    import iiwi.history as history
    from iiwi.models.report import RepositorySummary, WorklogReport

    history_path = tmp_path / "history.jsonl"
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(history_path))

    class StubReportService:
        def __init__(self, output_path, period) -> None:
            self.output_path = output_path
            self.period = period

        def generate(self, *, force: bool = False, dry_run: bool = False):
            return SimpleNamespace(
                output_path=self.output_path,
                content="# Engineering Worklog\n",
                report=WorklogReport(
                    generated_at=datetime(2026, 8, 3, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
                    period=self.period,
                    repositories=[
                        RepositorySummary(
                            repository_id="repo-a",
                            display_name="repo-a",
                        )
                    ],
                ),
                scan=SimpleNamespace(
                    loaded_session_count=4,
                    excluded_session_count=0,
                    failed_session_count=0,
                ),
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

    result = CliRunner().invoke(
        cli.app,
        ["report", "--days", "7", "--no-llm", "--output", str(tmp_path / "report.md")],
    )

    assert result.exit_code == 0
    entries = history.read_history(path=history_path)
    assert len(entries) == 1
    assert entries[0].harness == "opencode"
    assert entries[0].session_count == 4
    assert entries[0].narrative is False
    assert str(entries[0].output_path) == str(tmp_path / "report.md")


def _stub_update(monkeypatch, info):
    """Point the `update` command's check seam at a canned result."""
    import iiwi.cli as cli

    monkeypatch.setattr(
        cli,
        "check_for_update",
        lambda **kwargs: info,
    )
    return cli


def test_update_json_flag_emits_machine_readable_output(monkeypatch) -> None:
    import json

    from iiwi.update import UpdateInfo

    cli = _stub_update(
        monkeypatch,
        UpdateInfo(
            current="0.8.0",
            latest="0.9.0",
            update_available=True,
            upgrade_command="pipx upgrade iiwi",
        ),
    )

    result = CliRunner().invoke(cli.app, ["update", "--json"])

    assert result.exit_code == 8
    payload = json.loads(result.stdout)
    assert payload["current"] == "0.8.0"
    assert payload["latest"] == "0.9.0"
    assert payload["update_available"] is True
    assert payload["upgrade_command"] == "pipx upgrade iiwi"


def test_update_emits_json_automatically_when_piped(monkeypatch) -> None:
    import json

    from iiwi.update import UpdateInfo

    cli = _stub_update(
        monkeypatch,
        UpdateInfo(
            current="0.9.0",
            latest="0.9.0",
            update_available=False,
            upgrade_command="pipx upgrade iiwi",
        ),
    )

    result = CliRunner().invoke(cli.app, ["update"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["update_available"] is False


def test_update_reports_upgrade_command_when_behind(monkeypatch) -> None:
    from iiwi.update import UpdateInfo

    cli = _stub_update(
        monkeypatch,
        UpdateInfo(
            current="0.8.0",
            latest="0.9.0",
            update_available=True,
            upgrade_command="pipx upgrade iiwi",
        ),
    )

    result = CliRunner().invoke(cli.app, ["update", "--no-json"])

    assert result.exit_code == 8
    assert "0.9.0" in result.stdout
    assert "pipx upgrade iiwi" in result.stdout


def test_update_says_up_to_date(monkeypatch) -> None:
    from iiwi.update import UpdateInfo

    cli = _stub_update(
        monkeypatch,
        UpdateInfo(
            current="0.9.0",
            latest="0.9.0",
            update_available=False,
            upgrade_command="pipx upgrade iiwi",
        ),
    )

    result = CliRunner().invoke(cli.app, ["update", "--no-json"])

    assert result.exit_code == 0
    assert "up to date" in result.stdout


def test_update_network_failure_is_not_an_error(monkeypatch) -> None:
    import iiwi.cli as cli
    from iiwi.update import UpdateCheckError

    def fail(**kwargs):
        raise UpdateCheckError("could not reach the version index: connection refused")

    monkeypatch.setattr(cli, "check_for_update", fail)

    result = CliRunner().invoke(cli.app, ["update", "--no-json"])

    assert result.exit_code == 0
    assert "could not reach" in result.stdout


def test_version_flag_prints_the_installed_version() -> None:
    import iiwi

    result = CliRunner().invoke(iiwi.cli.app, ["--version"])

    assert result.exit_code == 0
    assert f"iiwi {iiwi.__version__}" in result.stdout
