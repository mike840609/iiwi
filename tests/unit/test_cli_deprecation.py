import pytest

from iiwi import cli


def test_load_settings_warns_once_about_a_deprecated_model_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "deepseek-r1")

    cli._load_settings()

    captured = capsys.readouterr()
    assert "harnesses.opencode.cli.model" in captured.err
    assert "narrator.model" in captured.err


def test_load_settings_warns_once_about_a_deprecated_timeout_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS", "120")

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
