from iiwi.config import AppSettings
from iiwi.process import CommandResult
from iiwi.services.doctor import run_doctor


def test_doctor_checks_opencode_version_db_path_and_git(fake_runner) -> None:
    fake_runner.set_output("opencode --version", "1.0.0\n")
    fake_runner.set_output("opencode db path", "/tmp/opencode.db\n")
    fake_runner.set_output("git --version", "git version 2.47\n")

    result = run_doctor(AppSettings(), runner=fake_runner)

    assert result.ok is True
    assert fake_runner.calls == [
        ["opencode", "--version"],
        ["opencode", "db", "path"],
        ["git", "--version"],
    ]
    assert all(check.ok for check in result.checks)


def test_doctor_reports_a_timed_out_check_instead_of_crashing(fake_runner) -> None:
    """`CommandRunner` reports timeouts as failed results rather than raising."""

    fake_runner.set_result(
        "opencode db path",
        CommandResult(
            returncode=124,
            stdout="",
            stderr="opencode timed out after 30.0 seconds",
        ),
    )

    result = run_doctor(AppSettings(), runner=fake_runner)

    assert result.ok is False
    database_check = next(
        check for check in result.checks if check.name == "opencode database"
    )
    assert database_check.ok is False
    assert "timed out" in database_check.detail


def test_doctor_skips_opencode_checks_for_claude_code(tmp_path) -> None:
    from iiwi.config import AppSettings
    from iiwi.services.doctor import run_doctor

    class RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args: list[str]) -> CommandResult:
            self.calls.append(args)
            return CommandResult(0, "git version 2.0.0", "")

    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path
    runner = RecordingRunner()

    result = run_doctor(settings, runner=runner, harness="claude-code")

    assert result.ok
    assert all(call[0] != "opencode" for call in runner.calls)
    assert any("claude code projects" in check.name for check in result.checks)


def test_doctor_fails_when_the_projects_directory_is_missing(tmp_path) -> None:
    from iiwi.config import AppSettings
    from iiwi.services.doctor import run_doctor

    class GitOnlyRunner:
        def run(self, args: list[str]) -> CommandResult:
            return CommandResult(0, "git version 2.0.0", "")

    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path / "absent"

    result = run_doctor(settings, runner=GitOnlyRunner(), harness="claude-code")

    assert not result.ok


def test_codex_doctor_reports_the_home_directory_and_discovery_path(
    tmp_path, monkeypatch, fake_runner
) -> None:
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path)
    )
    (tmp_path / "state_5.sqlite").write_text("", encoding="utf-8")
    settings = AppSettings()

    result = run_doctor(settings, runner=fake_runner, harness="codex")

    check = result.checks[0]
    assert check.name == "codex home directory"
    assert check.ok is True
    assert check.detail == f"{tmp_path} (state_5.sqlite)"


def test_codex_doctor_fails_on_a_missing_home_directory(
    tmp_path, monkeypatch, fake_runner
) -> None:
    monkeypatch.setenv(
        "AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent")
    )
    settings = AppSettings()

    result = run_doctor(settings, runner=fake_runner, harness="codex")

    assert result.checks[0].ok is False
