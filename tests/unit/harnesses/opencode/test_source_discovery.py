import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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


@dataclass
class TruncatingRunner:
    """Reproduce OpenCode's documented pipe-buffer truncation.

    The real CLI writes the whole payload when its stdout is a file, and silently
    truncates at the OS pipe buffer — still exiting 0 — when it is a pipe. A fake
    that ignores `stdout_path` cannot tell those apart, which is why every
    pre-existing discovery test passed while `discover()` was losing rows.
    """

    payload: str
    pipe_buffer: int = 65536
    stdout_paths: list[Path | None] = field(default_factory=list)

    def run(self, args: list[str], *, stdout_path: Path | None = None) -> CommandResult:
        del args
        self.stdout_paths.append(stdout_path)
        if stdout_path is None:
            return CommandResult(0, self.payload[: self.pipe_buffer], "")
        stdout_path.write_text(self.payload, encoding="utf-8")
        return CommandResult(0, self.payload, "")


def test_discovery_survives_a_payload_larger_than_the_pipe_buffer() -> None:
    rows = [
        {
            "id": f"s{index}",
            "project_id": "project",
            "parent_id": None,
            "directory": "/repo",
            "title": "t" * 200,
            "time_created": 1,
            "time_updated": 2,
        }
        for index in range(400)
    ]
    payload = json.dumps(rows)
    # The bug only appears past the pipe buffer, so the fixture has to clear it.
    assert len(payload) > 65536

    runner = TruncatingRunner(payload=payload)
    source = OpenCodeCliSource(runner=runner, executable="opencode")
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    descriptors = source.discover(period)

    assert len(descriptors) == 400
    assert runner.stdout_paths[0] is not None
