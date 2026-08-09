"""Claude Code session discovery and loading from local JSONL transcripts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iiwi.errors import SessionParseError
from iiwi.harnesses.base import HarnessSessionSource
from iiwi.harnesses.claude_code.mapper import ClaudeCodeJsonlMapper
from iiwi.models.session import AgentSession, SessionDescriptor
from iiwi.models.time_range import DateRange

HARNESS_NAME = "claude-code"

# Reading a whole multi-megabyte transcript just to date it is wasteful; the
# opening records always carry the timestamp and cwd.
_HEAD_RECORD_LIMIT = 50


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _iter_records(text: str) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            # Claude Code appends live, so the final line can be torn. Skipping
            # it keeps the rest of the session usable.
            continue
        if isinstance(record, Mapping):
            records.append(record)
    return records


class ClaudeCodeFileSource(HarnessSessionSource):
    """Read every Claude Code project transcript under one projects directory."""

    def __init__(
        self,
        *,
        projects_directory: Path,
        root_only: bool = False,
    ) -> None:
        self._projects_directory = projects_directory
        self._root_only = root_only

    def _session_files(self) -> list[Path]:
        root = self._projects_directory
        if not root.is_dir():
            return []
        files = sorted(root.glob("*/*.jsonl"))
        if not self._root_only:
            files.extend(sorted(root.glob("*/*/subagents/*.jsonl")))
        return files

    def _subagent_title(self, path: Path) -> str | None:
        meta_path = path.with_suffix(".meta.json")
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        description = payload.get("description")
        return description if isinstance(description, str) and description else None

    def _head_hints(self, path: Path) -> tuple[datetime | None, str | None]:
        created_at: datetime | None = None
        working_directory: str | None = None
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index >= _HEAD_RECORD_LIMIT:
                        break
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, Mapping):
                        continue
                    if created_at is None:
                        created_at = _parse_timestamp(record.get("timestamp"))
                    if working_directory is None:
                        cwd = record.get("cwd")
                        if isinstance(cwd, str) and cwd:
                            working_directory = cwd
                    if created_at is not None and working_directory is not None:
                        break
        except OSError:
            return None, None
        return created_at, working_directory

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        descriptors: list[SessionDescriptor] = []
        for path in self._session_files():
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if mtime < period.since:
                continue

            created_at, working_directory = self._head_hints(path)
            if created_at is not None and created_at >= period.until:
                continue

            is_subagent = path.parent.name == "subagents"
            descriptors.append(
                SessionDescriptor(
                    harness=HARNESS_NAME,
                    session_id=path.stem,
                    source_location=str(path),
                    title=self._subagent_title(path) if is_subagent else None,
                    created_at=created_at,
                    updated_at=mtime,
                    working_directory_hint=working_directory,
                    project_id_hint=(
                        path.parent.parent.parent.name if is_subagent else path.parent.name
                    ),
                    parent_session_id=path.parent.parent.name if is_subagent else None,
                )
            )
        return descriptors

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        if descriptor.source_location is None:
            raise SessionParseError(
                f"Claude Code session {descriptor.session_id} has no source location"
            )
        path = Path(descriptor.source_location)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise SessionParseError(
                f"Claude Code transcript unreadable for {descriptor.session_id}: {exc}"
            ) from exc
        return ClaudeCodeJsonlMapper().map(_iter_records(text), descriptor)
