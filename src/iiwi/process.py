"""Safe subprocess execution for harness and Git commands."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

_TIMEOUT_RETURNCODE = 124
_LAUNCH_FAILURE_RETURNCODE = 127


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Execute a pre-tokenized command without shell expansion."""

    def __init__(self, *, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
    ) -> CommandResult:
        """Run a command, reporting timeouts and launch failures as failed results.

        Every call site already handles a non-zero return code, so process-level
        failures are translated here instead of raising through unrelated layers.

        When `stdout_path` is given, stdout is redirected to that file rather than
        piped. Some binaries (OpenCode's export command) write only what fits in
        the OS pipe buffer when their stdout is a pipe, then exit cleanly with a
        truncated payload; a regular file avoids the truncation.
        """

        out_file = None
        captured_stdout = ""
        captured_stderr = ""
        returncode = 0
        try:
            if stdout_path is None:
                text_completed = subprocess.run(
                    args,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
                returncode = text_completed.returncode
                captured_stdout = text_completed.stdout
                captured_stderr = text_completed.stderr
            else:
                out_file = stdout_path.open("wb")
                bytes_completed = subprocess.run(
                    args,
                    check=False,
                    stdout=out_file,
                    stderr=subprocess.PIPE,
                    timeout=self._timeout_seconds,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
                returncode = bytes_completed.returncode
                captured_stdout = stdout_path.read_bytes().decode(
                    "utf-8", errors="replace"
                )
                stderr_bytes = bytes_completed.stderr
                if stderr_bytes is not None:
                    captured_stderr = stderr_bytes.decode(
                        "utf-8", errors="replace"
                    )
        except subprocess.TimeoutExpired:
            executable = args[0] if args else "command"
            return CommandResult(
                returncode=_TIMEOUT_RETURNCODE,
                stdout="",
                stderr=f"{executable} timed out after {self._timeout_seconds} seconds",
            )
        except OSError as exc:
            return CommandResult(
                returncode=_LAUNCH_FAILURE_RETURNCODE,
                stdout="",
                stderr=str(exc) or type(exc).__name__,
            )
        finally:
            if out_file is not None:
                out_file.close()
        return CommandResult(
            returncode=returncode,
            stdout=captured_stdout,
            stderr=captured_stderr,
        )
