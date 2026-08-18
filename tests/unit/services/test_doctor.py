import shutil

from iiwi.config import AppSettings
from iiwi.process import CommandResult
from iiwi.services import doctor
from iiwi.services.doctor import NarratorDescription, run_doctor

_NARRATOR = NarratorDescription(
    provider="opencode", executable="opencode", source="--harness opencode"
)


def test_doctor_checks_opencode_version_db_path_and_git(monkeypatch, fake_runner) -> None:
    fake_runner.set_output("opencode --version", "1.0.0\n")
    fake_runner.set_output("opencode db path", "/tmp/opencode.db\n")
    fake_runner.set_output("git --version", "git version 2.47\n")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")

    result = run_doctor(AppSettings(), runner=fake_runner, narrator=_NARRATOR)

    assert result.ok is True
    assert fake_runner.calls == [
        ["opencode", "--version"],
        ["opencode", "db", "path"],
        ["git", "--version"],
    ]
    assert all(check.ok for check in result.checks)


def test_doctor_reports_a_timed_out_check_instead_of_crashing(
    monkeypatch, fake_runner
) -> None:
    """`CommandRunner` reports timeouts as failed results rather than raising."""

    fake_runner.set_result(
        "opencode db path",
        CommandResult(
            returncode=124,
            stdout="",
            stderr="opencode timed out after 30.0 seconds",
        ),
    )
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")

    result = run_doctor(AppSettings(), runner=fake_runner, narrator=_NARRATOR)

    assert result.ok is False
    database_check = next(
        check for check in result.checks if check.name == "opencode database"
    )
    assert database_check.ok is False
    assert "timed out" in database_check.detail


def test_doctor_skips_opencode_checks_for_claude_code(monkeypatch, tmp_path) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args: list[str]) -> CommandResult:
            self.calls.append(args)
            return CommandResult(0, "git version 2.0.0", "")

    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path
    runner = RecordingRunner()
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")

    result = run_doctor(
        settings, runner=runner, harness="claude-code", narrator=_NARRATOR
    )

    assert result.ok
    assert all(call[0] != "opencode" for call in runner.calls)
    assert any("claude code projects" in check.name for check in result.checks)


def test_doctor_fails_when_the_projects_directory_is_missing(tmp_path) -> None:
    class GitOnlyRunner:
        def run(self, args: list[str]) -> CommandResult:
            return CommandResult(0, "git version 2.0.0", "")

    settings = AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path / "absent"

    result = run_doctor(
        settings, runner=GitOnlyRunner(), harness="claude-code", narrator=_NARRATOR
    )

    assert not result.ok


def test_codex_doctor_reports_the_home_directory_and_discovery_path(
    tmp_path, monkeypatch, fake_runner
) -> None:
    monkeypatch.setenv(
        "IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path)
    )
    (tmp_path / "state_5.sqlite").write_text("", encoding="utf-8")
    settings = AppSettings()

    result = run_doctor(
        settings, runner=fake_runner, harness="codex", narrator=_NARRATOR
    )

    check = result.checks[0]
    assert check.name == "codex home directory"
    assert check.ok is True
    assert check.detail == f"{tmp_path} (state_5.sqlite)"


def test_codex_doctor_fails_on_a_missing_home_directory(
    tmp_path, monkeypatch, fake_runner
) -> None:
    monkeypatch.setenv(
        "IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent")
    )
    settings = AppSettings()

    result = run_doctor(
        settings, runner=fake_runner, harness="codex", narrator=_NARRATOR
    )

    assert result.checks[0].ok is False


def test_doctor_reports_a_resolved_narrator(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/claude")
    description = NarratorDescription(
        provider="claude", executable="claude", source="--harness claude-code"
    )

    check = doctor._narrator_check(description)

    assert check.ok is True
    assert "claude" in check.detail
    assert "--harness claude-code" in check.detail


def test_doctor_reports_a_missing_narrator_binary(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    description = NarratorDescription(
        provider="codex", executable="codex", source="--harness codex"
    )

    check = doctor._narrator_check(description)

    assert check.ok is False
    assert "codex" in check.detail
    assert "narrator.executable" in check.detail


def test_doctor_points_codex_desktop_users_at_the_documentation(
    monkeypatch, tmp_path
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    monkeypatch.setattr(shutil, "which", lambda name: None)
    description = NarratorDescription(
        provider="codex", executable="codex", source="--harness codex"
    )

    check = doctor._narrator_check(description, codex_home=codex_home)

    assert "docs/configuration.md" in check.detail
