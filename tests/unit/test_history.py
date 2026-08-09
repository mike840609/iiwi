"""Report history persistence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_worklog.history import HistoryEntry, append_history, read_history

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
    assert str(entries[1].output_path) == "reports/other.md"


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


def test_history_entry_serialises_to_isoformat_datetimes(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    append_history(_entry(), path=path)

    raw = json.loads(path.read_text(encoding="utf-8").strip())

    assert raw["generated_at"] == "2026-08-03T09:00:00+08:00"
    assert raw["since"] == "2026-07-27T00:00:00+08:00"
    assert raw["output_path"] == "reports/worklog-2026-07-27_2026-08-03.md"
