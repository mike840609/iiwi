"""Claude Code narration through `claude -p`."""

from __future__ import annotations

from pathlib import Path

from iiwi.summarizers.narrator import (
    CommandRunnerLike,
    NarrativeRunError,
    finish_narrative_run,
    marked_prompt,
    run_with_workdir,
)


class ClaudeNarrator:
    """Run `claude -p` against a grouped transcript and return its prose."""

    def __init__(
        self,
        *,
        runner: CommandRunnerLike,
        executable: str = "claude",
        model: str = "",
        workdir: Path | None = None,
        executable_configured: bool = False,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._model = model
        self._workdir = workdir
        self._executable_configured = executable_configured

    def run(self, *, transcript: str, prompt: str, title: str) -> str:
        return run_with_workdir(
            self._workdir,
            lambda workdir: self._run_in_workdir(
                workdir, transcript=transcript, prompt=prompt, title=title
            ),
        )

    def _run_in_workdir(
        self,
        workdir: Path,
        *,
        transcript: str,
        prompt: str,
        title: str,
    ) -> str:
        try:
            output_path = workdir / "summary.md"
            # No --mcp-config alongside it, so this disables MCP servers for the
            # run. --bare would also isolate the run but disables OAuth, which
            # is the credential path iiwi relies on.
            args = [
                self._executable,
                "-p",
                marked_prompt(prompt, title),
                "--strict-mcp-config",
            ]
            if self._model:
                args += ["--model", self._model]
            # `cwd=workdir` keeps `claude -p` out of the user's project: without
            # it the subprocess inherits iiwi's own cwd, loads the project's
            # CLAUDE.md and .claude/settings*.json, and can run Stop/PreToolUse
            # hooks as a side effect of generating a report.
            result = self._runner.run(
                args, stdout_path=output_path, stdin_text=transcript, cwd=workdir
            )
        except OSError as exc:
            raise NarrativeRunError(str(exc)) from exc
        return finish_narrative_run(
            "claude",
            self._executable,
            result,
            output_path,
            fallback="claude -p failed",
            empty_output_message="claude -p produced no output",
            executable_configured=self._executable_configured,
        )
