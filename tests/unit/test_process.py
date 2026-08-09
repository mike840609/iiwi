import json
import subprocess
import sys

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
    result = CommandRunner(timeout_seconds=5).run(["agent-worklog-missing-binary"])

    assert result.returncode != 0
    assert result.stdout == ""
    assert "agent-worklog-missing-binary" in result.stderr


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
