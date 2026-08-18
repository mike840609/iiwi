"""Codex narration through `codex exec`."""

from __future__ import annotations

from pathlib import Path

from iiwi.summarizers.narrator import (
    CommandRunnerLike,
    NarrativeRunError,
    failure_detail,
    marked_prompt,
    run_with_workdir,
)


class CodexNarrator:
    """Run `codex exec` against a grouped transcript and return its prose."""

    def __init__(
        self,
        *,
        runner: CommandRunnerLike,
        executable: str = "codex",
        model: str = "",
        workdir: Path | None = None,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._model = model
        self._workdir = workdir

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
            # `codex exec` appends piped stdin to the prompt as a <stdin> block,
            # which is exactly the prompt-plus-transcript shape iiwi needs.
            args = [self._executable, "exec", marked_prompt(prompt, title)]
            if self._model:
                args += ["-m", self._model]
            result = self._runner.run(args, stdout_path=output_path, stdin_text=transcript)
            narrative = ""
            if output_path.exists():
                narrative = output_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise NarrativeRunError(str(exc)) from exc
        if result.returncode != 0:
            raise NarrativeRunError(
                failure_detail(result.stderr, narrative, fallback="codex exec failed")
            )
        if not narrative:
            raise NarrativeRunError("codex exec produced no output")
        return narrative
