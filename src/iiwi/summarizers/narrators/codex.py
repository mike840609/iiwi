"""Codex narration through `codex exec`."""

from __future__ import annotations

from pathlib import Path

from iiwi.summarizers.narrator import (
    CommandRunnerLike,
    NarrativeRunError,
    failure_detail,
    marked_prompt,
    narrator_failure_message,
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
        codex_home: Path | None = None,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._model = model
        self._workdir = workdir
        # Only used to decide whether a not-found failure should point at the
        # Codex desktop docs (see narrator_failure_message); never read to
        # locate the executable itself.
        self._codex_home = codex_home

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
            # `codex exec` refuses to run outside a Git repository unless told
            # otherwise, and `workdir` below is a disposable temp dir iiwi
            # created (not a repo) — so the check is protecting against
            # nothing here and would otherwise make every run fail with
            # "Not inside a trusted directory".
            args += ["--skip-git-repo-check"]
            # Explicit read-only sandbox: narration only reads the transcript,
            # so forbid writes even though read-only is the default — a
            # self-documenting posture against prompt-injection exfiltration.
            args += ["--sandbox", "read-only"]
            # `cwd=workdir` keeps `codex exec` out of the user's project: without
            # it the subprocess inherits iiwi's own cwd and gets write access to
            # the repository being reported on.
            result = self._runner.run(
                args, stdout_path=output_path, stdin_text=transcript, cwd=workdir
            )
            narrative = ""
            if output_path.exists():
                narrative = output_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise NarrativeRunError(str(exc)) from exc
        if result.returncode != 0:
            raise NarrativeRunError(
                narrator_failure_message(
                    "codex",
                    self._executable,
                    failure_detail(result.stderr, narrative, fallback="codex exec failed"),
                    codex_home=self._codex_home,
                )
            )
        if not narrative:
            raise NarrativeRunError("codex exec produced no output")
        return narrative
