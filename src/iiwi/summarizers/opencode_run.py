"""Local `opencode run` driver for the narrative report engine.

The weekly narrative is produced by the same CLI the user already has installed
(`opencode run`), so no API key, network endpoint, or extra dependency is
required. The prompt and a grouped raw transcript are handed to a subprocess;
the narrative prose comes back on stdout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from iiwi.process import CommandResult

_TEMPLATE = """Create a concise software engineering weekly report from the attached
OpenCode session transcript and usage statistics.

The reporting period is the last __DAYS__ days. The transcript is already
grouped by Git repository identity when possible, using headings like:

## Project: project-folder-name

Use those project headings exactly. Worktree directories belonging to the same
Git repository are already combined. Do not split them into separate projects,
do not merge different project headings, and do not infer replacement project
names from the conversation content.

Use this structure:

# Weekly Engineering Review

## Executive Summary

Summarize the most important work across all projects in 3-6 bullets.

## Work by Project

Create one section for every project heading found in the transcript:

### <project name>

**Directory:** `<full project directory>`

#### Completed

List changes that were clearly implemented or completed.

#### Investigated

List bugs, requirements, technical questions, alternatives, and possible
solutions that were investigated but not necessarily implemented.

#### Technical Decisions

List architecture, implementation, tooling, and design decisions, including
the rationale when available.

#### Verification

List tests, builds, reviews, commands, or other checks that were actually run.

#### Remaining Work

List incomplete work, blockers, failed attempts, missing verification, and
concrete next steps.

#### Related Sessions

List the relevant session titles and session IDs.

## Cross-Project Patterns

Describe repeated issues, shared technical themes, duplicated investigations,
or common tools across projects.

## Priorities for Next Week

Provide prioritized, concrete follow-up actions grouped by project.

## Usage Overview

Summarize model, token, tool, and cost information from the attached usage
statistics when available.

Rules:

- Use the provided Git-grouped project heading as the project name.
- Treat all listed working directories as worktrees or folders of that project.
- Include every project present in the transcript.
- Keep projects separate.
- Combine and deduplicate repeated sessions within the same project.
- Describe completed work only when there is evidence it was implemented.
- Do not treat assistant recommendations as completed user work.
- Clearly distinguish completed, investigated, decided, and verified work.
- Mention concrete files, components, commands, and features when available.
- Use concise, action-oriented bullets suitable for an engineering weekly report.
- Ignore casual conversation and unrelated content.
- Base every claim only on the attached transcript; do not invent projects,
  work, or verification that is not present.
"""


class OpenCodeRunError(Exception):
    """The local `opencode run` invocation could not produce a narrative."""


class _Runner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
    ) -> CommandResult: ...


def build_summary_prompt(days: int) -> str:
    """Return the weekly-report prompt with the day count substituted."""

    return _TEMPLATE.replace("__DAYS__", str(days))


class OpenCodeRunner:
    """Run `opencode run` against a grouped transcript and return its prose."""

    def __init__(
        self,
        *,
        runner: _Runner,
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

        workdir = self._workdir or Path(self._mkdtemp())
        transcript_path = workdir / "transcript.md"
        transcript_path.write_text(transcript, encoding="utf-8")
        output_path = workdir / "summary.md"
        args = [
            self._executable,
            "run",
            prompt,
            "--title",
            title,
            "--file",
            str(transcript_path),
            "--print-logs",
        ]
        if self._model:
            args += ["--model", self._model]
        result = self._runner.run(args, stdout_path=output_path)
        if result.returncode != 0:
            raise OpenCodeRunError(result.stderr.strip() or "opencode run failed")
        if not output_path.exists():
            raise OpenCodeRunError("opencode run produced no output")
        narrative = output_path.read_text(encoding="utf-8").strip()
        if not narrative:
            raise OpenCodeRunError("opencode run produced no output")
        return narrative

    def _mkdtemp(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="agent-worklog-report-")
