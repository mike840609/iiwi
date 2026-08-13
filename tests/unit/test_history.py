"""Report history persistence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import iiwi.history as history_module
from iiwi.history import (
    HistoryEntry,
    append_history,
    history_to_json,
    read_history,
)

TZ = ZoneInfo("Asia/Taipei")


def _entry(generated_at: str = "2026-08-03T09:00:00+08:00") -> HistoryEntry:
    return HistoryEntry(
        generated_at=datetime.fromisoformat(generated_at),
        harness="opencode",
        since=datetime(2026, 7, 27, 0, 0, tzinfo=TZ),
        until=datetime(2026, 8, 3, 0, 0, tzinfo=TZ),
        output_path=Path("reports/worklog-2026-07-27_2026-08-03.md"),
        repository_count=3,
        session_count=41,
        narrative=True,
        detail="full",
    )


def test_append_then_read_round_trips_in_order(tmp_path) -> None:
    first = _entry()
    second = HistoryEntry(
        generated_at=datetime(2026, 8, 4, 9, 0, tzinfo=TZ),
        harness="claude-code",
        since=first.since,
        until=first.until,
        output_path=Path("reports/other.md"),
        repository_count=1,
        session_count=2,
        narrative=False,
        detail="brief",
    )
    path = tmp_path / "history.jsonl"

    append_history(first, path=path)
    append_history(second, path=path)
    entries = read_history(path=path)

    assert [entry.generated_at for entry in entries] == [
        first.generated_at,
        second.generated_at,
    ]
    assert entries[0].harness == "opencode"
    assert entries[0].narrative is True
    assert entries[0].detail == "full"
    assert entries[1].harness == "claude-code"
    assert entries[1].narrative is False
    assert entries[1].detail == "brief"
    assert str(entries[1].output_path) == str(
        Path("reports/other.md").resolve()
    )


def test_append_creates_the_parent_directory(tmp_path) -> None:
    path = tmp_path / "data" / "nested" / "history.jsonl"

    append_history(_entry(), path=path)

    assert path.is_file()
    assert len(read_history(path=path)) == 1


def test_read_skips_corrupt_lines(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(
        "this is not json\n" + json.dumps(_entry().__dict__, default=str) + "\n",
        encoding="utf-8",
    )

    entries = read_history(path=path)

    assert len(entries) == 1
    assert entries[0].session_count == 41


def test_missing_history_file_reads_empty(tmp_path) -> None:
    assert read_history(path=tmp_path / "absent.jsonl") == []


def test_history_to_json_lists_the_newest_first() -> None:
    """`history --json` renders newest first, the same order as the table."""

    older = _entry()
    newer = HistoryEntry(
        generated_at=datetime(2026, 8, 4, 9, 0, tzinfo=TZ),
        harness="claude-code",
        since=older.since,
        until=older.until,
        output_path=Path("reports/other.md"),
        repository_count=1,
        session_count=2,
        narrative=False,
        detail="brief",
    )

    raw = json.loads(history_to_json([older, newer]))

    assert [entry["generated_at"] for entry in raw] == [
        newer.generated_at.isoformat(),
        older.generated_at.isoformat(),
    ]


def test_history_entry_serialises_to_isoformat_datetimes(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    append_history(_entry(), path=path)

    raw = json.loads(path.read_text(encoding="utf-8").strip())

    assert raw["generated_at"] == "2026-08-03T09:00:00+08:00"
    assert raw["since"] == "2026-07-27T00:00:00+08:00"
    assert raw["output_path"] == str(
        Path("reports/worklog-2026-07-27_2026-08-03.md").resolve()
    )


def test_append_resolves_relative_output_paths(tmp_path) -> None:
    path = tmp_path / "history.jsonl"

    append_history(_entry(), path=path)

    entries = read_history(path=path)
    assert entries[0].output_path == Path(
        "reports/worklog-2026-07-27_2026-08-03.md"
    ).resolve()
    assert entries[0].output_path.is_absolute()


def test_append_leaves_absolute_output_paths_unchanged(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    target = (tmp_path / "reports" / "worklog.md").resolve()
    entry = HistoryEntry(
        generated_at=datetime(2026, 8, 3, 9, 0, tzinfo=TZ),
        harness="opencode",
        since=datetime(2026, 7, 27, 0, 0, tzinfo=TZ),
        until=datetime(2026, 8, 3, 0, 0, tzinfo=TZ),
        output_path=target,
        repository_count=1,
        session_count=2,
        narrative=True,
        detail="full",
    )

    append_history(entry, path=path)

    assert read_history(path=path)[0].output_path == target


def test_append_expands_tilde_output_paths_against_the_writing_home(
    tmp_path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("USERPROFILE", raising=False)
    path = tmp_path / "history.jsonl"
    entry = HistoryEntry(
        generated_at=datetime(2026, 8, 3, 9, 0, tzinfo=TZ),
        harness="opencode",
        since=datetime(2026, 7, 27, 0, 0, tzinfo=TZ),
        until=datetime(2026, 8, 3, 0, 0, tzinfo=TZ),
        output_path=Path("~/worklog.md"),
        repository_count=1,
        session_count=2,
        narrative=True,
        detail="full",
    )

    append_history(entry, path=path)

    assert read_history(path=path)[0].output_path == (home / "worklog.md").resolve()


def test_old_relative_entries_read_back_verbatim(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps(_entry().__dict__, default=str) + "\n",
        encoding="utf-8",
    )

    entries = read_history(path=path)

    assert str(entries[0].output_path) == "reports/worklog-2026-07-27_2026-08-03.md"


def test_old_json_line_defaults_to_a_single_harness_report(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-03T09:00:00+08:00",
                "harness": "opencode",
                "since": "2026-07-27T00:00:00+08:00",
                "until": "2026-08-03T00:00:00+08:00",
                "output_path": "reports/legacy.md",
                "repository_count": 3,
                "session_count": 41,
                "narrative": True,
                "detail": "full",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    entry = read_history(path=path)[0]

    assert entry.kind is history_module.HistoryKind.REPORT
    assert entry.effective_harnesses == ("opencode",)
    assert entry.unavailable_harnesses == ()


def test_daily_standup_round_trips_first_class_metadata(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    entry = HistoryEntry(
        generated_at=datetime(2026, 8, 13, 9, 0, tzinfo=TZ),
        since=datetime(2026, 8, 12, 0, 0, tzinfo=TZ),
        until=datetime(2026, 8, 13, 0, 0, tzinfo=TZ),
        output_path=Path("reports/daily-standup-2026-08-13.md"),
        repository_count=4,
        session_count=12,
        kind=history_module.HistoryKind.DAILY_STANDUP,
        harnesses=("opencode", "codex"),
        unavailable_harnesses=("claude-code",),
    )

    append_history(entry, path=path)
    restored = read_history(path=path)[0]

    assert restored.kind is history_module.HistoryKind.DAILY_STANDUP
    assert restored.harness is None
    assert restored.narrative is None
    assert restored.detail is None
    assert restored.harnesses == ("opencode", "codex")
    assert restored.effective_harnesses == ("opencode", "codex")
    assert restored.unavailable_harnesses == ("claude-code",)
    assert restored.output_path == Path("reports/daily-standup-2026-08-13.md").resolve()
    assert restored.output_path.is_absolute()
