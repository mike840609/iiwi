"""Per-period interactive state persistence."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from iiwi.state import (
    load_selection,
    period_key,
    save_selection,
)

TZ = ZoneInfo("Asia/Taipei")


def _period_key() -> str:
    return period_key(
        since=datetime(2026, 8, 3, 0, 0, tzinfo=TZ),
        until=datetime(2026, 8, 10, 0, 0, tzinfo=TZ),
    )


def test_save_then_load_round_trips(tmp_path) -> None:
    key = _period_key()
    save_selection(
        harness="opencode",
        period_key=key,
        include_subagents=True,
        selected_session_ids={"ses-a", "ses-b"},
        path=tmp_path / "state.json",
    )

    stored = load_selection(
        harness="opencode",
        period_key=key,
        include_subagents=True,
        path=tmp_path / "state.json",
    )

    assert stored == {"ses-a", "ses-b"}


def test_load_of_a_missing_file_returns_none(tmp_path) -> None:
    assert (
        load_selection(
            harness="opencode",
            period_key=_period_key(),
            include_subagents=True,
            path=tmp_path / "absent.json",
        )
        is None
    )


def test_load_of_a_corrupt_file_returns_none(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text("this is not json", encoding="utf-8")

    assert (
        load_selection(
            harness="opencode",
            period_key=_period_key(),
            include_subagents=True,
            path=path,
        )
        is None
    )


def test_selections_are_keyed_by_harness_period_and_subagents(tmp_path) -> None:
    key = _period_key()
    path = tmp_path / "state.json"
    save_selection(
        harness="opencode",
        period_key=key,
        include_subagents=True,
        selected_session_ids={"ses-a"},
        path=path,
    )

    assert (
        load_selection(
            harness="claude-code",
            period_key=key,
            include_subagents=True,
            path=path,
        )
        is None
    )
    assert (
        load_selection(
            harness="opencode",
            period_key="2026-07-27_2026-08-03",
            include_subagents=True,
            path=path,
        )
        is None
    )
    assert (
        load_selection(
            harness="opencode",
            period_key=key,
            include_subagents=False,
            path=path,
        )
        is None
    )
    assert (
        load_selection(
            harness="opencode",
            period_key=key,
            include_subagents=True,
            path=path,
        )
        == {"ses-a"}
    )


def test_period_key_uses_the_periods_dates() -> None:
    assert _period_key() == "2026-08-03_2026-08-10"


def test_saved_state_file_is_owner_only(tmp_path) -> None:
    import os
    import stat

    path = tmp_path / "state.json"
    save_selection(
        harness="opencode",
        period_key=_period_key(),
        include_subagents=True,
        selected_session_ids={"ses-a"},
        path=path,
    )

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
