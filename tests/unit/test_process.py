import json
import subprocess
import sys
from pathlib import Path

import pytest

from iiwi import process
from iiwi.process import CommandRunner

_TRUNCATED_ECHO = (
    # A child that mimics opencode's stdout behaviour: when its stdout is a pipe
    # (FIFO) it writes only 64 KiB and exits cleanly, producing invalid JSON;
    # when its stdout is a regular file it writes the full payload.
    "import json,os,stat,sys\n"
    "data=('{\"blob\":\"%s\"}').encode()\n"
    "if stat.S_IFMT(os.fstat(1).st_mode)==stat.S_IFIFO:\n"
    "    os.write(1,data[:65536])\n"
    "else:\n"
    "    os.write(1,data)\n"
# Enough to overflow the 64 KiB pipe buffer (the whole point of the test) yet
# small enough that the `python -c "<script>"` argument stays under Linux's
# per-argument limit (MAX_ARG_STRLEN), which would otherwise raise E2BIG.
) % ("x" * 70_000)


def test_runner_disables_interactive_git_and_uses_argument_list() -> None:
    runner = CommandRunner(timeout_seconds=5)

    result = runner.run([sys.executable, "-c", "print('ok')"])

    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_timeout_becomes_a_failed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def timing_out_run(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd=["opencode", "stats"], timeout=5.0)

    monkeypatch.setattr(process.subprocess, "run", timing_out_run)

    result = CommandRunner(timeout_seconds=5).run(["opencode", "stats"])

    assert result.returncode != 0
    assert result.stdout == ""
    assert "opencode timed out after 5 seconds" in result.stderr


def test_missing_executable_becomes_a_failed_result() -> None:
    result = CommandRunner(timeout_seconds=5).run(["iiwi-missing-binary"])

    assert result.returncode != 0
    assert result.stdout == ""
    assert "iiwi-missing-binary" in result.stderr


def test_pipe_capture_truncates_output_at_pipe_buffer() -> None:
    result = CommandRunner(timeout_seconds=10).run(
        [sys.executable, "-c", _TRUNCATED_ECHO]
    )

    assert result.returncode == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_stdout_path_captures_full_output_beyond_pipe_buffer(tmp_path) -> None:
    out_path = tmp_path / "export.json"

    result = CommandRunner(timeout_seconds=10).run(
        [sys.executable, "-c", _TRUNCATED_ECHO],
        stdout_path=out_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload["blob"]) == 70_000
    assert out_path.exists()


def test_run_feeds_stdin_text_to_the_child() -> None:
    runner = CommandRunner(timeout_seconds=10.0)

    result = runner.run(
        ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"],
        stdin_text="hello",
    )

    assert result.returncode == 0
    assert result.stdout == "HELLO"


def test_run_feeds_stdin_text_utf8_independent_of_locale() -> None:
    """The text branch must encode stdin as UTF-8, not the process locale, so a
    non-ASCII transcript survives on a machine whose locale is not UTF-8."""
    runner = CommandRunner(timeout_seconds=10.0)

    result = runner.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write(sys.stdin.buffer.read().decode('utf-8'))",
        ],
        stdin_text="繁體中文測試",
    )

    assert result.returncode == 0
    assert result.stdout == "繁體中文測試"


def test_run_replaces_undecodable_output_instead_of_raising() -> None:
    """A child emitting non-UTF-8 bytes is a failed command, not a crash."""
    runner = CommandRunner(timeout_seconds=10.0)

    result = runner.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'\\xff'); "
            "sys.stderr.buffer.write(b'\\xfe')",
        ]
    )

    assert result.returncode == 0
    assert result.stdout == "\ufffd"
    assert result.stderr == "\ufffd"


def test_run_feeds_stdin_text_when_redirecting_stdout(tmp_path: Path) -> None:
    runner = CommandRunner(timeout_seconds=10.0)
    destination = tmp_path / "out.txt"

    result = runner.run(
        ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        stdout_path=destination,
        stdin_text="piped body",
    )

    assert result.returncode == 0
    assert destination.read_text(encoding="utf-8") == "piped body"
    assert result.stdout == "piped body"


def test_run_without_stdin_text_is_unchanged() -> None:
    runner = CommandRunner(timeout_seconds=10.0)

    result = runner.run(["python3", "-c", "print('no stdin needed')"])

    assert result.returncode == 0
    assert result.stdout.strip() == "no stdin needed"


def test_run_launches_the_child_in_the_given_cwd(tmp_path: Path) -> None:
    runner = CommandRunner(timeout_seconds=5)

    result = runner.run(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert Path(result.stdout.strip()).samefile(tmp_path)


def test_run_launches_the_child_in_the_given_cwd_when_redirecting_stdout(
    tmp_path: Path,
) -> None:
    runner = CommandRunner(timeout_seconds=5)
    workdir = tmp_path / "work"
    workdir.mkdir()
    destination = tmp_path / "out.txt"

    result = runner.run(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        stdout_path=destination,
        cwd=workdir,
    )

    assert result.returncode == 0
    assert Path(result.stdout.strip()).samefile(workdir)


def test_run_without_cwd_inherits_the_parent_process_cwd() -> None:
    runner = CommandRunner(timeout_seconds=5)

    result = runner.run([sys.executable, "-c", "import os; print(os.getcwd())"])

    assert result.returncode == 0
    assert Path(result.stdout.strip()).samefile(Path.cwd())
