import pytest

from iiwi import cli, config_store


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


def test_load_settings_is_silent_when_no_deprecated_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS", raising=False)

    cli._load_settings()

    assert capsys.readouterr().err == ""
