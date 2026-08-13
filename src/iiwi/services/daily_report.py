"""Render and write finalized Daily Standup artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from iiwi.models.daily import DailyStandupDraft
from iiwi.renderers.daily_markdown import render_daily_standup
from iiwi.security.secure_files import atomic_secure_write


def daily_output_path(output_directory: Path, standup_date: date) -> Path:
    """Return the stable filename for a Daily Standup's calendar date."""

    return output_directory / f"daily-standup-{standup_date:%Y-%m-%d}.md"


@dataclass(frozen=True)
class DailyReportResult:
    """The rendered Daily artifact and its draft-derived coverage counts."""

    content: str
    output_path: Path | None
    repository_count: int
    session_count: int


class DailyReportService:
    """Keep Daily rendering pure and isolate artifact writing at one boundary."""

    def preview(self, draft: DailyStandupDraft) -> DailyReportResult:
        """Render a draft without writing or changing it."""

        return DailyReportResult(
            content=render_daily_standup(draft),
            output_path=None,
            repository_count=draft.repository_count,
            session_count=draft.session_count,
        )

    def generate(
        self,
        draft: DailyStandupDraft,
        *,
        output_path: Path,
    ) -> DailyReportResult:
        """Render and atomically replace the artifact for the reviewed standup date."""

        content = render_daily_standup(draft)
        atomic_secure_write(output_path, content, force=True)
        return DailyReportResult(
            content=content,
            output_path=output_path,
            repository_count=draft.repository_count,
            session_count=draft.session_count,
        )
