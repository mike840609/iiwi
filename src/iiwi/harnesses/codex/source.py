"""Codex session discovery and loading."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from iiwi.errors import HarnessSourceError, SessionParseError
from iiwi.harnesses.base import HarnessSessionSource
from iiwi.harnesses.codex.mapper import CodexRolloutMapper
from iiwi.harnesses.codex.rollout_catalog import discover_rollouts
from iiwi.harnesses.codex.thread_catalog import (
    discover_threads,
    find_state_database,
)
from iiwi.models.session import AgentSession, SessionDescriptor
from iiwi.models.time_range import DateRange


def describe_discovery(home_directory: Path) -> str:
    """Name the discovery path `doctor` will take, so a fallback is visible."""

    database = find_state_database(home_directory)
    return database.name if database is not None else "directory scan"


def is_available(home_directory: Path) -> bool:
    """Whether this harness's sessions can be read on this machine."""

    return home_directory.is_dir()


def _iter_records(text: str) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            # Codex appends live, so the final line can be torn. Skipping it
            # keeps the rest of the session usable.
            continue
        if isinstance(record, Mapping):
            records.append(record)
    return records


class CodexSource(HarnessSessionSource):
    """Read Codex sessions, preferring the state database over a directory scan."""

    def __init__(self, *, home_directory: Path, root_only: bool = False) -> None:
        self._home_directory = home_directory
        self._root_only = root_only

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        if not self._home_directory.is_dir():
            raise HarnessSourceError(
                f"Codex home directory not found: {self._home_directory}"
            )

        database = find_state_database(self._home_directory)
        if database is not None:
            try:
                return discover_threads(
                    database, period, root_only=self._root_only
                )
            except sqlite3.Error:
                # A drifted schema or a locked database must not lose the week's
                # work: the rollout files carry the same facts, only slower.
                pass

        return discover_rollouts(
            self._home_directory, period, root_only=self._root_only
        )

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        if descriptor.source_location is None:
            raise SessionParseError(
                f"Codex session {descriptor.session_id} has no source location"
            )
        path = Path(descriptor.source_location)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise SessionParseError(
                f"Codex rollout unreadable for {descriptor.session_id}: {exc}"
            ) from exc
        return CodexRolloutMapper().map(_iter_records(text), descriptor)
