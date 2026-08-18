import pytest

from iiwi import cli, config_store

# The once-per-process flag `_warn_about_deprecated_keys` guards with is reset
# before every test by tests/conftest.py's autouse `_reset_deprecation_notice_flag`
# fixture, so each test below can assume a clean flag without repeating that here.


def test_load_settings_warns_once_about_a_deprecated_model_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "deepseek-r1")

    cli._load_settings()

    captured = capsys.readouterr()
    assert "harnesses.opencode.cli.model" in captured.err
    assert "narrator.model" in captured.err
    # "Once" means once, not once per deprecated key: the sibling key was never
    # set, so its notice must not appear.
    assert "narrator.timeout_seconds" not in captured.err


def test_load_settings_warns_once_about_a_deprecated_timeout_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS", "120")

    cli._load_settings()

    captured = capsys.readouterr()
    assert "harnesses.opencode.cli.run_timeout_seconds" in captured.err
    assert "narrator.timeout_seconds" in captured.err
    assert "narrator.model" not in captured.err


def test_load_settings_warns_about_a_deprecated_timeout_key_set_through_the_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The production path: `config set` writes the settings file, not a live
    environment variable, so the notice must fire from `_env_file` alone.

    `run_timeout_seconds` is the key whose detection depends on
    `model_fields_set` rather than truthiness, so this is the one whose
    file-sourced behaviour actually needs pinning.
    """

    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS", raising=False)
    # conftest's autouse fixture already points IIWI_CONFIG_FILE at a tmp file;
    # `set_value` is the same call `iiwi config set` makes.
    config_store.set_value("harnesses.opencode.cli.run_timeout_seconds", "900")

    cli._load_settings()

    captured = capsys.readouterr()
    assert "harnesses.opencode.cli.run_timeout_seconds" in captured.err
    assert "narrator.timeout_seconds" in captured.err


def test_load_settings_warns_only_once_per_process_across_repeated_calls(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """must-fix 5: the interactive layer calls `_load_settings()` on nearly
    every keypress (`_choose_harness` alone reloads it once per harness
    cycle), so "once" has to mean once per process, not once per call."""

    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "deepseek-r1")

    cli._load_settings()
    cli._load_settings()
    cli._load_settings()

    captured = capsys.readouterr()
    assert captured.err.count("harnesses.opencode.cli.model") == 1


def test_load_settings_is_silent_when_no_deprecated_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS", raising=False)

    cli._load_settings()

    assert capsys.readouterr().err == ""
