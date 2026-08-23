import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from iiwi.harnesses.codex.thread_catalog import (
    discover_threads,
    find_state_database,
)
from iiwi.models.time_range import DateRange
from tests.codex_state_db import seconds, write_database

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    rollout = tmp_path / "sessions" / "rollout-root.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n", encoding="utf-8")
    archived = tmp_path / "archived_sessions" / "rollout-old.jsonl"
    archived.parent.mkdir(parents=True)
    archived.write_text("{}\n", encoding="utf-8")

    write_database(
        tmp_path / "state_5.sqlite",
        rows=[
            (
                "root-1",
                str(rollout),
                seconds(datetime(2026, 7, 21, tzinfo=TZ)),
                seconds(datetime(2026, 7, 22, tzinfo=TZ)),
                "/worktrees/agent",
                "Add retry",
                None,
                "user",
                0,
            ),
            (
                "sub-1",
                str(rollout),
                seconds(datetime(2026, 7, 21, 2, tzinfo=TZ)),
                seconds(datetime(2026, 7, 21, 3, tzinfo=TZ)),
                "/worktrees/agent",
                "",
                "Ampere",
                "subagent",
                0,
            ),
            (
                "archived-1",
                str(archived),
                seconds(datetime(2026, 7, 23, tzinfo=TZ)),
                seconds(datetime(2026, 7, 23, 1, tzinfo=TZ)),
                "/worktrees/assets",
                "Archived work",
                None,
                "user",
                1,
            ),
            (
                "stale-1",
                str(rollout),
                seconds(datetime(2026, 7, 1, tzinfo=TZ)),
                seconds(datetime(2026, 7, 2, tzinfo=TZ)),
                "/worktrees/agent",
                "Old work",
                None,
                "user",
                0,
            ),
            (
                "null-source-1",
                str(rollout),
                seconds(datetime(2026, 7, 21, 12, tzinfo=TZ)),
                seconds(datetime(2026, 7, 21, 13, tzinfo=TZ)),
                "/worktrees/agent",
                "NULL source work",
                None,
                None,
                0,
            ),
            (
                "automation-1",
                str(rollout),
                seconds(datetime(2026, 7, 21, 14, tzinfo=TZ)),
                seconds(datetime(2026, 7, 21, 15, tzinfo=TZ)),
                "/worktrees/agent",
                "Automation work",
                None,
                "automation",
                0,
            ),
        ],
        edges=[("root-1", "sub-1", "completed")],
    )
    return tmp_path


def test_finds_the_highest_versioned_state_database(home: Path) -> None:
    (home / "state_10.sqlite").write_text("", encoding="utf-8")
    (home / "state_2.sqlite").write_text("", encoding="utf-8")

    assert find_state_database(home) == home / "state_10.sqlite"


def test_returns_none_without_a_state_database(tmp_path: Path) -> None:
    assert find_state_database(tmp_path) is None


def test_discovers_sessions_overlapping_the_period(home: Path) -> None:
    descriptors = discover_threads(
        find_state_database(home), PERIOD, root_only=False
    )

    ids = {descriptor.session_id for descriptor in descriptors}
    assert ids == {"root-1", "sub-1", "archived-1", "null-source-1", "automation-1"}


def test_archived_sessions_are_not_excluded(home: Path) -> None:
    descriptors = discover_threads(
        find_state_database(home), PERIOD, root_only=False
    )

    assert "archived-1" in {descriptor.session_id for descriptor in descriptors}


def test_root_only_excludes_subagent_threads(home: Path) -> None:
    descriptors = discover_threads(find_state_database(home), PERIOD, root_only=True)

    ids = {descriptor.session_id for descriptor in descriptors}
    # Should exclude only subagent rows; NULL and other thread_source values survive.
    assert ids == {"root-1", "archived-1", "null-source-1", "automation-1"}
    assert "sub-1" not in ids


def test_descriptor_carries_metadata_and_parent_edge(home: Path) -> None:
    descriptors = discover_threads(
        find_state_database(home), PERIOD, root_only=False
    )
    by_id = {descriptor.session_id: descriptor for descriptor in descriptors}

    root = by_id["root-1"]
    assert root.harness == "codex"
    assert root.title == "Add retry"
    assert root.working_directory_hint == "/worktrees/agent"
    assert root.created_at == datetime(2026, 7, 21, tzinfo=TZ).astimezone(UTC)
    assert root.parent_session_id is None
    assert by_id["sub-1"].parent_session_id == "root-1"


def test_empty_title_falls_back_to_the_agent_nickname(home: Path) -> None:
    descriptors = discover_threads(
        find_state_database(home), PERIOD, root_only=False
    )
    by_id = {descriptor.session_id: descriptor for descriptor in descriptors}

    assert by_id["sub-1"].title == "Ampere"


def test_schema_drift_raises_for_the_caller_to_fall_back(tmp_path: Path) -> None:
    database = tmp_path / "state_5.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE unrelated (id TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(sqlite3.Error):
        discover_threads(database, PERIOD, root_only=False)


def test_timestamp_handles_extreme_integers_and_milliseconds() -> None:
    from iiwi.harnesses.codex.thread_catalog import _timestamp

    # Millisecond timestamp
    ms_timestamp = 1723500000000
    parsed = _timestamp(ms_timestamp)
    assert parsed is not None
    assert parsed.year == 2024

    # Out of range timestamp (year > 9999)
    huge_timestamp = 999999999999999999
    assert _timestamp(huge_timestamp) is None

