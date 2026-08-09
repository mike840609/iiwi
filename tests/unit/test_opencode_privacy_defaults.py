from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import typer

import iiwi.cli as cli
from iiwi.config import AppSettings
from iiwi.harnesses.opencode.mapper import OpenCodeExportMapper
from iiwi.harnesses.opencode.source import OpenCodeCliSource
from iiwi.models.session import SessionDescriptor
from iiwi.process import CommandResult


@dataclass
class FakeRunner:
    calls: list[list[str]] = field(default_factory=list)

    def run(
        self,
        args: list[str],
        *,
        stdout_path: object = None,
    ) -> CommandResult:
        self.calls.append(args)
        return CommandResult(returncode=0, stdout='{"messages": []}', stderr="")


def test_opencode_sanitize_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(
        "IIWI_HARNESSES__OPENCODE__CLI__SANITIZE",
        raising=False,
    )

    assert AppSettings().harnesses.opencode.cli.sanitize is False


def test_opencode_sanitize_can_be_enabled_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "IIWI_HARNESSES__OPENCODE__CLI__SANITIZE",
        "true",
    )

    assert AppSettings().harnesses.opencode.cli.sanitize is True


def test_opencode_export_is_raw_by_default() -> None:
    runner = FakeRunner()
    source = OpenCodeCliSource(runner=runner, executable="opencode")

    source.load(SessionDescriptor(harness="opencode", session_id="s1"))

    assert runner.calls == [["opencode", "export", "s1"]]


def test_opencode_export_can_enable_sanitize() -> None:
    runner = FakeRunner()
    source = OpenCodeCliSource(
        runner=runner,
        executable="opencode",
        sanitize=True,
    )

    source.load(SessionDescriptor(harness="opencode", session_id="s1"))

    assert runner.calls == [["opencode", "export", "s1", "--sanitize"]]


def test_mapper_falls_back_and_omits_redacted_activities() -> None:
    descriptor = SessionDescriptor(
        harness="opencode",
        session_id="s1",
        title="Database title",
        working_directory_hint="/repo/from-db",
    )
    payload = {
        "info": {
            "title": "[redacted:session-title:s1]",
            "directory": "[redacted:session-directory:s1]",
        },
        "messages": [
            {
                "info": {"id": "m1", "role": "user"},
                "parts": [
                    {"type": "text", "text": "[redacted:text:p1]"},
                    {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "call-1",
                        "state": {"input": "[redacted:tool-input:p2]"},
                    },
                ],
            }
        ],
    }

    session = OpenCodeExportMapper().map(payload, descriptor)

    assert session.title == "Database title"
    assert session.working_directory == "/repo/from-db"
    assert session.activities == []


def test_effective_sanitize_uses_setting_and_cli_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "IIWI_HARNESSES__OPENCODE__CLI__SANITIZE",
        "true",
    )
    settings = AppSettings()

    assert cli._effective_sanitize(settings, cli.Harness.OPENCODE, None) is True
    assert cli._effective_sanitize(settings, cli.Harness.OPENCODE, False) is False


@pytest.mark.parametrize("harness", [cli.Harness.CLAUDE_CODE, cli.Harness.CODEX])
def test_sanitize_is_rejected_for_non_opencode(harness: cli.Harness) -> None:
    with pytest.raises(typer.BadParameter, match="supported only"):
        cli._validate_privacy_options(harness=harness, sanitize=True)
