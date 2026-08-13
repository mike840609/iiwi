"""Pure Markdown rendering for reviewed Daily Standup drafts."""

from __future__ import annotations

import re

from iiwi.models.daily import DailySection, DailyStandupDraft
from iiwi.security.redactor import redact_text

_INLINE_MARKDOWN = re.compile(r"([\\`*_\[\]<>])")


def safe_daily_text(value: str) -> str:
    """Render one redacted literal line consistently in review and Markdown."""

    single_line = " ".join(redact_text(value).splitlines())
    return _INLINE_MARKDOWN.sub(r"\\\1", single_line)


def render_daily_standup(draft: DailyStandupDraft) -> str:
    """Render the reader-facing Daily Standup artifact without changing ``draft``."""

    lines = [f"# Daily Standup — {draft.standup_date:%Y-%m-%d}", ""]
    lines.extend(
        f"> Warning: {safe_daily_text(warning)}"
        for warning in draft.coverage_warnings
    )
    if draft.coverage_warnings:
        lines.append("")

    sections = (
        (DailySection.YESTERDAY, "Yesterday"),
        (DailySection.TODAY, "Today"),
        (DailySection.BLOCKERS, "Blockers"),
    )
    for index, (section, heading) in enumerate(sections):
        lines.append(f"## {heading}")
        items = [
            (work, item)
            for work, item in draft.ordered_items(section)
            if item.included
        ]
        if not items:
            lines.append("- None")
        else:
            for work, item in items:
                repositories = sorted(
                    {safe_daily_text(repository) for repository in work.repository_ids}
                )
                prefix = f"[{', '.join(repositories)}] " if repositories else ""
                lines.append(f"- {prefix}{safe_daily_text(item.statement)}")
        if index != len(sections) - 1:
            lines.append("")

    return "\n".join(lines) + "\n"
