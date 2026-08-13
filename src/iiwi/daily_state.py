"""Persistence for same-day reviewed Daily Standup drafts."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from platformdirs import user_data_dir

from iiwi.models.daily import DailyStandupDraft
from iiwi.security.secure_files import atomic_secure_write

DAILY_STATE_DIR_VARIABLE = "IIWI_DAILY_STATE_DIR"
DAILY_STATE_RETENTION_DAYS = 30

_DATE_FILE = re.compile(r"\d{4}-\d{2}-\d{2}\.json\Z")


@dataclass(frozen=True)
class DailyStateLoadResult:
    draft: DailyStandupDraft | None
    warning: str | None = None


def daily_state_directory() -> Path:
    """Return the Daily state directory, honoring the test/user override."""

    override = os.environ.get(DAILY_STATE_DIR_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir("iiwi")) / "daily"


def daily_state_path(
    standup_date: date,
    *,
    directory: Path | None = None,
) -> Path:
    """Return the state path for one local standup date."""

    root = (directory or daily_state_directory()).expanduser()
    return root / f"{standup_date:%Y-%m-%d}.json"


def load_daily_draft(
    standup_date: date,
    *,
    directory: Path | None = None,
) -> DailyStateLoadResult:
    """Load reviewed state without hiding corrupt or unreadable data."""

    source = daily_state_path(standup_date, directory=directory)
    try:
        content = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DailyStateLoadResult(draft=None)
    except (OSError, UnicodeError) as exc:
        return _load_warning(source, exc)
    try:
        draft = DailyStandupDraft.model_validate_json(content)
        if draft.standup_date != standup_date:
            raise ValueError(
                f"stored date {draft.standup_date} does not match {standup_date}"
            )
    except (ValueError, UnicodeError) as exc:
        return _load_warning(source, exc)
    return DailyStateLoadResult(draft=draft)


def save_daily_draft(
    draft: DailyStandupDraft,
    *,
    directory: Path | None = None,
) -> None:
    """Atomically save a reviewed draft with owner-only permissions."""

    destination = daily_state_path(draft.standup_date, directory=directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        destination.parent.chmod(0o700)
    atomic_secure_write(
        destination,
        draft.model_dump_json(indent=2) + "\n",
        force=True,
    )


def cleanup_daily_state(
    today: date,
    *,
    directory: Path | None = None,
    retention_days: int = DAILY_STATE_RETENTION_DAYS,
) -> None:
    """Remove expired date-keyed drafts, ignoring best-effort cleanup errors."""

    root = (directory or daily_state_directory()).expanduser()
    cutoff = today - timedelta(days=retention_days)
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for path in entries:
        if not _DATE_FILE.fullmatch(path.name):
            continue
        try:
            stored_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if stored_date >= cutoff:
            continue
        try:
            path.unlink()
        except OSError:
            continue


def _load_warning(source: Path, exc: Exception) -> DailyStateLoadResult:
    return DailyStateLoadResult(
        draft=None,
        warning=f"Could not load reviewed Daily state from {source}: {exc}",
    )
