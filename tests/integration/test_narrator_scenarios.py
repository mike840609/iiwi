"""End-to-end coverage for the four installation scenarios the spec promises.

Each scenario pins every harness explicitly (Claude Code's projects directory,
Codex's home directory, and OpenCode's `shutil.which` resolution) so the
result depends only on what the test sets up, never on this machine's real
`~/.claude`, `~/.codex`, or installed CLIs.
"""

import shutil
from pathlib import Path

import pytest

from iiwi import cli
from iiwi.summarizers.narrators.claude import ClaudeNarrator
from iiwi.summarizers.narrators.codex import CodexNarrator
from iiwi.summarizers.opencode_run import OpenCodeRunner


def _only(installed: str | None) -> object:
    def which(name: str) -> str | None:
        return f"/usr/local/bin/{name}" if installed and name == installed else None

    return which


def test_only_opencode_behaves_exactly_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `shutil` is a singleton module: patching it here reaches every caller,
    # including `cli.shutil` and `harnesses.opencode.source.shutil`, because
    # they all hold the same module object.
    monkeypatch.setattr(shutil, "which", _only("opencode"))
    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(tmp_path / "absent")
    )
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent"))
    # Deliberately setting the deprecated key: this is the compatibility
    # promise under test, and it prints a migration notice to stderr. That is
    # correct behaviour, not a failure.
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "deepseek-r1")

    settings = cli._load_settings()
    harness = cli._default_harness(settings)
    provider = cli._resolve_provider(settings, harness)

    assert harness == cli.Harness.OPENCODE
    assert provider == "opencode"
    assert cli._resolve_model(settings, provider) == "deepseek-r1"
    assert isinstance(cli._build_narrator(settings, harness), OpenCodeRunner)


def test_only_claude_code_works_without_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(shutil, "which", _only("claude"))
    monkeypatch.setenv("IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(projects))
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent"))
    # A leftover OpenCode setting from a prior setup must not leak into Claude.
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "deepseek-r1")

    settings = cli._load_settings()
    harness = cli._default_harness(settings)
    provider = cli._resolve_provider(settings, harness)

    assert harness == cli.Harness.CLAUDE_CODE
    assert provider == "claude"
    # The leftover OpenCode model must not reach `claude --model`.
    assert cli._resolve_model(settings, provider) == ""
    assert cli._resolve_executable(settings, provider) == "claude"
    assert isinstance(cli._build_narrator(settings, harness), ClaudeNarrator)


def test_only_codex_with_the_cli_on_path_works_without_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    monkeypatch.setattr(shutil, "which", _only("codex"))
    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(tmp_path / "absent")
    )
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(codex_home))

    settings = cli._load_settings()
    harness = cli._default_harness(settings)
    provider = cli._resolve_provider(settings, harness)

    assert harness == cli.Harness.CODEX
    assert provider == "codex"
    assert cli._resolve_executable(settings, provider) == "codex"
    assert isinstance(cli._build_narrator(settings, harness), CodexNarrator)


def test_codex_desktop_reads_but_needs_an_executable_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    bundled = codex_home / "plugins" / ".plugin-appserver" / "codex"
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    # No CLI on PATH at all: Codex desktop ships no `codex` binary a shell
    # can find, only the session store and a bundled executable.
    monkeypatch.setattr(shutil, "which", _only(None))
    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(tmp_path / "absent")
    )
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(codex_home))

    settings = cli._load_settings()

    # Reading still works: availability is about the session store, not the
    # binary being on PATH.
    assert cli._default_harness(settings) == cli.Harness.CODEX

    # Before that setting, the executable resolves to the bare, unusable
    # "codex" name: nothing on this PATH can run it yet.
    assert cli._resolve_executable(settings, "codex") == "codex"

    # Narration needs one setting pointing at the bundled CLI.
    monkeypatch.setenv("IIWI_NARRATOR__EXECUTABLE", str(bundled))
    settings = cli._load_settings()

    assert cli._resolve_executable(settings, "codex") == str(bundled)
