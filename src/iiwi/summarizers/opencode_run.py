"""Local `opencode run` driver for the narrative report engine."""

from __future__ import annotations

from pathlib import Path

from iiwi.summarizers.narrator import (
    CommandRunnerLike,
    NarrativeRunError,
    build_summary_prompt,
    failure_detail,
    marked_prompt,
    run_with_workdir,
)

OpenCodeRunError = NarrativeRunError

__all__ = [
    "OpenCodeRunError",
    "OpenCodeRunner",
    "build_summary_prompt",
]


class OpenCodeRunner:
    """Run `opencode run` against a grouped transcript and return its prose."""

    def __init__(
        self,
        *,
        runner: CommandRunnerLike,
        executable: str = "opencode",
        model: str = "",
        workdir: Path | None = None,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._model = model
        self._workdir = workdir

    def run(
        self,
        *,
        transcript: str,
        prompt: str,
        title: str,
    ) -> str:
        """Invoke opencode and return the trimmed narrative text.

        The transcript is written to a temporary file and attached with
        `--file`, and stdout is redirected to a second temporary file (the same
        pipe-truncation avoidance the export path uses). Failures surface as
        `OpenCodeRunError`.
        """

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
            transcript_path = workdir / "transcript.md"
            transcript_path.write_text(transcript, encoding="utf-8")
            output_path = workdir / "summary.md"
            args = [
                self._executable,
                "run",
                marked_prompt(prompt, title),
                "--title",
                title,
                "--file",
                str(transcript_path),
                "--print-logs",
            ]
            if self._model:
                args += ["--model", self._model]
            result = self._runner.run(args, stdout_path=output_path)
            narrative = ""
            if output_path.exists():
                narrative = output_path.read_text(encoding="utf-8").strip()
            if result.returncode != 0:
                raise OpenCodeRunError(
                    failure_detail(result.stderr, narrative, fallback="opencode run failed")
                )
        except OSError as exc:
            raise OpenCodeRunError(str(exc)) from exc
        if not narrative:
            raise OpenCodeRunError("opencode run produced no output")
        return narrative
