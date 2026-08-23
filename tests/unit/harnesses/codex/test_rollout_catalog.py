import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from iiwi.harnesses.codex.rollout_catalog import discover_rollouts
from iiwi.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


def _session_meta(
    session_id: str,
    timestamp: str,
    *,
    id: str | None = None,
    cwd: str = "/worktrees/agent",
    thread_source: str = "user",
    parent: str | None = None,
    nickname: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "session_id": session_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "thread_source": thread_source,
        "parent_thread_id": parent,
        "agent_nickname": nickname,
    }
    if id is not None:
        payload["id"] = id
    return json.dumps({"timestamp": timestamp, "type": "session_meta", "payload": payload})


def _write(path: Path, lines: list[str], mtime: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stamp = mtime.timestamp()
    os.utime(path, (stamp, stamp))


def _session_meta_without_thread_source(
    session_id: str,
    timestamp: str,
    *,
    cwd: str = "/worktrees/agent",
    parent: str | None = None,
    nickname: str | None = None,
) -> str:
    """Create a session_meta record without thread_source field (simulating NULL)."""
    return json.dumps(
        {
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {
                "session_id": session_id,
                "timestamp": timestamp,
                "cwd": cwd,
                "parent_thread_id": parent,
                "agent_nickname": nickname,
            },
        }
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    _write(
        tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-root.jsonl",
        [
            _session_meta("root-1", "2026-07-20T17:00:00.000Z"),
            # A resumed session appends a second session_meta; the first wins.
            _session_meta("root-1", "2026-07-24T17:00:00.000Z", cwd="/elsewhere"),
        ],
        mtime=datetime(2026, 7, 22, tzinfo=TZ),
    )
    _write(
        tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-sub.jsonl",
        [
            _session_meta(
                "sub-1",
                "2026-07-20T18:00:00.000Z",
                thread_source="subagent",
                parent="root-1",
                nickname="Ampere",
            )
        ],
        mtime=datetime(2026, 7, 22, tzinfo=TZ),
    )
    _write(
        tmp_path / "archived_sessions" / "rollout-archived.jsonl",
        [_session_meta("archived-1", "2026-07-22T17:00:00.000Z")],
        mtime=datetime(2026, 7, 23, tzinfo=TZ),
    )
    _write(
        tmp_path / "sessions" / "2026" / "07" / "01" / "rollout-stale.jsonl",
        [_session_meta("stale-1", "2026-07-01T17:00:00.000Z")],
        mtime=datetime(2026, 7, 1, tzinfo=TZ),
    )
    return tmp_path


def test_discovers_sessions_and_archived_sessions_in_the_period(home: Path) -> None:
    descriptors = discover_rollouts(home, PERIOD, root_only=False)

    ids = {descriptor.session_id for descriptor in descriptors}
    assert ids == {"root-1", "sub-1", "archived-1"}


def test_root_only_excludes_subagent_rollouts(home: Path) -> None:
    descriptors = discover_rollouts(home, PERIOD, root_only=True)

    assert "sub-1" not in {descriptor.session_id for descriptor in descriptors}


def test_uses_the_first_session_meta_record(home: Path) -> None:
    descriptors = discover_rollouts(home, PERIOD, root_only=False)
    by_id = {descriptor.session_id: descriptor for descriptor in descriptors}

    assert by_id["root-1"].working_directory_hint == "/worktrees/agent"


def test_carries_parent_and_nickname(home: Path) -> None:
    descriptors = discover_rollouts(home, PERIOD, root_only=False)
    by_id = {descriptor.session_id: descriptor for descriptor in descriptors}

    assert by_id["sub-1"].parent_session_id == "root-1"
    assert by_id["sub-1"].title == "Ampere"


def test_missing_directories_are_not_an_error(tmp_path: Path) -> None:
    assert discover_rollouts(tmp_path, PERIOD, root_only=False) == []


def test_null_thread_source_survives_root_only_filter(tmp_path: Path) -> None:
    """A session with NULL/absent thread_source should survive root_only=True."""
    _write(
        tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-null-source.jsonl",
        [_session_meta_without_thread_source("null-1", "2026-07-20T19:00:00.000Z")],
        mtime=datetime(2026, 7, 22, tzinfo=TZ),
    )

    descriptors = discover_rollouts(tmp_path, PERIOD, root_only=True)
    ids = {descriptor.session_id for descriptor in descriptors}
    assert "null-1" in ids


def test_prefers_id_over_session_id_for_the_descriptor_session_id(tmp_path: Path) -> None:
    """`session_id` is the originating/root thread id, not this session's own id.

    Every resumed session and every subagent inherits the same `session_id`, so
    the descriptor must be built from `id` — the session's own id — whenever it
    is present.
    """

    _write(
        tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-own-id.jsonl",
        [
            _session_meta(
                "thread-root", "2026-07-20T17:00:00.000Z", id="thread-own"
            )
        ],
        mtime=datetime(2026, 7, 22, tzinfo=TZ),
    )

    descriptors = discover_rollouts(tmp_path, PERIOD, root_only=False)

    assert [descriptor.session_id for descriptor in descriptors] == ["thread-own"]


def test_two_sessions_resumed_from_one_root_stay_distinct(tmp_path: Path) -> None:
    """Two rollouts resumed from the same root thread share `session_id` but each
    carries its own `id`. Falling back to `session_id` would collapse both
    descriptors onto the same id.
    """

    _write(
        tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-a.jsonl",
        [_session_meta("thread-root", "2026-07-20T17:00:00.000Z", id="thread-a")],
        mtime=datetime(2026, 7, 22, tzinfo=TZ),
    )
    _write(
        tmp_path / "sessions" / "2026" / "07" / "21" / "rollout-b.jsonl",
        [_session_meta("thread-root", "2026-07-21T17:00:00.000Z", id="thread-b")],
        mtime=datetime(2026, 7, 22, tzinfo=TZ),
    )

    descriptors = discover_rollouts(tmp_path, PERIOD, root_only=False)

    ids = {descriptor.session_id for descriptor in descriptors}
    assert ids == {"thread-a", "thread-b"}


def test_rollout_files_discovers_nested_archived_sessions(tmp_path: Path) -> None:
    from iiwi.harnesses.codex.rollout_catalog import _rollout_files

    nested_dir = tmp_path / "archived_sessions" / "2026" / "08" / "15"
    nested_dir.mkdir(parents=True)
    rollout = nested_dir / "rollout-nested.jsonl"
    rollout.write_text('{"type": "session_meta"}\n', encoding="utf-8")

    files = _rollout_files(tmp_path)
    assert rollout in files

