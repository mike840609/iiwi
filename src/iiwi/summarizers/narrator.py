"""The narration contract shared by every provider adapter.

The weekly narrative is produced by a coding-agent CLI the user already has
installed, so no API key, network endpoint, or extra dependency is required. A
prompt and a grouped transcript go to a subprocess; the prose comes back.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from iiwi.errors import IiwiError
from iiwi.models.report_options import DetailLevel
from iiwi.process import CommandResult
from iiwi.security.secure_files import secure_temporary_directory
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX

_TEMPLATE = """Create a concise software engineering weekly report from the attached
session transcript and usage statistics.

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

_BRIEF_TEMPLATE = """Create a concise weekly work update from the attached
session transcript.

The reporting period is the last __DAYS__ days. Use this structure:

# Weekly Work Update

## Outcomes

List concise outcomes and impact that are supported by the transcript.

## In Progress

List clearly incomplete work with concise impact when available.

## Blockers

Include only blockers supported by the transcript.

## Next Week

List concise, concrete follow-up work supported by the transcript.

Rules:

- Keep claims grounded in the attached transcript; do not invent work.
- Do not include session IDs, file lists, command lists, or Usage.
- Do not treat assistant recommendations as completed user work.
"""


class NarrativeRunError(IiwiError):
    """A provider CLI could not produce a narrative."""


class NarrativeRunner(Protocol):
    def run(self, *, transcript: str, prompt: str, title: str) -> str: ...


class CommandRunnerLike(Protocol):
    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = ...,
        stdin_text: str | None = ...,
        cwd: Path | None = ...,
    ) -> CommandResult: ...


def build_summary_prompt(
    days: int,
    detail: DetailLevel = DetailLevel.FULL,
) -> str:
    """Return the weekly-report prompt with the day count substituted."""

    detail = DetailLevel(detail)
    template = _BRIEF_TEMPLATE if detail is DetailLevel.BRIEF else _TEMPLATE
    return template.replace("__DAYS__", str(days))


def marked_prompt(prompt: str, title: str) -> str:
    """Prefix the prompt with the marker that keeps iiwi's runs out of reports.

    Only `opencode run` accepts `--title`; Claude Code and Codex title sessions
    from model output. Putting the marker in the prompt is the one signal every
    harness records verbatim, so `is_iiwi_authored` can see it everywhere.

    Idempotent: callers already pass a title carrying the prefix (it doubles
    as the `--title` argument for OpenCode), so a title that starts with it is
    used verbatim instead of being prefixed again.
    """

    if not title.startswith(IIWI_SESSION_TITLE_PREFIX):
        title = f"{IIWI_SESSION_TITLE_PREFIX}{title}"
    return f"{title}\n\n{prompt}"


def failure_detail(stderr: str, stdout: str, *, fallback: str) -> str:
    """Report why a provider failed, wherever it chose to say so.

    An unauthenticated `claude -p` exits non-zero with an empty stderr and the
    reason on stdout, so preferring stderr alone turns "please log in" into a
    generic failure.
    """

    detail = stderr.strip()
    if detail:
        return detail
    first_line = stdout.strip().splitlines()[0].strip() if stdout.strip() else ""
    return first_line or fallback


def narrator_failure_message(
    provider: str,
    executable: str,
    detail: str,
    *,
    codex_home: Path | None = None,
    executable_configured: bool = False,
) -> str:
    """Name the resolved provider and where to fix it, on top of the raw detail.

    `failure_detail` returns a bare string (the CLI's own stderr/stdout line, or
    an OSError repr like "[Errno 2] No such file or directory: 'codex'") with no
    mention of which provider ran or which setting controls it. Every adapter
    raises `NarrativeRunError` with exactly one such string, and both the
    weekly report's narration-unavailable warning and Quick Review's error
    just interpolate that exception, so building the full message here — the
    one place that already has the provider and the resolved executable — is
    what reaches both call sites without threading settings through them.

    When the executable is a default (the user never set narrator.executable),
    the advice points at installing the CLI rather than at a setting they never
    touched.
    """

    if executable_configured:
        advice = (
            f"set narrator.provider or narrator.executable "
            f"(currently {executable!r})"
        )
    else:
        advice = f"install the {provider} CLI or set narrator.provider / narrator.executable"
    message = f"{provider} narration failed ({detail}); {advice}"
    # A Codex desktop install ships its CLI outside PATH, under a private
    # directory a future release can relocate, so this points at the docs
    # instead of guessing the path.
    if (
        provider == "codex"
        and codex_home is not None
        and codex_home.is_dir()
        and shutil.which(executable) is None
    ):
        message += "; see the Codex desktop section of docs/configuration.md"
    return message


def finish_narrative_run(
    provider: str,
    executable: str,
    result: CommandResult,
    output_path: Path,
    *,
    fallback: str,
    codex_home: Path | None = None,
    empty_output_message: str,
    executable_configured: bool = False,
) -> str:
    """Turn a provider subprocess result into a narrative, or a NarrativeRunError.

    Every adapter ends the same way: read the output file (an OSError there
    becomes a NarrativeRunError), translate a non-zero exit into a
    `narrator_failure_message`, then reject an empty narrative with the
    provider-specific `empty_output_message`. The caller keeps its own
    try/except around `runner.run` so a launch OSError is still wrapped here.
    """

    try:
        narrative = ""
        if output_path.exists():
            narrative = output_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise NarrativeRunError(str(exc)) from exc
    if result.returncode != 0:
        raise NarrativeRunError(
            narrator_failure_message(
                provider,
                executable,
                failure_detail(result.stderr, narrative, fallback=fallback),
                codex_home=codex_home,
                executable_configured=executable_configured,
            )
        )
    if not narrative:
        raise NarrativeRunError(empty_output_message)
    return narrative


def run_with_workdir(workdir: Path | None, execute: Callable[[Path], str]) -> str:
    """Run `execute` in `workdir`, or in a fresh temporary one when absent.

    Every adapter needs the same workdir selection: an explicit workdir (how
    tests pin a directory to inspect) is used as-is, while the normal path
    gets a secure_temporary_directory() that is cleaned up on exit. OSError
    from creating or removing that directory becomes a NarrativeRunError so
    callers only need to catch one exception type.
    """

    if workdir is not None:
        return execute(workdir)
    try:
        with secure_temporary_directory() as temporary_workdir:
            return execute(temporary_workdir)
    except OSError as exc:
        raise NarrativeRunError(str(exc)) from exc
