import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from iiwi.process import CommandResult
from iiwi.summarizers.opencode_run import OpenCodeRunError, OpenCodeRunner


@dataclass
class RecordingRunner:
    returncode: int = 0
    stderr: str = ""
    output: str = ""
    calls: list[list[str]] = field(default_factory=list)
    stdin_texts: list[str | None] = field(default_factory=list)

    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult:
        self.calls.append(args)
        self.stdin_texts.append(stdin_text)
        if stdout_path is not None and self.returncode == 0:
            stdout_path.write_text(self.output, encoding="utf-8")
        return CommandResult(self.returncode, "", self.stderr)


def test_run_invokes_opencode_with_transcript_file(tmp_path: Path) -> None:
    runner = RecordingRunner(output="# Weekly OpenCode Review\n\nWork happened.\n")
    driver = OpenCodeRunner(runner=runner, workdir=tmp_path)

    narrative = driver.run(
        transcript="## Project: Alpha\n",
        prompt="Write a report.",
        title="Iiwi - 2026-07-20 to 2026-07-27",
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


def test_run_removes_owned_tempdir_on_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Path] = []

    def mkdtemp(*, prefix: str) -> str:
        path = tmp_path / f"{prefix}{len(created)}"
        path.mkdir()
        created.append(path)
        return str(path)

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)

    OpenCodeRunner(runner=RecordingRunner(output="ok")).run(
        transcript="t",
        prompt="p",
        title="title",
    )
    with pytest.raises(OpenCodeRunError, match="failed"):
        OpenCodeRunner(runner=RecordingRunner(returncode=1, stderr="failed")).run(
            transcript="t",
            prompt="p",
            title="title",
        )

    assert [path.exists() for path in created] == [False, False]


def test_run_translates_tempfile_io_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mkdtemp(*, prefix: str) -> str:
        del prefix
        raise OSError("no temp space")

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)

    with pytest.raises(OpenCodeRunError, match="no temp space"):
        OpenCodeRunner(runner=RecordingRunner(output="ok")).run(
            transcript="t",
            prompt="p",
            title="title",
        )
