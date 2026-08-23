"""Raw grouped-transcript builder for the LLM report engine.

The narrative report feeds a locally installed `opencode run` with a plain
transcript of what happened, grouped by repository, rather than pre-digested
structured evidence. The model then writes the prose; we keep the raw material
redacted and local-only.
"""

from __future__ import annotations

from datetime import datetime

from iiwi.models.repository import ResolvedSession
from iiwi.models.session import ActivityType
from iiwi.models.time_range import DateRange
from iiwi.security.redactor import redact_text


def _session_sort_key(resolved: ResolvedSession) -> datetime:
    stamps = [
        activity.timestamp
        for activity in resolved.session.activities
        if activity.timestamp is not None
    ]
    return max(stamps, default=resolved.session.created_at or datetime.min)


def build_grouped_transcript(
    *,
    sessions_by_repository: dict[str, list[ResolvedSession]],
    period: DateRange,
    generated_at: datetime,
    include_subagents: bool,
    sanitized: bool,
    usage_text: str | None = None,
) -> str:
    """Render a redacted, repository-grouped transcript of the session content.

    Only user and assistant message activities are included; tool calls,
    commands, and other structured activity kinds are dropped because the model
    is asked to reason from the conversation, not from tool scaffolding.
    Usage statistics, when available, are appended as a final `## Usage`
    section so the model sees the same data the FULL prompt asks it to
    summarize, from the same `--file`.
    """

    ordered_groups = sorted(
        sessions_by_repository.items(),
        key=lambda item: item[1][0].repository.display_name.casefold()
        if item[1]
        else item[0].casefold(),
    )
    session_count = sum(len(items) for items in sessions_by_repository.values())

    lines: list[str] = [
        "# Iiwi sessions grouped by repository",
        "",
        f"- Period: {period.since.date().isoformat()} to {period.until.date().isoformat()}",
        f"- Generated: {generated_at.isoformat()}",
        f"- Projects: {len(sessions_by_repository)}",
        f"- Sessions: {session_count}",
        f"- Subagent sessions included: {'yes' if include_subagents else 'no'}",
        f"- Sanitized exports: {'yes' if sanitized else 'no'}",
        "",
    ]

    for _repository_id, resolved_items in ordered_groups:
        if not resolved_items:
            continue
        first = resolved_items[0].repository
        lines.append(f"## Project: {first.display_name}")
        lines.append("")
        lines.append(f"- Repository identity: `{first.repository_id}`")
        if first.working_directory:
            lines.append(f"- Directory: `{first.working_directory}`")
        if first.branch:
            lines.append(f"- Branch: {first.branch}")
        lines.append("")

        for resolved in sorted(resolved_items, key=_session_sort_key, reverse=True):
            session = resolved.session
            title = session.title or session.session_id
            lines.append(f"### Session: {title}")
            lines.append("")
            lines.append(f"- Session ID: `{session.session_id}`")
            lines.append("")
            for activity in session.activities:
                if activity.activity_type is ActivityType.USER_MESSAGE:
                    label = "user"
                elif activity.activity_type is ActivityType.ASSISTANT_MESSAGE:
                    label = "assistant"
                else:
                    continue
                lines.append(f"**{label}:**")
                lines.append("")
                lines.append(redact_text(activity.content))
                lines.append("")

    if usage_text:
        lines += [
            "## Usage",
            "",
            "```text",
            usage_text,
            "```",
            "",
        ]

    return redact_text("\n".join(lines).rstrip() + "\n")
