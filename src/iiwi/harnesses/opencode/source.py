"""OpenCode CLI-backed session discovery and loading."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from iiwi.errors import HarnessSourceError, SessionParseError
from iiwi.harnesses.base import HarnessSessionSource
from iiwi.harnesses.opencode.mapper import OpenCodeExportMapper
from iiwi.models.session import AgentSession, SessionDescriptor
from iiwi.models.time_range import DateRange
from iiwi.process import CommandResult


class Runner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
    ) -> CommandResult: ...


def _from_millis(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        milliseconds = int(cast(int | str, value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _rows_from_payload(payload: object) -> list[dict[str, object]]:
    rows: object = payload
    if isinstance(payload, dict):
        rows = payload.get("data", payload.get("rows", []))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise HarnessSourceError("OpenCode database response must contain a list of rows")
    return cast(list[dict[str, object]], rows)


class OpenCodeCliSource(HarnessSessionSource):
    """Query all OpenCode projects through the OpenCode CLI."""

    def __init__(
        self,
        *,
        runner: Runner,
        executable: str = "opencode",
        root_only: bool = False,
        sanitize: bool = False,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._root_only = root_only
        self._sanitize = sanitize

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        since_ms = int(period.since.timestamp() * 1000)
        until_ms = int(period.until.timestamp() * 1000)
        parent_filter = "AND parent_id IS NULL " if self._root_only else ""
        query = (
            "SELECT id, project_id, parent_id, directory, title, time_created, time_updated "
            "FROM session "
            f"WHERE time_created < {until_ms} "
            f"AND COALESCE(time_updated, time_created, 0) >= {since_ms} "
            f"{parent_filter}"
            "ORDER BY COALESCE(time_updated, time_created, 0) DESC;"
        )
        result = self._runner.run(
            [self._executable, "db", query, "--format", "json"]
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or "OpenCode database query failed"
            raise HarnessSourceError(detail)
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise HarnessSourceError("OpenCode database returned invalid JSON") from exc

        descriptors: list[SessionDescriptor] = []
        for row in _rows_from_payload(payload):
            session_id = row.get("id")
            if not isinstance(session_id, str) or not session_id:
                continue
            directory = row.get("directory")
            project_id = row.get("project_id")
            parent_id = row.get("parent_id")
            title = row.get("title")
            descriptors.append(
                SessionDescriptor(
                    harness="opencode",
                    session_id=session_id,
                    title=(title if isinstance(title, str) else None),
                    created_at=_from_millis(row.get("time_created")),
                    updated_at=_from_millis(row.get("time_updated")),
                    working_directory_hint=(directory if isinstance(directory, str) else None),
                    project_id_hint=(project_id if isinstance(project_id, str) else None),
                    parent_session_id=(parent_id if isinstance(parent_id, str) else None),
                )
            )
        return descriptors

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        args = [self._executable, "export", descriptor.session_id]
        if self._sanitize:
            args.append("--sanitize")
        # OpenCode's export command truncates stdout to the OS pipe buffer when
        # its stdout is a pipe (returning exit 0 with invalid JSON). Redirect to
        # a temporary file so large exports are captured completely.
        with tempfile.TemporaryDirectory() as directory:
            export_path = Path(directory) / "export.json"
            result = self._runner.run(args, stdout_path=export_path)
            if result.returncode != 0:
                detail = (
                    result.stderr.strip()
                    or f"OpenCode export failed for {descriptor.session_id}"
                )
                raise SessionParseError(detail)
            try:
                payload = json.loads(result.stdout or "{}")
            except json.JSONDecodeError as exc:
                raise SessionParseError(
                    f"OpenCode export returned invalid JSON for {descriptor.session_id}"
                ) from exc
        return OpenCodeExportMapper().map(payload, descriptor)
