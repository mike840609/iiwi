import shutil
from pathlib import Path

import pytest

from iiwi.harnesses.claude_code.source import is_available as claude_code_is_available
from iiwi.harnesses.codex.source import is_available as codex_is_available
from iiwi.harnesses.opencode.source import is_available as opencode_is_available


def test_opencode_is_available_when_the_executable_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/opencode")

    assert opencode_is_available("opencode") is True


def test_opencode_is_unavailable_when_the_executable_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    assert opencode_is_available("opencode") is False


def test_claude_code_is_available_when_the_projects_directory_exists(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()

    assert claude_code_is_available(projects) is True
    assert claude_code_is_available(tmp_path / "absent") is False


def test_codex_is_available_when_the_home_directory_exists(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    home.mkdir()

    assert codex_is_available(home) is True
    assert codex_is_available(tmp_path / "absent") is False
