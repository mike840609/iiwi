import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.errors import HarnessSourceError
from iiwi.harnesses.opencode.stats import collect_usage_stats, usage_days
from iiwi.models.time_range import DateRange
from iiwi.process import CommandResult

TZ = ZoneInfo("Asia/Taipei")


@dataclass
class TimingOutRunner:
    """A runner double mirroring `CommandRunner.run`'s uncaught timeout behavior."""

    calls: list[list[str]] = field(default_factory=list)

    def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        raise subprocess.TimeoutExpired(cmd=args, timeout=5.0)


def test_usage_days_covers_period_start_until_now() -> None:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    assert usage_days(period, datetime(2026, 7, 29, 20, 0, tzinfo=TZ)) == 10


def test_usage_days_is_at_least_one() -> None:
    period = DateRange(
        since=datetime(2026, 7, 29, 18, 0, tzinfo=TZ),
        until=datetime(2026, 7, 29, 19, 0, tzinfo=TZ),
    )

    assert usage_days(period, datetime(2026, 7, 29, 19, 0, tzinfo=TZ)) == 1


def test_collect_usage_stats_requests_models_and_tools(fake_runner) -> None:
    fake_runner.stdout = "gpt-5-mini  1234 tokens\n"

    text = collect_usage_stats(runner=fake_runner, executable="opencode", days=10)

    assert text == "gpt-5-mini  1234 tokens"
    assert fake_runner.calls[0] == [
        "opencode",
        "stats",
        "--days",
        "10",
        "--models",
        "20",
        "--tools",
        "20",
    ]


def test_collect_usage_stats_raises_on_failure(fake_runner) -> None:
    fake_runner.set_result(
        "--tools 20",
        CommandResult(returncode=1, stdout="", stderr="stats unsupported"),
    )

    with pytest.raises(HarnessSourceError, match="stats unsupported"):
        collect_usage_stats(runner=fake_runner, executable="opencode", days=7)


def test_collect_usage_stats_raises_on_empty_output(fake_runner) -> None:
    fake_runner.stdout = "   \n"

    with pytest.raises(HarnessSourceError, match="no output"):
        collect_usage_stats(runner=fake_runner, executable="opencode", days=7)


def test_collect_usage_stats_raises_on_timeout() -> None:
    runner = TimingOutRunner()

    with pytest.raises(HarnessSourceError, match="timed out"):
        collect_usage_stats(runner=runner, executable="opencode", days=7)
