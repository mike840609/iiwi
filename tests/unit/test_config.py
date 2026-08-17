from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from iiwi import config_store
from iiwi.cli import app
from iiwi.config import AppSettings, OpenCodeCliSettings, ReportSettings
from iiwi.models.report_options import ReportType


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


def test_quick_review_report_type_defaults_to_manager() -> None:
    settings = AppSettings()

    assert settings.report.quick_review_report_type is ReportType.MANAGER


def test_quick_review_evidence_budget_defaults_and_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert AppSettings().report.quick_review_max_evidence_bytes == 40000

    monkeypatch.setenv("IIWI_REPORT__QUICK_REVIEW_MAX_EVIDENCE_BYTES", "12000")

    assert AppSettings().report.quick_review_max_evidence_bytes == 12000


def test_quick_review_report_type_is_configurable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE",
        "engineering",
    )

    settings = AppSettings()

    assert settings.report.quick_review_report_type is ReportType.ENGINEERING


def test_quick_review_report_type_is_listable_settable_and_unsettable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    runner = CliRunner()

    listed = runner.invoke(app, ["config", "list"])
    assert listed.exit_code == 0
    assert "report.quick_review_" in listed.stdout
    assert "report_type" in listed.stdout
    listed_setting = next(
        row
        for row in config_store.describe_settings(path)
        if row.key == "report.quick_review_report_type"
    )
    assert (listed_setting.value, listed_setting.source, listed_setting.default) == (
        "manager",
        "default",
        "manager",
    )

    written = runner.invoke(
        app,
        ["config", "set", "report.quick_review_report_type", "engineering"],
    )
    assert written.exit_code == 0
    assert config_store.stored_values(path) == {
        "IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE": "engineering"
    }

    removed = runner.invoke(
        app,
        ["config", "unset", "report.quick_review_report_type"],
    )
    assert removed.exit_code == 0
    assert config_store.stored_values(path) == {}


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


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), 0.0, -5.0],
)
def test_opencode_cli_timeout_seconds_rejects_non_finite_or_non_positive_values(
    value: float,
) -> None:
    with pytest.raises(ValidationError):
        OpenCodeCliSettings(timeout_seconds=value)


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), 0.0, -5.0],
)
def test_opencode_cli_run_timeout_seconds_rejects_non_finite_or_non_positive_values(
    value: float,
) -> None:
    with pytest.raises(ValidationError):
        OpenCodeCliSettings(run_timeout_seconds=value)


@pytest.mark.parametrize(
    "value",
    [30.0, 600.0, 0.5, 120.5],
)
def test_opencode_cli_timeout_accepts_finite_strictly_positive_values(
    value: float,
) -> None:
    assert OpenCodeCliSettings(timeout_seconds=value).timeout_seconds == value
    assert OpenCodeCliSettings(run_timeout_seconds=value).run_timeout_seconds == value


def test_report_timezone_rejects_an_unknown_zone() -> None:
    with pytest.raises(ValidationError, match="unknown timezone"):
        ReportSettings(timezone="Mars/Olympus")


@pytest.mark.parametrize("timezone", ["UTC", "America/New_York", "Asia/Taipei"])
def test_report_timezone_accepts_known_zones(timezone: str) -> None:
    assert ReportSettings(timezone=timezone).timezone == timezone


@pytest.mark.parametrize("value", [0, -1, -40000, 999])
def test_quick_review_evidence_budget_rejects_values_under_one_session(
    value: int,
) -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1000"):
        ReportSettings(quick_review_max_evidence_bytes=value)


@pytest.mark.parametrize("value", [1000, 12000, 40000])
def test_quick_review_evidence_budget_accepts_a_budget_one_session_fits_in(
    value: int,
) -> None:
    settings = ReportSettings(quick_review_max_evidence_bytes=value)

    assert settings.quick_review_max_evidence_bytes == value
