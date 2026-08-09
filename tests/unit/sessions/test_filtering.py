from datetime import datetime
from zoneinfo import ZoneInfo

from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.sessions.filtering import filter_session_to_period

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
