"""Per-period interactive state that outlives a single run.

Today this holds one thing: the session selection of the last Review Sessions
visit for a given harness and period, so a rescan (or a changed sanitize
setting that clears the scan) does not throw away the sessions the user
deliberately unselected. Session ids are ephemeral across periods, so a stored
selection only ever matches the period that produced it; anything else simply
does not match and falls back to the default selection.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from platformdirs import user_data_dir

from iiwi.security.secure_files import atomic_secure_write

STATE_FILE_VARIABLE = "IIWI_STATE_FILE"


def state_file_path() -> Path:
    """Return the state file, honoring an explicit override for tests."""

    override = os.environ.get(STATE_FILE_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir("iiwi")) / "state.json"


def period_key(*, since: datetime, until: datetime) -> str:
    """The identity of a period for selection memory, at day granularity.

    A rolling window's `until` is the moment it was built, so an exact
    timestamp key would never match the same window twice. Two scans on the
    same day cover the same sessions, so the day is the right resolution.
    """

    return f"{since:%Y-%m-%d}_{until:%Y-%m-%d}"


def _selection_key(harness: str, period_key: str, include_subagents: bool) -> str:
    return f"{harness}|{period_key}|{include_subagents}"


def load_selection(
    *,
    harness: str,
    period_key: str,
    include_subagents: bool,
    path: Path | None = None,
) -> set[str] | None:
    """Return the last selection for this exact key, or None when there is none.

    A corrupt state file is treated as empty rather than as an error: the file
    is a convenience, and refusing to run over it would punish the user for a
    hand edit. The selection is metadata, not evidence.
    """

    source = path or state_file_path()
    if not source.exists():
        return None
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    selections = raw.get("selections")
    if not isinstance(selections, dict):
        return None
    stored = selections.get(
        _selection_key(harness, period_key, include_subagents)
    )
    if not isinstance(stored, dict):
        return None
    ids = stored.get("selected_session_ids")
    if not isinstance(ids, list):
        return None
    return {entry for entry in ids if isinstance(entry, str)}


def save_selection(
    *,
    harness: str,
    period_key: str,
    include_subagents: bool,
    selected_session_ids: Iterable[str],
    path: Path | None = None,
) -> None:
    """Record the selection for one key, keeping the other keys intact."""

    destination = path or state_file_path()
    existing: dict[str, object] = {}
    if destination.exists():
        try:
            raw = json.loads(destination.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("selections"), dict):
                existing = raw
        except (OSError, ValueError):
            existing = {}
    selections = existing.get("selections")
    if not isinstance(selections, dict):
        selections = {}
    selections[_selection_key(harness, period_key, include_subagents)] = {
        "selected_session_ids": sorted(selected_session_ids),
        "updated_at": datetime.now().isoformat(),
    }
    existing["selections"] = selections
    atomic_secure_write(
        destination,
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        force=True,
    )
