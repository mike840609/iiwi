from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.sessions.filtering import (
    IIWI_SESSION_TITLE_PREFIX,
    filter_session_to_period,
    is_iiwi_authored,
)

TZ = ZoneInfo("Asia/Taipei")


def test_old_session_with_in_range_activity_is_included() -> None:
    session = AgentSession(
        harness="opencode",
        session_id="s1",
        created_at=datetime(2026, 7, 1, tzinfo=TZ),
        activities=[
            SessionActivity(
                activity_id="a1",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                content="implement report",
            )
        ],
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    filtered = filter_session_to_period(session, period)

    assert filtered is not None
    assert [item.activity_id for item in filtered.activities] == ["a1"]


def test_opencode_metadata_only_session_uses_session_timestamp() -> None:
    session = AgentSession(
        harness="opencode",
        session_id="s1",
        created_at=datetime(2026, 7, 1, tzinfo=TZ),
        updated_at=datetime(2026, 7, 22, tzinfo=TZ),
        activities=[],
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    filtered = filter_session_to_period(session, period)

    assert filtered is not None
    assert filtered.activities == []


def test_non_opencode_metadata_only_session_is_excluded() -> None:
    session = AgentSession(
        harness="codex",
        session_id="s1",
        updated_at=datetime(2026, 7, 22, tzinfo=TZ),
        activities=[],
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    assert filter_session_to_period(session, period) is None


def test_metadata_only_session_outside_period_is_excluded() -> None:
    session = AgentSession(
        harness="opencode",
        session_id="s1",
        updated_at=datetime(2026, 7, 19, tzinfo=TZ),
        activities=[],
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    assert filter_session_to_period(session, period) is None


def test_activity_exactly_at_until_is_excluded() -> None:
    until = datetime(2026, 7, 27, tzinfo=TZ)
    session = AgentSession(
        harness="opencode",
        session_id="s1",
        activities=[
            SessionActivity(
                activity_id="a1",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=until,
                content="outside range",
            )
        ],
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=until,
    )

    assert filter_session_to_period(session, period) is None


def test_activity_without_timestamp_is_excluded() -> None:
    session = AgentSession(
        harness="opencode",
        session_id="s1",
        activities=[
            SessionActivity(
                activity_id="a1",
                activity_type=ActivityType.USER_MESSAGE,
                content="unknown time",
            )
        ],
    )
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )

    assert filter_session_to_period(session, period) is None


def _titled(title: str | None) -> AgentSession:
    return AgentSession(harness="opencode", session_id="s1", title=title)


@pytest.mark.parametrize(
    "title",
    [
        "iiwi-internal: outcome synthesis",
        "iiwi-internal: narrative 2026-08-05 to 2026-08-12",
        "Iiwi outcome synthesis",
        "Iiwi narrative summary",
        "Iiwi - 2026-08-05 to 2026-08-12",
    ],
)
def test_titles_iiwi_writes_are_recognized(title: str) -> None:
    assert is_iiwi_authored(_titled(title)) is True


@pytest.mark.parametrize(
    "title",
    [
        "Iiwi main menu rework",
        "Iiwi outcome synthesis rewrite",
        "iiwi-internal notes",
        "agent-worklog 更名 iiwi 進度整理",
        "Iiwi - not a date range",
        "Iiwi - 2026-08-05 to yesterday",
    ],
)
def test_human_titles_are_not_dropped(title: str) -> None:
    assert is_iiwi_authored(_titled(title)) is False


@pytest.mark.parametrize("title", [None, "", "   "])
def test_absent_titles_are_not_iiwi_authored(title: str | None) -> None:
    assert is_iiwi_authored(_titled(title)) is False


def test_prefix_constant_matches_what_the_predicate_accepts() -> None:
    assert is_iiwi_authored(_titled(f"{IIWI_SESSION_TITLE_PREFIX}anything")) is True
