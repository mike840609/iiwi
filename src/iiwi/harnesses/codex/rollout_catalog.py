"""Discover Codex sessions by scanning rollout files.

The fallback for a machine with no Codex state database, or one whose schema
this version does not understand. It reads the same facts from the first
`session_meta` record of each rollout file, at the cost of opening every file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iiwi.harnesses.codex.thread_catalog import HARNESS_NAME
from iiwi.models.session import SessionDescriptor
from iiwi.models.time_range import DateRange

# `session_meta` is the opening record; reading further just to date a file
# would defeat the point of the mtime pre-filter.
_HEAD_RECORD_LIMIT = 50


def parse_timestamp(value: object) -> datetime | None:
    """Parse a Codex ISO-8601 timestamp, assuming UTC when no offset is given."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _rollout_files(home_directory: Path) -> list[Path]:
    files = sorted((home_directory / "sessions").rglob("rollout-*.jsonl"))
    files.extend(sorted((home_directory / "archived_sessions").glob("rollout-*.jsonl")))
    return files


def _first_session_meta(path: Path) -> Mapping[str, Any] | None:
    """Return the first `session_meta` payload.

    A resumed or forked session appends further `session_meta` records — one
    measured file holds 68 — and the later ones describe the resumption, not the
    session, so only the first is authoritative.
    """

    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= _HEAD_RECORD_LIMIT:
                    return None
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, Mapping):
                    continue
                if record.get("type") != "session_meta":
                    continue
                payload = record.get("payload")
                return payload if isinstance(payload, Mapping) else None
    except OSError:
        return None
    return None


def discover_rollouts(
    home_directory: Path,
    period: DateRange,
    *,
    root_only: bool,
) -> list[SessionDescriptor]:
    """Return descriptors for rollout files whose activity overlaps the period."""

    descriptors: list[SessionDescriptor] = []
    for path in _rollout_files(home_directory):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime < period.since:
            continue

        meta = _first_session_meta(path)
        if meta is None:
            continue
        if root_only and meta.get("thread_source") == "subagent":
            continue

        created_at = parse_timestamp(meta.get("timestamp"))
        if created_at is not None and created_at >= period.until:
            continue

        # `id` is this session's own id. `session_id` is the originating/root
        # thread id, which every resumed session and every subagent inherits —
        # preferring it collapses many distinct sessions onto one id. `id` is
        # therefore tried first, with `session_id` only as the fallback for a
        # payload that lacks it.
        session_id = _text(meta.get("id")) or _text(meta.get("session_id")) or path.stem
        descriptors.append(
            SessionDescriptor(
                harness=HARNESS_NAME,
                session_id=session_id,
                source_location=str(path),
                title=_text(meta.get("agent_nickname")),
                created_at=created_at,
                updated_at=mtime,
                working_directory_hint=_text(meta.get("cwd")),
                parent_session_id=_text(meta.get("parent_thread_id")),
            )
        )
    return descriptors
