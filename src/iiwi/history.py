"""Append-only report history, one JSON line per generated report.

The log is deliberately append-only: rewriting it would need a lock and could
lose entries; scripts only ever need to read it back in chronological order.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from platformdirs import user_data_dir

from iiwi.paths import LEGACY_APP_NAME, adopt_legacy

HISTORY_FILE_VARIABLE = "IIWI_HISTORY_FILE"


@dataclass(frozen=True)
class HistoryEntry:
    """One successfully written report."""

    generated_at: datetime
    harness: str
    since: datetime
    until: datetime
    output_path: Path
    repository_count: int
    session_count: int
    narrative: bool
    detail: str


def history_file_path() -> Path:
    """Return the history log, honoring an explicit override for tests and
    per-project logs, the same escape hatch `config` uses for its file."""

    override = os.environ.get(HISTORY_FILE_VARIABLE)
    if override:
        return Path(override).expanduser()
    return adopt_legacy(
        Path(user_data_dir("iiwi")) / "history.jsonl",
        Path(user_data_dir(LEGACY_APP_NAME)) / "history.jsonl",
    )


def _open_for_append(path: Path):
    """Append-mode descriptor, creating the file owner-only when absent."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    if os.name == "posix":
        os.fchmod(descriptor, 0o600)
    return descriptor


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def append_history(entry: HistoryEntry, *, path: Path | None = None) -> None:
    """Record one report, appending it to the end of the log."""

    destination = path or history_file_path()
    descriptor = _open_for_append(destination)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(entry), default=_json_default, ensure_ascii=False))
        handle.write("\n")


def read_history(*, path: Path | None = None) -> list[HistoryEntry]:
    """Return recorded reports in generation order, skipping unreadable lines.

    A corrupt line is evidence the file was edited by hand; the entries around
    it remain valuable, so the loss is silently contained to that line.
    """

    source = path or history_file_path()
    if not source.exists():
        return []
    entries: list[HistoryEntry] = []
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            entries.append(
                HistoryEntry(
                    generated_at=datetime.fromisoformat(raw["generated_at"]),
                    harness=raw["harness"],
                    since=datetime.fromisoformat(raw["since"]),
                    until=datetime.fromisoformat(raw["until"]),
                    output_path=Path(raw["output_path"]),
                    repository_count=int(raw["repository_count"]),
                    session_count=int(raw["session_count"]),
                    narrative=bool(raw["narrative"]),
                    detail=raw["detail"],
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return entries


def history_to_json(entries: list[HistoryEntry]) -> str:
    """Render the recorded reports as a JSON array, newest first."""

    return json.dumps(
        [asdict(entry) for entry in reversed(entries)],
        indent=2,
        default=_json_default,
        ensure_ascii=False,
    )
