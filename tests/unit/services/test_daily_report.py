"""Tests for the Daily Standup rendering/write boundary."""

from datetime import date, datetime
from pathlib import Path

import pytest

from iiwi.errors import ReportOutputError
from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.services.daily_report import DailyReportService, daily_output_path


def _draft() -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=date(2026, 8, 13),
        scan_since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        scan_until=datetime.fromisoformat("2026-08-13T09:00:00+08:00"),
        work_items=[
            DailyStandupWorkItem(
                id="daily",
                repository_ids=["iiwi"],
                today=DailySectionItem(
                    statement="Implement the Daily Standup draft.",
                    source=DailyStatementSource.ACTIVITY_TODAY,
                ),
            )
        ],
        repository_count=4,
        session_count=7,
    )


def test_daily_output_path_uses_the_standup_date(tmp_path: Path) -> None:
    """This fails if same-day reports get an unstable or non-date-based name."""

    assert daily_output_path(tmp_path, date(2026, 8, 13)) == (
        tmp_path / "daily-standup-2026-08-13.md"
    )


def test_preview_and_generate_return_identical_content_and_replace_same_day_file(
    tmp_path: Path,
) -> None:
    """This fails if preview diverges or Generate refuses/reuses an existing file."""

    service = DailyReportService()
    draft = _draft()
    path = daily_output_path(tmp_path, draft.standup_date)
    path.write_text("old same-day report", encoding="utf-8")

    preview = service.preview(draft)
    generated = service.generate(draft, output_path=path)

    assert preview.content == generated.content == path.read_text(encoding="utf-8")
    assert preview.output_path is None
    assert generated.output_path == path
    assert (generated.repository_count, generated.session_count) == (4, 7)


def test_generate_propagates_a_secure_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This fails if report-output errors are hidden or converted at the boundary."""

    def fail_write(path: Path, content: str, *, force: bool) -> None:
        raise ReportOutputError("disk unavailable")

    monkeypatch.setattr("iiwi.services.daily_report.atomic_secure_write", fail_write)

    with pytest.raises(ReportOutputError, match="disk unavailable"):
        DailyReportService().generate(_draft(), output_path=tmp_path / "daily.md")
