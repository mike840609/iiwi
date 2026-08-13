"""Same-day Daily Standup review-state persistence."""

from __future__ import annotations

import os
import stat
from datetime import date, datetime, timedelta

import pytest

from iiwi.daily_state import (
    DAILY_STATE_DIR_VARIABLE,
    cleanup_daily_state,
    daily_state_directory,
    daily_state_path,
    load_daily_draft,
    save_daily_draft,
)
from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)

STANDUP_DATE = date(2026, 8, 13)


def _draft() -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=STANDUP_DATE,
        scan_since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        scan_until=datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
        work_items=[
            DailyStandupWorkItem(
                id="daily-1",
                today=DailySectionItem(
                    statement="Ship reviewed Daily state",
                    source=DailyStatementSource.USER_ADDED,
                    user_edited=True,
                ),
            )
        ],
        warnings=["kept warning"],
        successful_harnesses=["codex"],
        repository_count=1,
        session_count=2,
    )


def test_state_directory_honors_environment_override(monkeypatch, tmp_path) -> None:
    override = tmp_path / "private-state"
    monkeypatch.setenv(DAILY_STATE_DIR_VARIABLE, str(override))

    assert daily_state_directory() == override
    assert daily_state_path(STANDUP_DATE) == override / "2026-08-13.json"


def test_save_and_load_round_trip_by_standup_date(tmp_path) -> None:
    original = _draft()

    save_daily_draft(original, directory=tmp_path)
    loaded = load_daily_draft(STANDUP_DATE, directory=tmp_path)

    assert daily_state_path(STANDUP_DATE, directory=tmp_path).name == "2026-08-13.json"
    assert loaded.warning is None
    assert loaded.draft == original


def test_missing_daily_state_is_an_empty_non_warning_result(tmp_path) -> None:
    loaded = load_daily_draft(STANDUP_DATE, directory=tmp_path)

    assert loaded.draft is None
    assert loaded.warning is None


@pytest.mark.parametrize(
    "content",
    ["not json", '{"standup_date": "not-a-date"}'],
)
def test_corrupt_daily_state_returns_visible_warning(tmp_path, content: str) -> None:
    path = daily_state_path(STANDUP_DATE, directory=tmp_path)
    path.write_text(content, encoding="utf-8")

    loaded = load_daily_draft(STANDUP_DATE, directory=tmp_path)

    assert loaded.draft is None
    assert loaded.warning is not None
    assert "2026-08-13.json" in loaded.warning


def test_non_utf8_daily_state_returns_visible_warning(tmp_path) -> None:
    path = daily_state_path(STANDUP_DATE, directory=tmp_path)
    path.write_bytes(b"\xff\xfe corrupt")

    loaded = load_daily_draft(STANDUP_DATE, directory=tmp_path)

    assert loaded.draft is None
    assert loaded.warning is not None
    assert "2026-08-13.json" in loaded.warning


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_saved_daily_state_directory_and_file_are_owner_only(tmp_path) -> None:
    directory = tmp_path / "daily"
    directory.mkdir(mode=0o755)

    save_daily_draft(_draft(), directory=directory)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(daily_state_path(STANDUP_DATE, directory=directory).stat().st_mode) == 0o600


def test_cleanup_removes_only_valid_date_files_older_than_retention(tmp_path) -> None:
    today = date(2026, 8, 13)
    expired = tmp_path / f"{today - timedelta(days=31):%Y-%m-%d}.json"
    boundary = tmp_path / f"{today - timedelta(days=30):%Y-%m-%d}.json"
    current = tmp_path / f"{today:%Y-%m-%d}.json"
    malformed = tmp_path / "2026-8-1.json"
    unrelated = tmp_path / "notes.json"
    for path in (expired, boundary, current, malformed, unrelated):
        path.write_text("state", encoding="utf-8")

    cleanup_daily_state(today, directory=tmp_path)

    assert not expired.exists()
    assert boundary.exists()
    assert current.exists()
    assert malformed.exists()
    assert unrelated.exists()


def test_cleanup_ignores_unlink_oserror(monkeypatch, tmp_path) -> None:
    expired = tmp_path / "2026-07-13.json"
    expired.write_text("state", encoding="utf-8")
    original_unlink = type(expired).unlink

    def fail_for_expired(path, *args, **kwargs) -> None:
        if path == expired:
            raise OSError("read-only filesystem")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(expired), "unlink", fail_for_expired)

    cleanup_daily_state(STANDUP_DATE, directory=tmp_path)

    assert expired.exists()
