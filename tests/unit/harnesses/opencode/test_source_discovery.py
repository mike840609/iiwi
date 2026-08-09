from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.errors import HarnessSourceError
from iiwi.harnesses.opencode.source import OpenCodeCliSource
from iiwi.models.time_range import DateRange
from iiwi.process import CommandResult

TZ = ZoneInfo("Asia/Taipei")


def test_discovery_uses_interval_overlap_and_no_project_filter(fake_runner) -> None:
    fake_runner.stdout = '[{"id":"s1","time_created":1,"time_updated":2}]'
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    source.discover(period)

    query = fake_runner.calls[0][2]
    assert "time_created <" in query
    assert "COALESCE(time_updated, time_created, 0) >=" in query
    assert "project_id =" not in query
    assert "directory =" not in query
    assert fake_runner.calls[0][-2:] == ["--format", "json"]


def test_discovery_accepts_rows_wrapper(fake_runner) -> None:
    fake_runner.stdout = (
        '{"rows":[{"id":"s1","project_id":"p1","directory":"/repo","title":"Fix bug",'
        '"time_created":1000,"time_updated":2000}]}'
    )
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")
    period = DateRange(
        since=datetime(1970, 1, 1, tzinfo=TZ),
        until=datetime(1970, 1, 2, tzinfo=TZ),
    )

    descriptors = source.discover(period)

    assert descriptors[0].session_id == "s1"
    assert descriptors[0].working_directory_hint == "/repo"
    assert descriptors[0].project_id_hint == "p1"
    assert descriptors[0].title == "Fix bug"
    assert descriptors[0].created_at is not None


def test_discovery_raises_on_command_failure(fake_runner) -> None:
    fake_runner.set_result(
        "--format json",
        CommandResult(returncode=1, stdout="", stderr="database unavailable"),
    )
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    with pytest.raises(HarnessSourceError, match="database unavailable"):
        source.discover(period)


def test_discovery_includes_child_sessions_by_default(fake_runner) -> None:
    fake_runner.stdout = "[]"
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    source.discover(period)

    assert "parent_id IS NULL" not in fake_runner.calls[0][2]


def test_root_only_excludes_child_sessions(fake_runner) -> None:
    fake_runner.stdout = "[]"
    source = OpenCodeCliSource(
        runner=fake_runner,
        executable="opencode",
        root_only=True,
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    source.discover(period)

    query = fake_runner.calls[0][2]
    assert "AND parent_id IS NULL" in query
    assert query.rstrip().endswith("DESC;")
