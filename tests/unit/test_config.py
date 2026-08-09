from pathlib import Path

import pytest

from iiwi.config import AppSettings


def test_settings_use_opencode_cli_and_taipei_defaults() -> None:
    settings = AppSettings()

    assert settings.harnesses.opencode.source == "cli"
    assert settings.harnesses.opencode.cli.executable == "opencode"
    assert settings.report.timezone == "Asia/Taipei"
    assert settings.report.output_directory == Path("reports")


def test_opencode_run_timeout_and_model_defaults() -> None:
    settings = AppSettings()

    assert settings.harnesses.opencode.cli.run_timeout_seconds == 600.0
    assert settings.harnesses.opencode.cli.model == ""


def test_report_exclude_repositories_defaults_to_empty() -> None:
    settings = AppSettings()

    assert settings.report.exclude_repositories == ""


def test_report_exclude_repositories_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "IIWI_REPORT__EXCLUDE_REPOSITORIES",
        "dotfiles,  notes-vault",
    )

    settings = AppSettings()

    assert settings.report.exclude_repositories == "dotfiles,  notes-vault"


def test_excluded_repository_ids_parses_whitespace_and_empty_entries() -> None:
    settings = AppSettings()
    settings.report.exclude_repositories = " dotfiles , , notes-vault ,"

    assert settings.report.excluded_repository_ids() == ("dotfiles", "notes-vault")


def test_excluded_repository_ids_of_an_empty_setting_is_empty() -> None:
    settings = AppSettings()

    assert settings.report.excluded_repository_ids() == ()


def test_opencode_run_timeout_and_model_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS",
        "120.0",
    )
    monkeypatch.setenv(
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL",
        "gpt-5.3",
    )

    settings = AppSettings()

    assert settings.harnesses.opencode.cli.run_timeout_seconds == 120.0
    assert settings.harnesses.opencode.cli.model == "gpt-5.3"


def test_claude_code_projects_directory_defaults_under_home() -> None:
    from pathlib import Path

    from iiwi.config import AppSettings

    settings = AppSettings()

    assert settings.harnesses.claude_code.projects_directory == (
        Path.home() / ".claude" / "projects"
    )


def test_claude_code_projects_directory_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from iiwi.config import AppSettings

    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY",
        "/tmp/claude-projects",
    )

    settings = AppSettings()

    assert settings.harnesses.claude_code.projects_directory == Path("/tmp/claude-projects")


def test_codex_defaults_to_the_user_codex_home() -> None:
    settings = AppSettings()

    assert settings.harnesses.codex.enabled is True
    assert settings.harnesses.codex.home_directory == Path.home() / ".codex"


def test_codex_home_directory_is_configurable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "codex")
    )

    settings = AppSettings()

    assert settings.harnesses.codex.home_directory == tmp_path / "codex"


def test_every_harness_enum_member_has_settings_field_with_enabled() -> None:
    """
    Verify that every Harness enum member resolves to a settings field on
    HarnessSettings with an `enabled` attribute.

    This ensures that cli.py's reflective lookup—getattr(settings.harnesses,
    harness.name.lower()).enabled—will not raise AttributeError. If a new
    Harness enum member is added without a corresponding HarnessSettings field,
    this test catches it before a user sees an uncaught traceback.
    """
    from iiwi.cli import Harness

    settings = AppSettings()

    for harness in Harness:
        field_name = harness.name.lower()
        # Verify the field exists on HarnessSettings
        assert hasattr(settings.harnesses, field_name), (
            f"HarnessSettings missing field '{field_name}' for Harness.{harness.name}"
        )
        # Verify the field has an `enabled` attribute
        field_value = getattr(settings.harnesses, field_name)
        assert hasattr(field_value, "enabled"), (
            f"HarnessSettings.{field_name} missing `enabled` attribute"
        )

def test_old_environment_prefix_is_not_consumed(monkeypatch: pytest.MonkeyPatch) -> None:
    old_name = "AGENT_" + "WORKLOG_REPORT__TIMEZONE"
    monkeypatch.setenv(old_name, "UTC")
    monkeypatch.delenv("IIWI_REPORT__TIMEZONE", raising=False)

    settings = AppSettings()

    assert settings.report.timezone == "Asia/Taipei"
