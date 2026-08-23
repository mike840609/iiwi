from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def test_from_days_returns_half_open_range() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=TZ)

    period = DateRange.from_days(days=7, now=now)

    assert period.since == datetime(2026, 7, 22, 20, 0, tzinfo=TZ)
    assert period.until == now


def test_previous_week_is_monday_to_monday() -> None:
    now = datetime(2026, 7, 29, 20, 0, tzinfo=TZ)

    period = DateRange.previous_week(now=now)

    assert period.since == datetime(2026, 7, 20, 0, 0, tzinfo=TZ)
    assert period.until == datetime(2026, 7, 27, 0, 0, tzinfo=TZ)


def test_date_range_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        DateRange(
            since=datetime(2026, 7, 20),
            until=datetime(2026, 7, 21),
        )


def test_current_week_starts_at_this_weeks_monday() -> None:
    """A weekly report wants the week in progress, not the one that already closed."""

    now = datetime(2026, 8, 8, 15, 30, tzinfo=TZ)

    period = DateRange.current_week(now=now)

    assert period.since == datetime(2026, 8, 3, tzinfo=TZ)
    assert period.until == now


def test_current_week_on_a_monday_starts_that_morning() -> None:
    """Run on a Monday the window is a few hours long, not empty and not last week."""

    now = datetime(2026, 8, 3, 9, 0, tzinfo=TZ)

    period = DateRange.current_week(now=now)

    assert period.since == datetime(2026, 8, 3, tzinfo=TZ)
    assert period.until == now


def test_current_week_rejects_a_naive_clock() -> None:
    """Harnesses record aware timestamps; a naive bound would compare against them wrongly."""

    with pytest.raises(ValueError):
        DateRange.current_week(now=datetime(2026, 8, 8, 15, 30))


def test_current_week_at_monday_midnight_returns_previous_week() -> None:
    monday_midnight = datetime(2026, 8, 17, 0, 0, 0, tzinfo=TZ)
    range_ = DateRange.current_week(now=monday_midnight)

    assert range_.since == datetime(2026, 8, 10, 0, 0, 0, tzinfo=TZ)
    assert range_.until == monday_midnight

