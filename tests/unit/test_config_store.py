import os
import sys
from pathlib import Path

import pytest

from iiwi.config_store import (
    CONFIG_FILE_VARIABLE,
    config_file_path,
    describe_settings,
    resolve_key,
    set_value,
    setting_keys,
    stored_values,
    unset_value,
    validate_value,
)
from iiwi.errors import ConfigurationError

# chmod-based permission denial does not bite on Windows, and root ignores
# file-permission bits entirely, so both would make these tests spuriously
# fail to reproduce the OSError they exist to catch.
_PERMISSIONS_DO_NOT_APPLY = sys.platform.startswith("win") or (
    hasattr(os, "geteuid") and os.geteuid() == 0
)
skip_unless_permissions_enforced = pytest.mark.skipif(
    _PERMISSIONS_DO_NOT_APPLY,
    reason="chmod-based permission denial does not apply on Windows or as root",
)


def test_setting_keys_cover_the_leaves_of_the_settings_tree() -> None:
    keys = {setting.key: setting for setting in setting_keys()}

    assert keys["harnesses.opencode.cli.model"].variable == (
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL"
    )
    assert keys["harnesses.opencode.cli.model"].default == ""
    assert keys["harnesses.opencode.cli.executable"].variable == (
        "IIWI_HARNESSES__OPENCODE__CLI__EXECUTABLE"
    )
    # A container is a path to settings, not a setting.
    assert "harnesses" not in keys
    assert "harnesses.opencode.cli" not in keys


def test_setting_keys_include_the_report_exclude_repositories_leaf() -> None:
    keys = {setting.key: setting for setting in setting_keys()}

    assert keys["report.exclude_repositories"].variable == (
        "IIWI_REPORT__EXCLUDE_REPOSITORIES"
    )
    assert keys["report.exclude_repositories"].default == ""


def test_setting_key_defaults_are_rendered_the_way_a_user_types_them() -> None:
    keys = {setting.key: setting for setting in setting_keys()}

    assert keys["harnesses.codex.enabled"].default == "true"
    assert keys["harnesses.claude_code.projects_directory"].default == str(
        Path.home() / ".claude" / "projects"
    )
    assert keys["harnesses.opencode.cli.run_timeout_seconds"].default == "600.0"


def test_config_file_path_follows_an_explicit_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "custom.env"))

    assert config_file_path() == tmp_path / "custom.env"


def test_config_file_path_defaults_into_the_user_config_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IIWI_CONFIG_FILE", raising=False)

    path = config_file_path()

    assert path.name == "config.env"
    assert "iiwi" in str(path)


@pytest.mark.parametrize(
    ("module", "resolver", "directory_function", "variable", "filename"),
    [
        (
            "iiwi.config_store",
            "config_file_path",
            "user_config_dir",
            "IIWI_CONFIG_FILE",
            "config.env",
        ),
        (
            "iiwi.history",
            "history_file_path",
            "user_data_dir",
            "IIWI_HISTORY_FILE",
            "history.jsonl",
        ),
        (
            "iiwi.state",
            "state_file_path",
            "user_data_dir",
            "IIWI_STATE_FILE",
            "state.json",
        ),
    ],
)
def test_a_legacy_decoy_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module: str,
    resolver: str,
    directory_function: str,
    variable: str,
    filename: str,
) -> None:
    """A file under the pre-rename directory is left untouched, never adopted.

    The autouse fixture sets the override, so clear it to reach the real branch.
    """

    import importlib

    monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        importlib.import_module(module),
        directory_function,
        lambda name: str(tmp_path / name),
    )
    decoy = tmp_path / "agent-worklog" / filename
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text("kept\n", encoding="utf-8")

    resolved = getattr(importlib.import_module(module), resolver)()

    assert resolved == tmp_path / "iiwi" / filename
    assert decoy.exists()
    assert decoy.read_text(encoding="utf-8") == "kept\n"


def test_resolve_key_suggests_the_closest_key_for_a_typo() -> None:
    with pytest.raises(ConfigurationError) as error:
        resolve_key("harnesses.opencode.cli.mdoel")

    assert "did you mean harnesses.opencode.cli.model" in str(error.value)


def test_resolve_key_rejects_a_key_with_no_close_match() -> None:
    with pytest.raises(ConfigurationError, match="unknown setting: nope.at.all"):
        resolve_key("nope.at.all")


def test_validate_value_rejects_a_timeout_that_is_not_a_number() -> None:
    with pytest.raises(
        ConfigurationError, match="invalid value for harnesses.opencode.cli.run_timeout_seconds"
    ):
        validate_value(resolve_key("harnesses.opencode.cli.run_timeout_seconds"), "abc")


def test_validate_value_accepts_the_boolean_spellings_env_settings_use() -> None:
    validate_value(resolve_key("harnesses.opencode.enabled"), "false")
    validate_value(resolve_key("harnesses.codex.enabled"), "true")


@pytest.mark.parametrize(
    "value",
    ["nan", "inf", "-inf", "0", "-5"],
)
def test_validate_value_rejects_a_non_finite_or_non_positive_timeout(
    value: str,
) -> None:
    with pytest.raises(
        ConfigurationError,
        match="invalid value for harnesses.opencode.cli.timeout_seconds",
    ):
        validate_value(resolve_key("harnesses.opencode.cli.timeout_seconds"), value)


def test_validate_value_rejects_an_unknown_timezone() -> None:
    with pytest.raises(ConfigurationError, match="unknown timezone"):
        validate_value(resolve_key("report.timezone"), "Mars/Olympus")


def test_validate_value_accepts_valid_domain_values() -> None:
    validate_value(resolve_key("harnesses.opencode.cli.timeout_seconds"), "30.5")
    validate_value(resolve_key("report.timezone"), "Asia/Taipei")
    validate_value(resolve_key("report.timezone"), "UTC")


@pytest.fixture
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at a throwaway file for the duration of one test."""

    path = tmp_path / "config.env"
    monkeypatch.setenv(CONFIG_FILE_VARIABLE, str(path))
    return path


def test_set_value_writes_the_environment_variable_form(settings_file: Path) -> None:
    set_value("harnesses.opencode.cli.model", "gpt-5")

    assert stored_values(settings_file) == {
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL": "gpt-5"
    }


def test_set_value_creates_an_owner_only_file(settings_file: Path) -> None:
    set_value("harnesses.opencode.cli.model", "gpt-5")

    assert settings_file.stat().st_mode & 0o777 == 0o600


def test_set_value_replaces_an_earlier_entry_for_the_same_key(settings_file: Path) -> None:
    set_value("harnesses.opencode.cli.model", "gpt-5")
    set_value("harnesses.opencode.cli.model", "gpt-5-mini")

    assert stored_values(settings_file) == {
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL": "gpt-5-mini"
    }


def test_set_value_keeps_a_value_containing_spaces_intact(settings_file: Path) -> None:
    set_value("report.output_directory", "/tmp/my reports")

    assert stored_values(settings_file) == {
        "IIWI_REPORT__OUTPUT_DIRECTORY": "/tmp/my reports"
    }


def test_set_value_refuses_a_bad_value_without_creating_the_file(
    settings_file: Path,
) -> None:
    with pytest.raises(ConfigurationError):
        set_value("harnesses.opencode.cli.run_timeout_seconds", "abc")

    assert not settings_file.exists()


def test_set_value_refuses_a_nan_timeout_without_creating_the_file(
    settings_file: Path,
) -> None:
    with pytest.raises(ConfigurationError):
        set_value("harnesses.opencode.cli.timeout_seconds", "nan")

    assert not settings_file.exists()


def test_set_value_refuses_an_unknown_timezone_without_creating_the_file(
    settings_file: Path,
) -> None:
    with pytest.raises(ConfigurationError):
        set_value("report.timezone", "Mars/Olympus")

    assert not settings_file.exists()


def test_unset_value_removes_the_entry_and_reports_that_it_did(
    settings_file: Path,
) -> None:
    set_value("harnesses.opencode.cli.model", "gpt-5")

    setting, removed = unset_value("harnesses.opencode.cli.model")

    assert (setting.key, removed) == ("harnesses.opencode.cli.model", True)
    assert stored_values(settings_file) == {}


def test_unset_value_on_a_key_that_was_never_set_is_a_quiet_no_op(
    settings_file: Path,
) -> None:
    setting, removed = unset_value("harnesses.opencode.cli.model")

    assert (setting.key, removed) == ("harnesses.opencode.cli.model", False)


def test_describe_settings_reports_where_each_value_comes_from(
    settings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_value("harnesses.opencode.cli.model", "gpt-5")
    monkeypatch.setenv("IIWI_REPORT__TIMEZONE", "UTC")
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)

    rows = {row.key: row for row in describe_settings()}

    assert (
        rows["harnesses.opencode.cli.model"].value,
        rows["harnesses.opencode.cli.model"].source,
    ) == ("gpt-5", "file")
    assert rows["harnesses.opencode.cli.model"].default == ""
    assert (rows["report.timezone"].value, rows["report.timezone"].source) == (
        "UTC",
        "environment",
    )
    assert (
        rows["harnesses.opencode.cli.executable"].value,
        rows["harnesses.opencode.cli.executable"].source,
    ) == ("opencode", "default")


def test_describe_settings_lets_the_environment_win_over_the_file(
    settings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_value("harnesses.opencode.cli.model", "from-file")
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "from-environment")

    rows = {row.key: row for row in describe_settings()}

    assert (
        rows["harnesses.opencode.cli.model"].value,
        rows["harnesses.opencode.cli.model"].source,
    ) == ("from-environment", "environment")


def test_describe_settings_works_without_a_settings_file(settings_file: Path) -> None:
    rows = {row.key: row for row in describe_settings()}

    assert not settings_file.exists()
    assert rows["harnesses.opencode.cli.model"].source == "default"


# --- IMPORTANT 2: filesystem errors must raise ConfigurationError, not a raw
# OSError, so they exit with code 3 like every other settings failure instead
# of dumping a traceback.


@skip_unless_permissions_enforced
def test_set_value_raises_configuration_error_on_an_unwritable_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "unwritable"
    directory.mkdir()
    path = directory / "config.env"
    monkeypatch.setenv(CONFIG_FILE_VARIABLE, str(path))
    directory.chmod(0o500)  # read + execute only: no write, no create
    try:
        with pytest.raises(ConfigurationError):
            set_value("harnesses.opencode.cli.model", "gpt-5")
    finally:
        directory.chmod(0o700)  # restore so pytest can clean up tmp_path


@skip_unless_permissions_enforced
def test_describe_settings_raises_configuration_error_on_an_unreadable_file(
    settings_file: Path,
) -> None:
    set_value("harnesses.opencode.cli.model", "gpt-5")
    settings_file.chmod(0o000)
    try:
        with pytest.raises(ConfigurationError):
            describe_settings()
    finally:
        settings_file.chmod(0o600)  # restore so pytest can clean up tmp_path


# --- IMPORTANT 5: `_prepare_file` must not silently reset the mode of a file
# it did not create.


def test_set_value_keeps_the_mode_of_a_preexisting_file(settings_file: Path) -> None:
    settings_file.write_text("", encoding="utf-8")
    settings_file.chmod(0o644)

    set_value("harnesses.opencode.cli.model", "gpt-5")

    assert settings_file.stat().st_mode & 0o777 == 0o644


# --- MINOR: no existing test exercises `_prepare_file`'s `parent.mkdir`
# branch, because the `settings_file` fixture's directory (`tmp_path`) always
# already exists — but a missing config directory is the real first-run path.


def test_set_value_creates_a_missing_config_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "nested" / "config.env"
    monkeypatch.setenv(CONFIG_FILE_VARIABLE, str(path))

    set_value("harnesses.opencode.cli.model", "gpt-5")

    assert stored_values(path) == {
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL": "gpt-5"
    }
