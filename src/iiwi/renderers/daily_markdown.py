"""Pure Markdown rendering for reviewed Daily Standup drafts."""

from __future__ import annotations

from iiwi.models.daily import DailySection, DailyStandupDraft


def render_daily_standup(draft: DailyStandupDraft) -> str:
    """Render the reader-facing Daily Standup artifact without changing ``draft``."""

    lines = [f"# Daily Standup — {draft.standup_date:%Y-%m-%d}", ""]
    lines.extend(f"> Warning: {warning}" for warning in draft.coverage_warnings)
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
                repositories = sorted(set(work.repository_ids))
                prefix = f"[{', '.join(repositories)}] " if repositories else ""
                lines.append(f"- {prefix}{item.statement}")
        if index != len(sections) - 1:
            lines.append("")

    return "\n".join(lines) + "\n"
