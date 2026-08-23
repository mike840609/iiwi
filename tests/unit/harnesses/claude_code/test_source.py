import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from iiwi.errors import SessionParseError
from iiwi.harnesses.claude_code.source import ClaudeCodeFileSource
from iiwi.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


def _record(uuid: str, timestamp: str, cwd: str = "/repo/main") -> str:
    return json.dumps(
        {
            "type": "user",
            "origin": {"kind": "human"},
            "message": {"role": "user", "content": f"work item {uuid}"},
            "uuid": uuid,
            "timestamp": timestamp,
            "cwd": cwd,
            "gitBranch": "main",
        }
    )


def _write_session(path: Path, *, timestamp: str, mtime: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_record("u-1", timestamp) + "\n", encoding="utf-8")
    stamp = mtime.timestamp()
    os.utime(path, (stamp, stamp))


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    _write_session(
        root / "-repo-main" / "sess-in.jsonl",
        timestamp="2026-07-21T01:00:00.000Z",
        mtime=datetime(2026, 7, 21, tzinfo=TZ),
    )
    _write_session(
        root / "-repo-main" / "sess-stale.jsonl",
        timestamp="2026-07-01T01:00:00.000Z",
        mtime=datetime(2026, 7, 1, tzinfo=TZ),
    )
    _write_session(
        root / "-repo-main" / "sess-in" / "subagents" / "agent-abc.jsonl",
        timestamp="2026-07-21T02:00:00.000Z",
        mtime=datetime(2026, 7, 21, tzinfo=TZ),
    )
    (root / "-repo-main" / "sess-in" / "subagents" / "agent-abc.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": "Implement Task 1"}),
        encoding="utf-8",
    )
    return root


def test_discover_skips_files_last_touched_before_the_period(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects)

    ids = {descriptor.session_id for descriptor in source.discover(PERIOD)}

    assert "sess-in" in ids
    assert "sess-stale" not in ids


def test_discover_includes_subagents_with_parent_and_meta_title(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects)

    subagent = next(
        descriptor
        for descriptor in source.discover(PERIOD)
        if descriptor.session_id == "agent-abc"
    )

    assert subagent.parent_session_id == "sess-in"
    assert subagent.title == "Implement Task 1"
    assert subagent.project_id_hint == "-repo-main"


def test_root_only_excludes_subagents(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects, root_only=True)

    ids = {descriptor.session_id for descriptor in source.discover(PERIOD)}

    assert ids == {"sess-in"}


def test_discover_returns_a_usable_source_location(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects)

    descriptor = next(
        item for item in source.discover(PERIOD) if item.session_id == "sess-in"
    )

    assert descriptor.source_location is not None
    assert Path(descriptor.source_location).is_file()
    assert descriptor.harness == "claude-code"


def test_load_returns_a_mapped_session(projects: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=projects)
    descriptor = next(
        item for item in source.discover(PERIOD) if item.session_id == "sess-in"
    )

    session = source.load(descriptor)

    assert session.harness == "claude-code"
    assert session.working_directory == "/repo/main"
    assert [activity.content for activity in session.activities] == ["work item u-1"]


def test_load_skips_a_torn_trailing_line(projects: Path) -> None:
    """Claude Code appends live, so the last line can be half-written."""

    path = projects / "-repo-main" / "sess-in.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"user","origin":{"kind":"hum')
    source = ClaudeCodeFileSource(projects_directory=projects)
    descriptor = next(
        item for item in source.discover(PERIOD) if item.session_id == "sess-in"
    )

    session = source.load(descriptor)

    assert len(session.activities) == 1


def test_load_without_source_location_raises(projects: Path) -> None:
    from iiwi.models.session import SessionDescriptor

    source = ClaudeCodeFileSource(projects_directory=projects)

    with pytest.raises(SessionParseError):
        source.load(SessionDescriptor(harness="claude-code", session_id="ghost"))


def test_discover_on_a_missing_projects_directory_returns_nothing(tmp_path: Path) -> None:
    source = ClaudeCodeFileSource(projects_directory=tmp_path / "absent")

    assert source.discover(PERIOD) == []


def test_discover_excludes_a_session_created_after_the_period(tmp_path: Path) -> None:
    """A session that started after the window ends is skipped at discovery.

    The mtime prefilter cannot catch this one: the file was touched inside the
    period but every record in it postdates `period.until`. A bug here drops
    in-period sessions rather than merely missing a prefilter, so it is pinned.
    """

    root = tmp_path / "projects"
    _write_session(
        root / "-repo-main" / "sess-future.jsonl",
        timestamp="2026-07-28T01:00:00.000Z",
        mtime=datetime(2026, 7, 26, tzinfo=TZ),
    )
    source = ClaudeCodeFileSource(projects_directory=root)

    assert source.discover(PERIOD) == []


def test_subagent_meta_with_invalid_utf8_does_not_crash_discovery(tmp_path: Path) -> None:
    source_dir = tmp_path / "projects" / "p1"
    subagent_dir = source_dir / "subagents"
    subagent_dir.mkdir(parents=True)
    jsonl_file = subagent_dir / "agent-1.jsonl"
    jsonl_file.write_text('{"type": "user"}\n', encoding="utf-8")
    meta_file = subagent_dir / "agent-1.meta.json"
    meta_file.write_bytes(b'{"description": "\xff\xfe invalid"}')

    source = ClaudeCodeFileSource(projects_directory=tmp_path / "projects")
    title = source._subagent_title(jsonl_file)
    assert title is None or isinstance(title, str)

