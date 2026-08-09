from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agent_worklog import cli
from agent_worklog.interactive import cli_actions
from agent_worklog.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def test_choose_harness_cycles_enabled_values_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_load_settings", lambda: object())
    monkeypatch.setattr(
        cli,
        "_enabled_harnesses",
        lambda settings: [cli.Harness.OPENCODE, cli.Harness.CLAUDE_CODE, cli.Harness.CODEX],
    )
    monkeypatch.setattr(
        cli,
        "_prompt",
        lambda prompt: pytest.fail(f"typed prompt should not run: {prompt}"),
    )

    assert cli_actions._choose_harness("opencode") == "claude-code"
    assert cli_actions._choose_harness("claude-code") == "codex"
    assert cli_actions._choose_harness("codex") == "opencode"


def test_choose_harness_keeps_only_enabled_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_load_settings", lambda: object())
    monkeypatch.setattr(
        cli,
        "_enabled_harnesses",
        lambda settings: [cli.Harness.CODEX],
    )

    assert cli_actions._choose_harness("codex") == "codex"


def test_choose_period_reaches_every_named_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The arrow advertises five windows, so pressing it must reach all five.

    The old cycle located the current window by comparing its timestamps against a
    freshly derived list. A rolling window's `until` is the moment it was built, so
    the comparison failed on every other press and snapped back to the first entry:
    `Last 14 days` and `Last 30 days` could not be reached at all. The previous test
    missed it by freezing the clock, which is the one thing that made it work.
    """

    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_prompt",
        lambda prompt: pytest.fail(f"typed prompt should not run: {prompt}"),
    )

    # A clock that advances between presses, as a real one does.
    ticks = iter(datetime(2026, 8, 7, 12, second=tick, tzinfo=TZ) for tick in range(30))
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: next(ticks))

    label: str | None = None
    seen: list[str] = []
    for _ in range(6):
        label, _range = cli_actions._choose_period(label)
        seen.append(label)

    assert seen == [
        "This week",
        "Last week",
        "Last 7 days",
        "Last 14 days",
        "Last 30 days",
        "This week",
    ]


def test_choose_period_starts_the_cycle_for_an_unnamed_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `--since` range carries no name, so the arrow starts the cycle rather than guessing."""

    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 7, 12, tzinfo=TZ)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)

    label, period = cli_actions._choose_period(None)

    assert label == "This week"
    assert period == DateRange.current_week(now=now)


def test_exclude_repository_appends_to_the_exclusion_setting(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))

    message = cli_actions._exclude_repository(
        "git:github.com/mike/dotfiles", "Dotfiles"
    )

    assert "Dotfiles" in message
    assert "future scans will skip it" in message
    settings = cli._load_settings()
    assert settings.report.excluded_repository_ids() == ("git:github.com/mike/dotfiles",)


def test_exclude_repository_keeps_already_configured_exclusions(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    cli_actions._exclude_repository("git:github.com/mike/notes", "Notes")

    cli_actions._exclude_repository("git:github.com/mike/dotfiles", "Dotfiles")

    settings = cli._load_settings()
    assert settings.report.excluded_repository_ids() == (
        "git:github.com/mike/notes",
        "git:github.com/mike/dotfiles",
    )


def test_exclude_repository_is_idempotent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_CONFIG_FILE", str(tmp_path / "config.env"))
    cli_actions._exclude_repository("git:github.com/mike/dotfiles", "Dotfiles")

    message = cli_actions._exclude_repository("git:github.com/mike/dotfiles", "Dotfiles")

    assert "already excluded" in message
    assert cli._load_settings().report.excluded_repository_ids() == (
        "git:github.com/mike/dotfiles",
    )


def test_save_and_restore_round_trip_through_the_state_file(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AGENT_WORKLOG_STATE_FILE", str(tmp_path / "state.json"))

    assert cli_actions._restore_selection("opencode", _period(), True) is None

    cli_actions._save_selection(
        "opencode", _period(), True, {"ses-a", "ses-b"}
    )

    assert cli_actions._restore_selection("opencode", _period(), True) == {
        "ses-a",
        "ses-b",
    }
