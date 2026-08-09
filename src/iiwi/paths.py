"""Adoption of state written under the name this project had before the rename.

Delete this module and its three call sites one release after 0.9.0. It exists
only so that an installed `agent-worklog` does not silently lose its settings,
history and session-selection memory.
"""

from __future__ import annotations

from pathlib import Path

LEGACY_APP_NAME = "agent-worklog"


def adopt_legacy(new_path: Path, legacy_path: Path) -> Path:
    """Move state written under the old name, then return the new path.

    Both paths live under the same user directory, so the rename never crosses
    a filesystem. The existence guard makes the call idempotent and means an
    already-migrated file always wins over a stale legacy one.
    """

    if not new_path.exists() and legacy_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        legacy_path.rename(new_path)
    return new_path
