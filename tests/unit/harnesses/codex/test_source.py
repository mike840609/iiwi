import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from iiwi.errors import HarnessSourceError
from iiwi.harnesses.codex.source import CodexSource, describe_discovery
from iiwi.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    rollout = tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-root.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(
        '{"timestamp":"2026-07-20T17:00:00.000Z","type":"session_meta",'
        '"payload":{"session_id":"root-1","timestamp":"2026-07-20T17:00:00.000Z",'
        '"cwd":"/worktrees/agent","thread_source":"user"}}\n',
        encoding="utf-8",
    )
    import os

    stamp = datetime(2026, 7, 22, tzinfo=TZ).timestamp()
    os.utime(rollout, (stamp, stamp))
    return tmp_path


def test_missing_home_directory_is_a_harness_error(tmp_path: Path) -> None:
    source = CodexSource(home_directory=tmp_path / "absent")

    with pytest.raises(HarnessSourceError):
        source.discover(PERIOD)


def test_falls_back_to_the_rollout_scan_without_a_database(home: Path) -> None:
    descriptors = CodexSource(home_directory=home).discover(PERIOD)

    assert [descriptor.session_id for descriptor in descriptors] == ["root-1"]


def test_falls_back_to_the_rollout_scan_on_schema_drift(home: Path) -> None:
    connection = sqlite3.connect(home / "state_5.sqlite")
    connection.execute("CREATE TABLE unrelated (id TEXT)")
    connection.commit()
    connection.close()

    descriptors = CodexSource(home_directory=home).discover(PERIOD)

    assert [descriptor.session_id for descriptor in descriptors] == ["root-1"]


def test_discovers_from_database_not_rollout(home: Path) -> None:
    """Verify discover() uses the state database when available.

    This test guards against implementations that unconditionally use
    discover_rollouts without actually checking the database. The seeded
    session id (db-only-1) exists only in the database, not the rollout
    file. If discover() incorrectly skipped the database, this test would
    fail because root-1 would be returned instead.
    """
    from tests.codex_state_db import seconds, write_database

    db_timestamp = seconds(datetime(2026, 7, 22, 12, tzinfo=TZ))
    write_database(
        home / "state_5.sqlite",
        rows=[
            (
                "db-only-1",
                str(home / "sessions" / "2026" / "07" / "22" / "db-only.jsonl"),
                db_timestamp,
                db_timestamp,
                "/worktrees/agent",
                "Database-only session",
                None,
                "user",
                0,
            ),
        ],
    )

    descriptors = CodexSource(home_directory=home).discover(PERIOD)
    session_ids = [descriptor.session_id for descriptor in descriptors]

    # Must return the database session, not the rollout session, proving
    # the database path was actually taken
    assert session_ids == ["db-only-1"]
    assert "root-1" not in session_ids


def test_describes_the_discovery_path(home: Path) -> None:
    assert describe_discovery(home) == "directory scan"

    (home / "state_5.sqlite").write_text("", encoding="utf-8")

    assert describe_discovery(home) == "state_5.sqlite"
