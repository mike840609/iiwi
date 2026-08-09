"""Optional OpenCode usage statistics collection."""

from __future__ import annotations

import math
import subprocess
from datetime import datetime
from typing import Protocol

from iiwi.errors import HarnessSourceError
from iiwi.models.time_range import DateRange
from iiwi.process import CommandResult


class Runner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


def usage_days(period: DateRange, now: datetime) -> int:
    """Return whole days from the period start to now, at least one.

    `opencode stats` only accepts a rolling window ending now, so the window is
    widened to contain the report period instead of matching it exactly.
    """

    elapsed_days = (now - period.since).total_seconds() / 86400
    return max(1, math.ceil(elapsed_days))


def collect_usage_stats(*, runner: Runner, executable: str, days: int) -> str:
    """Return raw `opencode stats` output for the trailing window."""

    # ponytail: raw CLI text, not parsed. Parse only if the report needs per-model rows.
    try:
        result = runner.run(
            [
                executable,
                "stats",
                "--days",
                str(days),
                "--models",
                "20",
                "--tools",
                "20",
            ]
        )
    except (OSError, TimeoutError, subprocess.SubprocessError) as exc:
        raise HarnessSourceError(str(exc) or type(exc).__name__) from exc
    if result.returncode != 0:
        raise HarnessSourceError(result.stderr.strip() or "opencode stats failed")
    text = result.stdout.strip()
    if not text:
        raise HarnessSourceError("opencode stats returned no output")
    return text
