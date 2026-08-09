from dataclasses import dataclass, field
from pathlib import Path

import pytest

from iiwi.process import CommandResult
from iiwi.summarizers.opencode_run import (
    OpenCodeRunError,
    OpenCodeRunner,
    build_summary_prompt,
)


@dataclass
class RecordingRunner:
    returncode: int = 0
    stderr: str = ""
    output: str = ""
    calls: list[list[str]] = field(default_factory=list)

    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
    ) -> CommandResult:
        self.calls.append(args)
        if stdout_path is not None and self.returncode == 0:
            stdout_path.write_text(self.output, encoding="utf-8")
        return CommandResult(self.returncode, "", self.stderr)


def test_build_summary_prompt_substitutes_days() -> None:
    prompt = build_summary_prompt(14)

    assert "__DAYS__" not in prompt
    assert "last 14 days" in prompt
    assert "## Executive Summary" in prompt
    assert "## Work by Project" in prompt


def test_build_summary_prompt_forbids_inventing_content() -> None:
    prompt = build_summary_prompt(7)

    assert "attached transcript" in prompt


def test_run_invokes_opencode_with_transcript_file(tmp_path: Path) -> None:
    runner = RecordingRunner(output="# Weekly OpenCode Review\n\nWork happened.\n")
    driver = OpenCodeRunner(runner=runner, workdir=tmp_path)

    narrative = driver.run(
        transcript="## Project: Alpha\n",
        prompt="Write a report.",
        title="Agent Worklog - 2026-07-20 to 2026-07-27",
    )

    assert narrative == "# Weekly OpenCode Review\n\nWork happened."
    assert len(runner.calls) == 1
    args = runner.calls[0]
    assert args[0:2] == ["opencode", "run"]
    assert args[2] == "Write a report."
    assert "--title" in args
    assert "--file" in args
    assert "--print-logs" in args
    transcript_arg = args[args.index("--file") + 1]
    assert Path(transcript_arg) == tmp_path / "transcript.md"
    assert Path(transcript_arg).read_text(encoding="utf-8") == "## Project: Alpha\n"


def test_run_appends_model_flag_when_configured(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    driver = OpenCodeRunner(
        runner=runner,
        executable="opencode",
        model="gpt-5.3",
        workdir=tmp_path,
    )

    driver.run(transcript="t", prompt="p", title="title")

    assert "--model" in runner.calls[0]
    assert runner.calls[0][runner.calls[0].index("--model") + 1] == "gpt-5.3"


def test_run_raises_on_nonzero_exit(tmp_path: Path) -> None:
    runner = RecordingRunner(returncode=1, stderr="opencode: failed to connect")
    driver = OpenCodeRunner(runner=runner, workdir=tmp_path)

    with pytest.raises(OpenCodeRunError, match="failed to connect"):
        driver.run(transcript="t", prompt="p", title="title")


def test_run_raises_when_output_is_empty(tmp_path: Path) -> None:
    runner = RecordingRunner(output="")
    driver = OpenCodeRunner(runner=runner, workdir=tmp_path)

    with pytest.raises(OpenCodeRunError, match="no output"):
        driver.run(transcript="t", prompt="p", title="title")


def test_run_raises_when_stdout_file_is_never_written(tmp_path: Path) -> None:
    runner = RecordingRunner()
    driver = OpenCodeRunner(runner=runner, workdir=tmp_path)

    with pytest.raises(OpenCodeRunError, match="no output"):
        driver.run(transcript="t", prompt="p", title="title")