from __future__ import annotations

from pathlib import Path

import pytest

from iiwi import config_store
from iiwi.errors import ConfigurationError
from iiwi.interactive.settings import (
    SettingsRow,
    build_settings_rows,
    next_choice,
    write_setting,
)
from iiwi.models.report_options import ReportType


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_REPORT__OUTPUT_DIRECTORY", raising=False)
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS", raising=False)
    return path


def _row(**overrides: object) -> SettingsRow:
    fields = dict(
        key="harnesses.opencode.cli.timeout_seconds",
        label="opencode.cli.timeout_seconds",
        value="30",
        source="default",
        default="30",
        choices=("15", "30", "60", "120"),
        show_all=False,
        locked=False,
        variable="IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS",
    )
    fields.update(overrides)
    return SettingsRow(**fields)


def test_sections_group_each_setting() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.enabled"].section == "OpenCode"
    assert rows["harnesses.opencode.cli.model"].section == "OpenCode"
    assert rows["harnesses.claude_code.enabled"].section == "Claude Code"
    assert rows["harnesses.claude_code.projects_directory"].section == "Claude Code"
    assert rows["harnesses.codex.enabled"].section == "Codex"
    assert rows["harnesses.codex.home_directory"].section == "Codex"
    assert rows["report.output_directory"].section == "General"
    assert rows["report.quick_review_max_evidence_bytes"].section == "General"


def test_choices_follow_each_setting_annotation() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.enabled"].choices == ("true", "false")
    assert rows["harnesses.opencode.cli.sanitize"].choices == ("true", "false")
    assert rows["report.quick_review_report_type"].choices == (
        tuple(member.value for member in ReportType)
    )
    assert rows["harnesses.opencode.source"].choices == ("cli",)
    assert rows["harnesses.opencode.cli.timeout_seconds"].choices == ("15", "30", "60", "120")
    assert rows["harnesses.opencode.cli.model"].choices == ()
    assert rows["harnesses.opencode.cli.model"].show_all is False


def test_choice_rows_show_all_and_timezone_does_not() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.enabled"].show_all is True
    assert rows["report.quick_review_report_type"].show_all is True
    assert rows["harnesses.opencode.cli.timeout_seconds"].show_all is False
    assert rows["harnesses.opencode.cli.timeout_seconds"].editable is True
    assert rows["harnesses.opencode.enabled"].editable is False


def test_labels_strip_the_harnesses_prefix() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.cli.executable"].label == "opencode.cli.executable"
    assert rows["report.output_directory"].label == "report.output_directory"


def test_environment_sourced_rows_are_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IIWI_REPORT__OUTPUT_DIRECTORY", "/tmp/out")
    rows = {row.key: row for row in build_settings_rows()}
    row = rows["report.output_directory"]
    assert row.locked is True
    assert row.variable == "IIWI_REPORT__OUTPUT_DIRECTORY"


def test_file_sourced_rows_are_not_locked(config_file: Path) -> None:
    config_store.set_value("report.output_directory", "/tmp/out")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["report.output_directory"].source == "file"
    assert rows["report.output_directory"].locked is False


def test_next_choice_wraps_at_both_ends() -> None:
    row = _row()
    assert next_choice(row, "15", right=True) == "30"
    assert next_choice(row, "120", right=True) == "15"
    assert next_choice(row, "15", right=False) == "120"


def test_next_choice_steps_off_an_out_of_list_value() -> None:
    row = _row(value="999")
    assert next_choice(row, "999", right=True) == "15"
    assert next_choice(row, "999", right=False) == "120"


def test_next_choice_is_a_noop_without_choices() -> None:
    row = _row(choices=())
    assert next_choice(row, "anything", right=True) == "anything"


def test_write_setting_persists_a_value(config_file: Path) -> None:
    write_setting("report.output_directory", "/tmp/out")
    assert config_store.stored_values(config_file) == {
        "IIWI_REPORT__OUTPUT_DIRECTORY": "/tmp/out"
    }


def test_write_setting_empty_restores_the_default(config_file: Path) -> None:
    write_setting("report.output_directory", "/tmp/out")
    write_setting("report.output_directory", "")
    assert config_store.stored_values(config_file) == {}


def test_write_setting_rejects_an_invalid_value(config_file: Path) -> None:
    with pytest.raises(ConfigurationError):
        write_setting("harnesses.opencode.cli.timeout_seconds", "abc")
    assert not config_file.exists()


def test_a_disabled_harness_mutes_its_other_rows(config_file: Path) -> None:
    config_store.set_value("harnesses.claude_code.enabled", "false")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.claude_code.projects_directory"].disabled_reason == (
        "Claude Code is disabled; enable harnesses.claude_code.enabled"
        " to make this take effect."
    )


def test_the_enabled_row_itself_is_never_disabled(config_file: Path) -> None:
    config_store.set_value("harnesses.claude_code.enabled", "false")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.claude_code.enabled"].disabled_reason == ""


def test_disabling_opencode_reaches_its_nested_cli_rows(config_file: Path) -> None:
    config_store.set_value("harnesses.opencode.enabled", "false")
    rows = {row.key: row for row in build_settings_rows()}
    reason = rows["harnesses.opencode.cli.executable"].disabled_reason
    assert reason.startswith("OpenCode is disabled;")


def test_non_harness_rows_are_never_disabled(config_file: Path) -> None:
    config_store.set_value("harnesses.claude_code.enabled", "false")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["report.output_directory"].disabled_reason == ""


def test_no_row_is_disabled_while_every_harness_is_enabled() -> None:
    assert all(row.disabled_reason == "" for row in build_settings_rows())


def test_hybrid_preset_choices_are_exposed() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.cli.timeout_seconds"].choices == ("15", "30", "60", "120")
    assert rows["harnesses.opencode.cli.run_timeout_seconds"].choices == ("300", "600", "1200")
    assert rows["narrator.timeout_seconds"].choices == ("300", "600", "1200")
    assert rows["report.quick_review_max_evidence_bytes"].choices == ("20000", "40000", "80000")
    assert rows["narrator.provider"].choices == ("", "claude", "codex")


def test_hybrid_rows_are_editable_and_not_inline() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    for key in (
        "harnesses.opencode.cli.timeout_seconds",
        "harnesses.opencode.cli.run_timeout_seconds",
        "narrator.timeout_seconds",
        "report.quick_review_max_evidence_bytes",
        "narrator.provider",
    ):
        assert rows[key].show_all is False, key
        assert rows[key].editable is True, key
    # Closed sets stay inline
    assert rows["harnesses.opencode.enabled"].show_all is True
    assert rows["report.quick_review_report_type"].show_all is True
    assert rows["harnesses.opencode.source"].show_all is True
    # Free-text stays with no choices
    assert rows["harnesses.opencode.cli.executable"].choices == ()
    assert rows["narrator.model"].choices == ()
    assert rows["report.exclude_repositories"].choices == ()


def test_float_value_canonicalization_matches_presets(config_file: Path) -> None:
    # Stored as float string with .0
    write_setting("harnesses.opencode.cli.timeout_seconds", "30.0")
    rows = {row.key: row for row in build_settings_rows()}
    row = rows["harnesses.opencode.cli.timeout_seconds"]
    assert row.value == "30"
    assert next_choice(row, row.value, right=True) == "60"
    assert next_choice(row, row.value, right=False) == "15"


def test_narrator_provider_empty_cycles_and_unsets(config_file: Path) -> None:
    rows = {row.key: row for row in build_settings_rows()}
    row = rows["narrator.provider"]
    # From empty, right goes to first preset claude (out-of-list lands on nearest end is 0)
    assert next_choice(row, "", right=True) == "claude"
    assert next_choice(row, "", right=False) == "codex"
    # Writing empty unsets
    write_setting("narrator.provider", "claude")
    write_setting("narrator.provider", "")
    assert config_store.stored_values(config_file) == {}
