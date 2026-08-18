"""Shared test double for the Claude and Codex narrator adapter tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from iiwi.process import CommandResult


@dataclass
class RecordingRunner:
    returncode: int = 0
    stderr: str = ""
    output: str = ""
    calls: list[list[str]] = field(default_factory=list)
    stdin_texts: list[str | None] = field(default_factory=list)
    cwds: list[Path | None] = field(default_factory=list)

    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
        stdin_text: str | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        self.calls.append(args)
        self.stdin_texts.append(stdin_text)
        self.cwds.append(cwd)
        if stdout_path is not None:
            stdout_path.write_text(self.output, encoding="utf-8")
        return CommandResult(self.returncode, "", self.stderr)


@pytest.fixture
def runner_factory() -> type[RecordingRunner]:
    return RecordingRunner
