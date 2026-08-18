import shutil
from pathlib import Path

import pytest

from iiwi import cli
from iiwi.config import AppSettings
from iiwi.errors import ConfigurationError


def _settings(**narrator: object) -> AppSettings:
    settings = AppSettings()
    for name, value in narrator.items():
        setattr(settings.narrator, name, value)
    return settings


def test_provider_follows_the_harness_when_unset() -> None:
    settings = _settings()

    assert cli._resolve_provider(settings, cli.Harness.CLAUDE_CODE) == "claude"
    assert cli._resolve_provider(settings, cli.Harness.CODEX) == "codex"
    assert cli._resolve_provider(settings, cli.Harness.OPENCODE) == "opencode"


def test_configured_provider_overrides_the_harness() -> None:
    settings = _settings(provider="claude")

    assert cli._resolve_provider(settings, cli.Harness.CODEX) == "claude"


def test_unknown_provider_is_a_configuration_error() -> None:
    settings = _settings(provider="gemini")

    with pytest.raises(ConfigurationError, match="gemini"):
        cli._resolve_provider(settings, cli.Harness.CODEX)


def test_executable_defaults_to_the_provider_name() -> None:
    settings = _settings()

    assert cli._resolve_executable(settings, "claude") == "claude"
    assert cli._resolve_executable(settings, "codex") == "codex"


def test_executable_for_opencode_comes_from_the_harness_setting() -> None:
    settings = _settings()
    settings.harnesses.opencode.cli.executable = "/opt/bin/opencode"

    assert cli._resolve_executable(settings, "opencode") == "/opt/bin/opencode"


def test_executable_falls_back_only_for_opencode() -> None:
    settings = _settings()
    settings.harnesses.opencode.cli.executable = "/opt/bin/opencode"

    assert cli._resolve_executable(settings, "opencode") == "/opt/bin/opencode"
    assert cli._resolve_executable(settings, "claude") == "claude"


def test_configured_executable_wins_for_every_provider() -> None:
    settings = _settings(executable="/Users/x/.codex/plugins/.plugin-appserver/codex")

    assert cli._resolve_executable(settings, "codex").endswith("codex")
    assert cli._resolve_executable(settings, "opencode").endswith("codex")


def test_model_falls_back_only_for_opencode() -> None:
    settings = _settings()
    settings.harnesses.opencode.cli.model = "deepseek-r1"

    assert cli._resolve_model(settings, "opencode") == "deepseek-r1"
    assert cli._resolve_model(settings, "claude") == ""


def test_configured_model_wins() -> None:
    settings = _settings(model="opus")
    settings.harnesses.opencode.cli.model = "deepseek-r1"

    assert cli._resolve_model(settings, "opencode") == "opus"
    assert cli._resolve_model(settings, "claude") == "opus"


def test_timeout_falls_back_only_for_opencode() -> None:
    settings = _settings()
    settings.harnesses.opencode.cli.run_timeout_seconds = 45.0

    assert cli._resolve_timeout(settings, "opencode") == 45.0
    assert cli._resolve_timeout(settings, "claude") == 600.0


def test_configured_timeout_wins() -> None:
    settings = _settings(timeout_seconds=30.0)
    settings.harnesses.opencode.cli.run_timeout_seconds = 45.0

    assert cli._resolve_timeout(settings, "opencode") == 30.0


def test_build_narrator_returns_the_adapter_for_the_harness() -> None:
    from iiwi.summarizers.narrators.claude import ClaudeNarrator
    from iiwi.summarizers.narrators.codex import CodexNarrator
    from iiwi.summarizers.opencode_run import OpenCodeRunner

    settings = _settings()

    assert isinstance(cli._build_narrator(settings, cli.Harness.CLAUDE_CODE), ClaudeNarrator)
    assert isinstance(cli._build_narrator(settings, cli.Harness.CODEX), CodexNarrator)
    assert isinstance(cli._build_narrator(settings, cli.Harness.OPENCODE), OpenCodeRunner)


def test_daily_narrator_prefers_opencode_among_installed_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iiwi.summarizers.opencode_run import OpenCodeRunner

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/" + Path(name).name)

    assert isinstance(cli._build_daily_narrator(_settings()), OpenCodeRunner)


def test_daily_narrator_skips_providers_that_are_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iiwi.summarizers.narrators.claude import ClaudeNarrator

    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/local/bin/claude" if name == "claude" else None
    )

    assert isinstance(cli._build_daily_narrator(_settings()), ClaudeNarrator)


def test_daily_narrator_raises_when_no_provider_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iiwi.summarizers.narrator import NarrativeRunError

    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(NarrativeRunError, match="opencode"):
        cli._build_daily_narrator(_settings())
