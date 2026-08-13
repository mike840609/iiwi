"""Convert canonical session activities into provenance-aware evidence."""

from __future__ import annotations

from collections.abc import Mapping

from iiwi.extraction.rules import (
    ASSISTANT_COMPLETION_PATTERN,
    COMMAND_TOOL_NAMES,
    FILE_TOOL_NAMES,
    is_meaningful_user_text,
    is_verification_command,
)
from iiwi.models.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    SessionEvidence,
)
from iiwi.models.repository import ResolvedSession
from iiwi.models.session import ActivityType, SessionActivity

# An evidence item is a pointer back to work, not a copy of it. Both harnesses put
# a whole tool input into `SessionActivity.content` — a Claude Code `input.command`
# holding a heredoc body carries the file it writes, and there is no upstream
# `--sanitize` on that path — so the cap lives here, where every item is built.
EVIDENCE_TEXT_MAX_LENGTH = 300

# A path that survives the `_file_path` fallback below must fit in one report line.
_PATH_MAX_LENGTH = 512
_PATH_REJECTED_CHARACTERS = frozenset("{}[]\"'`<>|*?")

# Shell forms that make stderr empty by construction rather than by success.
# "2>" already subsumes "2>&1", "2>/dev/null", and "2>>file"; "&>" and "|&" are
# bash's send-both-streams forms, which redirect stderr without naming it.
_STDERR_REDIRECTION_MARKERS = ("2>", "&>", "|&")


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip()


def _truncate(text: str) -> str:
    """Cap one evidence item, marking the cut so a reader sees text was removed."""

    if len(text) <= EVIDENCE_TEXT_MAX_LENGTH:
        return text
    return text[: EVIDENCE_TEXT_MAX_LENGTH - 1].rstrip() + "…"


def _is_plausible_path(value: str) -> bool:
    """Reject fallback text that is not a path.

    `_file_path` falls back to the activity's content, which for a file tool call
    carrying no path key is the mapper's serialized input — for a `Write`-shaped
    call that is the file's own `content`. Rendering that under "Key Files" would
    copy source into the report, so anything unlike a single path is refused.
    """

    if not value or len(value) > _PATH_MAX_LENGTH:
        return False
    if any(character in _PATH_REJECTED_CHARACTERS for character in value):
        return False
    if any(character.isspace() for character in value):
        return False
    return "/" in value or "\\" in value or "." in value


def _nested_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _exit_code(activity: SessionActivity) -> int | None:
    direct = activity.metadata.get("exit_code")
    if isinstance(direct, int):
        return direct
    state = _nested_mapping(activity.metadata.get("state"))
    for key in ("exit_code", "exitCode", "code"):
        value = state.get(key)
        if isinstance(value, int):
            return value
    metadata = _nested_mapping(state.get("metadata"))
    for key in ("exit", "exit_code", "exitCode"):
        value = metadata.get(key)
        if isinstance(value, int):
            return value
    return None


def _observed_failure(activity: SessionActivity) -> bool | None:
    """Return whether the command was observed to fail, or None if unobserved.

    Two harnesses record two different real signals. OpenCode reports a process
    exit code. Claude Code reports no exit code, but it does set `is_error` on
    the tool result, which for a shell tool is the same observation under
    another name. Neither is inferred, so both support the same conclusions.

    Where both exist the exit code wins: it distinguishes *how* a command
    failed, which `is_error` flattens to a boolean.
    """

    exit_code = _exit_code(activity)
    if exit_code is not None:
        return exit_code != 0
    failed = activity.metadata.get("tool_failed")
    return failed if isinstance(failed, bool) else None


def _file_path(activity: SessionActivity) -> str | None:
    for source in (
        activity.metadata,
        _nested_mapping(activity.metadata.get("state")),
        _nested_mapping(_nested_mapping(activity.metadata.get("state")).get("input")),
    ):
        for key in ("path", "file", "file_path", "filePath"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    content = _normalize(activity.content)
    return content if _is_plausible_path(content) else None


def _item(
    *,
    text: str,
    activity: SessionActivity,
    confidence: EvidenceConfidence,
    extraction_method: str,
    status: EvidenceStatus = EvidenceStatus.UNKNOWN,
) -> EvidenceItem:
    return EvidenceItem(
        text=_truncate(_normalize(text)),
        source_activity_ids=[activity.activity_id],
        confidence=confidence,
        extraction_method=extraction_method,
        status=status,
    )


def _append_unique(
    items: list[EvidenceItem],
    candidate: EvidenceItem,
    *,
    repository_id: str,
) -> None:
    key = (candidate.text.casefold(), repository_id)
    existing = {(item.text.casefold(), repository_id) for item in items}
    if key not in existing:
        items.append(candidate)


def _redirects_stderr(command: str) -> bool:
    """Detect a command whose empty stderr is an artefact of its own redirection.

    `pytest 2>&1 | tail` and `ruff check . 2>/dev/null` leave stderr empty no
    matter what happened, so `stderr_empty` carries no information about them.
    Measured against real transcripts, 96 of 113 inferences came from commands
    shaped like this.

    ponytail: plain substring match, not shell-aware. A heredoc that *writes about*
    redirection — `cat <<EOF > doc.md` containing the text `cmd &> file` — matches
    too. That costs a suppressed annotation on a command whose outcome was already
    unobserved, never a wrong claim, and never the `commands` list, so the trade is
    worth it. Parse the shell only if a real verification result goes missing.
    """

    return any(marker in command for marker in _STDERR_REDIRECTION_MARKERS)


def _append_stderr_heuristic(
    evidence: SessionEvidence,
    *,
    activity: SessionActivity,
    content: str,
    repository_id: str,
) -> None:
    """Record what a command was, not how it ended, when nothing was observed.

    This is the last resort, reached only when neither harness signal is
    present: no exit code and no `is_error`. Empty stderr is then all that is
    left, and it is weak — pytest writes `FAILED` to stdout and `ruff` reports
    violations on stdout. Nothing here claims success. A command that redirects
    stderr is skipped outright, because for it the signal is not weak but absent.

    Non-empty stderr is deliberately *not* treated as failure. `git` writes to
    stderr on success constantly, so it produced 31 items of `git stash` and
    `cd … && uv sync` noise against real transcripts — none of which the report
    renders, while all of them travelled in the outbound LLM request. Only an
    observed outcome makes a failure worth recording.
    """

    if _redirects_stderr(content):
        return

    if (
        activity.metadata.get("stderr_empty") is True
        and activity.metadata.get("interrupted") is not True
        and is_verification_command(content)
    ):
        _append_unique(
            evidence.outcomes,
            _item(
                text=f"Ran verification command: {content}",
                activity=activity,
                confidence=EvidenceConfidence.MEDIUM,
                extraction_method="stderr_heuristic",
                status=EvidenceStatus.UNKNOWN,
            ),
            repository_id=repository_id,
        )


def extract_evidence(resolved: ResolvedSession) -> SessionEvidence:
    """Extract conservative evidence from one repository-resolved session."""

    evidence = SessionEvidence(
        harness=resolved.session.harness,
        session_id=resolved.session.session_id,
        repository_id=resolved.repository.repository_id,
        # A harness-recorded title has no length bound of its own: Codex's
        # `threads.title` is the verbatim first user message, and the longest on
        # a real machine is 1,478 characters. Capping here rather than in the
        # summarizer is what also covers the outbound LLM request, which sends
        # this whole model.
        title=_truncate(_normalize(resolved.session.title)) if resolved.session.title else None,
        working_directory=resolved.session.working_directory,
    )
    repository_id = resolved.repository.repository_id

    for activity in resolved.session.activities:
        content = _normalize(activity.content)
        if activity.activity_type == ActivityType.USER_MESSAGE and is_meaningful_user_text(content):
            _append_unique(
                evidence.goals,
                _item(
                    text=content,
                    activity=activity,
                    confidence=EvidenceConfidence.HIGH,
                    extraction_method="user_message",
                    status=EvidenceStatus.IN_PROGRESS,
                ),
                repository_id=repository_id,
            )
            continue

        tool_name = (activity.tool_name or "").casefold()
        is_command = activity.activity_type == ActivityType.COMMAND or (
            activity.activity_type == ActivityType.TOOL_CALL and tool_name in COMMAND_TOOL_NAMES
        )
        if is_command and content:
            _append_unique(
                evidence.commands,
                _item(
                    text=content,
                    activity=activity,
                    confidence=EvidenceConfidence.HIGH,
                    extraction_method="tool_command",
                ),
                repository_id=repository_id,
            )
            failed = _observed_failure(activity)
            if failed is True:
                _append_unique(
                    evidence.errors,
                    _item(
                        text=content,
                        activity=activity,
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="observed_command_failure",
                        status=EvidenceStatus.BLOCKED,
                    ),
                    repository_id=repository_id,
                )
            elif failed is False and is_verification_command(content):
                _append_unique(
                    evidence.outcomes,
                    _item(
                        text=f"Verification passed: {content}",
                        activity=activity,
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="successful_verification_command",
                        status=EvidenceStatus.COMPLETED,
                    ),
                    repository_id=repository_id,
                )
            elif failed is None:
                _append_stderr_heuristic(
                    evidence,
                    activity=activity,
                    content=content,
                    repository_id=repository_id,
                )
            continue

        if activity.activity_type in {ActivityType.FILE_CHANGE, ActivityType.TOOL_CALL} and (
            activity.activity_type == ActivityType.FILE_CHANGE or tool_name in FILE_TOOL_NAMES
        ):
            path = _file_path(activity)
            if path:
                _append_unique(
                    evidence.files_changed,
                    _item(
                        text=path,
                        activity=activity,
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="file_tool",
                    ),
                    repository_id=repository_id,
                )
            continue

        if (
            activity.activity_type == ActivityType.ASSISTANT_MESSAGE
            and content
            and ASSISTANT_COMPLETION_PATTERN.search(content)
        ):
            _append_unique(
                evidence.outcomes,
                _item(
                    text=content,
                    activity=activity,
                    confidence=EvidenceConfidence.LOW,
                    extraction_method="assistant_claim",
                    status=EvidenceStatus.UNKNOWN,
                ),
                repository_id=repository_id,
            )

    return evidence
