"""The narration contract shared by every provider adapter.

The weekly narrative is produced by a coding-agent CLI the user already has
installed, so no API key, network endpoint, or extra dependency is required. A
prompt and a grouped transcript go to a subprocess; the prose comes back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from iiwi.models.report_options import DetailLevel
from iiwi.process import CommandResult
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


class NarrativeRunError(Exception):
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
    """

    return f"{IIWI_SESSION_TITLE_PREFIX}{title}\n\n{prompt}"
