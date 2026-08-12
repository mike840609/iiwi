from __future__ import annotations

from pathlib import Path

import pytest

from iiwi import config_store
from iiwi.errors import ConfigurationError
from iiwi.interactive.settings import (
    TIMEZONE_CHOICES,
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
    monkeypatch.delenv("IIWI_REPORT__TIMEZONE", raising=False)
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS", raising=False)
    return path


def _row(**overrides: object) -> SettingsRow:
    fields = dict(
        key="report.timezone",
        label="timezone",
        value="Asia/Taipei",
        source="default",
        default="Asia/Taipei",
        choices=TIMEZONE_CHOICES,
        show_all=False,
        locked=False,
        variable="IIWI_REPORT__TIMEZONE",
    )
    fields.update(overrides)
    return SettingsRow(**fields)


def test_choices_follow_each_setting_annotation() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.enabled"].choices == ("true", "false")
    assert rows["harnesses.opencode.cli.sanitize"].choices == ("true", "false")
    assert rows["report.quick_review_report_type"].choices == (
        tuple(member.value for member in ReportType)
    )
    assert rows["harnesses.opencode.source"].choices == ("cli",)
    assert rows["report.timezone"].choices == TIMEZONE_CHOICES
    assert rows["harnesses.opencode.cli.model"].choices == ()
    assert rows["harnesses.opencode.cli.model"].show_all is False


def test_choice_rows_show_all_and_timezone_does_not() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.enabled"].show_all is True
    assert rows["report.quick_review_report_type"].show_all is True
    assert rows["report.timezone"].show_all is False
    assert rows["report.timezone"].editable is True
    assert rows["harnesses.opencode.enabled"].editable is False


def test_labels_strip_the_harnesses_prefix() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.cli.executable"].label == "opencode.cli.executable"
    assert rows["report.timezone"].label == "report.timezone"


def test_environment_sourced_rows_are_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IIWI_REPORT__TIMEZONE", "UTC")
    rows = {row.key: row for row in build_settings_rows()}
    timezone = rows["report.timezone"]
    assert timezone.value == "UTC"
    assert timezone.locked is True
    assert timezone.variable == "IIWI_REPORT__TIMEZONE"


def test_file_sourced_rows_are_not_locked(config_file: Path) -> None:
    config_store.set_value("report.timezone", "Europe/Berlin")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["report.timezone"].source == "file"
    assert rows["report.timezone"].locked is False


def test_next_choice_wraps_at_both_ends() -> None:
    row = _row()
    assert next_choice(row, "Asia/Taipei", right=True) == "Asia/Shanghai"
    assert next_choice(row, "UTC", right=True) == "Asia/Taipei"
    assert next_choice(row, "Asia/Taipei", right=False) == "UTC"


def test_next_choice_steps_off_an_out_of_list_value() -> None:
    row = _row(value="Europe/Paris")
    assert next_choice(row, "Europe/Paris", right=True) == "Asia/Taipei"
    assert next_choice(row, "Europe/Paris", right=False) == "UTC"


def test_next_choice_is_a_noop_without_choices() -> None:
    row = _row(choices=())
    assert next_choice(row, "anything", right=True) == "anything"


def test_write_setting_persists_a_value(config_file: Path) -> None:
    write_setting("report.timezone", "Europe/Berlin")
    assert config_store.stored_values(config_file) == {
        "IIWI_REPORT__TIMEZONE": "Europe/Berlin"
    }


def test_write_setting_empty_restores_the_default(config_file: Path) -> None:
    write_setting("report.timezone", "Europe/Berlin")
    write_setting("report.timezone", "")
    assert config_store.stored_values(config_file) == {}


def test_write_setting_rejects_an_invalid_value(config_file: Path) -> None:
    with pytest.raises(ConfigurationError):
        write_setting("harnesses.opencode.cli.timeout_seconds", "abc")
    assert not config_file.exists()
