"""Discover Codex sessions from the Codex state database."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from iiwi.models.session import SessionDescriptor
from iiwi.models.time_range import DateRange

HARNESS_NAME = "codex"

# The file name carries the schema version, so a Codex upgrade introduces
# `state_6.sqlite` beside `state_5.sqlite` rather than migrating it in place.
_STATE_VERSION_PATTERN = re.compile(r"^state_(\d+)\.sqlite$")

_QUERY = """
SELECT t.id AS id,
       t.rollout_path AS rollout_path,
       t.created_at AS created_at,
       t.updated_at AS updated_at,
       t.cwd AS cwd,
       t.title AS title,
       t.agent_nickname AS agent_nickname,
       e.parent_thread_id AS parent_thread_id
  FROM threads t
  LEFT JOIN thread_spawn_edges e ON e.child_thread_id = t.id
 WHERE t.updated_at >= ? AND t.created_at < ?
"""

# `archived` is deliberately absent from the filter: archiving is a Codex UI
# state, not a statement that the work did not happen that week.
# IS NOT is required instead of != to safely handle NULL: NULL != 'subagent' is
# NULL (excluded), but NULL IS NOT 'subagent' is TRUE (included).
_ROOT_ONLY_CLAUSE = " AND t.thread_source IS NOT 'subagent'"


def find_state_database(home_directory: Path) -> Path | None:
    """Return the highest-versioned `state_<n>.sqlite`, or None if there is none."""

    try:
        entries = list(home_directory.iterdir())
    except OSError:
        return None
    candidates: list[tuple[int, Path]] = []
    for entry in entries:
        match = _STATE_VERSION_PATTERN.match(entry.name)
        if match is not None and entry.is_file():
            candidates.append((int(match.group(1)), entry))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def _timestamp(value: object) -> datetime | None:
    # bool is an int subclass; a stray JSON true must not become 1970-01-01.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def discover_threads(
    database: Path,
    period: DateRange,
    *,
    root_only: bool,
) -> list[SessionDescriptor]:
    """Return descriptors for threads whose activity overlaps the period.

    `created_at` and `updated_at` are unix seconds. The overlap test mirrors the
    Claude Code source's mtime/`created_at` pair: a session counts when it was
    still being written after the period opened and had already started before
    the period closed.

    Raises `sqlite3.Error` when the database cannot be read or its schema has
    drifted, which is the caller's signal to fall back to the rollout scan.
    """

    query = _QUERY + (_ROOT_ONLY_CLAUSE if root_only else "")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            query,
            (int(period.since.timestamp()), int(period.until.timestamp())),
        ).fetchall()
    finally:
        connection.close()

    descriptors: list[SessionDescriptor] = []
    for row in rows:
        session_id = _text(row["id"])
        rollout_path = _text(row["rollout_path"])
        if session_id is None or rollout_path is None:
            continue
        # A missing rollout file is not filtered here on purpose: letting `load`
        # fail turns it into a report warning, which is more visible than a
        # session silently absent from the week.
        descriptors.append(
            SessionDescriptor(
                harness=HARNESS_NAME,
                session_id=session_id,
                source_location=rollout_path,
                title=_text(row["title"]) or _text(row["agent_nickname"]),
                created_at=_timestamp(row["created_at"]),
                updated_at=_timestamp(row["updated_at"]),
                working_directory_hint=_text(row["cwd"]),
                parent_session_id=_text(row["parent_thread_id"]),
            )
        )
    return descriptors
