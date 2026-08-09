from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from iiwi.interactive.density import (
    is_subagent,
    last_activity_at,
    message_volume,
    repository_meta,
    session_meta,
)
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def _session(
    *,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    activities: list[SessionActivity] | None = None,
    parent_session_id: str | None = None,
) -> AgentSession:
    return AgentSession(
        harness="opencode",
        session_id="s1",
        parent_session_id=parent_session_id,
        created_at=created_at,
        updated_at=updated_at,
        activities=activities or [],
    )


def _activity(kind: ActivityType, ts: datetime) -> SessionActivity:
    return SessionActivity(activity_id="act", activity_type=kind, timestamp=ts, content="c")


def _resolved(session: AgentSession, repository_id: str = "repo") -> ResolvedSession:
    return ResolvedSession(
        session=session,
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=repository_id,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repository_id}",
            resolution_method="test",
        ),
    )


def _scan(items: list[ResolvedSession]) -> ScanResult:
    by_repo: dict[str, list[ResolvedSession]] = {}
    for item in items:
        by_repo.setdefault(item.repository.repository_id, []).append(item)
    return ScanResult(
        period=DateRange(
            since=datetime(2026, 8, 1, tzinfo=TZ),
            until=datetime(2026, 8, 10, tzinfo=TZ),
        ),
        candidate_session_count=len(items),
        loaded_session_count=len(items),
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository=by_repo,
    )


def test_message_volume_counts_only_user_and_assistant() -> None:
    session = _session(
        updated_at=datetime(2026, 8, 5, tzinfo=TZ),
        activities=[
            _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
            _activity(ActivityType.ASSISTANT_MESSAGE, datetime(2026, 8, 5, 9, 1, tzinfo=TZ)),
            _activity(ActivityType.TOOL_CALL, datetime(2026, 8, 5, 9, 2, tzinfo=TZ)),
            _activity(ActivityType.SYSTEM, datetime(2026, 8, 5, 9, 3, tzinfo=TZ)),
        ],
    )
    assert message_volume(session) == 2


def test_last_activity_at_uses_latest_activity_timestamp() -> None:
    session = _session(
        created_at=datetime(2026, 8, 3, 9, 0, tzinfo=TZ),
        updated_at=datetime(2026, 8, 4, 9, 0, tzinfo=TZ),
        activities=[
            _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
        ],
    )
    assert last_activity_at(session) == datetime(2026, 8, 5, 9, 0, tzinfo=TZ)


def test_last_activity_at_falls_back_to_updated_then_created() -> None:
    created = datetime(2026, 8, 3, 9, 0, tzinfo=TZ)
    updated = datetime(2026, 8, 4, 9, 0, tzinfo=TZ)
    assert last_activity_at(_session(updated_at=updated, created_at=created)) == updated
    assert last_activity_at(_session(created_at=created)) == created
    assert last_activity_at(_session()) is None


def test_last_activity_at_none_when_activities_lack_timestamps() -> None:
    session = _session(
        updated_at=datetime(2026, 8, 4, 9, 0, tzinfo=TZ),
        activities=[
            SessionActivity(
                activity_id="a",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=None,
                content="c",
            )
        ],
    )
    assert last_activity_at(session) is None
    assert session_meta(session, TZ) == "1 msg"


def test_is_subagent() -> None:
    assert is_subagent(_session(parent_session_id="parent")) is True
    assert is_subagent(_session()) is False


def test_session_meta_renders_date_and_volume() -> None:
    session = _session(
        updated_at=datetime(2026, 8, 5, 9, 0, tzinfo=TZ),
        activities=[
            _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
            _activity(ActivityType.ASSISTANT_MESSAGE, datetime(2026, 8, 5, 9, 1, tzinfo=TZ)),
            _activity(ActivityType.TOOL_CALL, datetime(2026, 8, 5, 9, 2, tzinfo=TZ)),
        ],
    )
    assert session_meta(session, TZ) == "Aug 5 │ 2 msgs"


def test_session_meta_omits_volume_when_zero() -> None:
    session = _session(
        updated_at=datetime(2026, 8, 5, 9, 0, tzinfo=TZ),
        activities=[_activity(ActivityType.TOOL_CALL, datetime(2026, 8, 5, 9, 2, tzinfo=TZ))],
    )
    assert session_meta(session, TZ) == "Aug 5"


def test_session_meta_empty_without_date_or_volume() -> None:
    assert session_meta(_session(), TZ) == ""


def test_repository_meta_spans_dates_and_sums_volume() -> None:
    items = [
        _resolved(
            _session(
                updated_at=datetime(2026, 8, 3, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 3, 9, 0, tzinfo=TZ)),
                ],
            )
        ),
        _resolved(
            _session(
                updated_at=datetime(2026, 8, 5, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
                    _activity(
                        ActivityType.ASSISTANT_MESSAGE, datetime(2026, 8, 5, 9, 1, tzinfo=TZ)
                    ),
                ],
            )
        ),
    ]
    assert repository_meta("repo", _scan(items)) == "Aug 3–5 │ 3 msgs"


def test_repository_meta_cross_month_uses_en_dash() -> None:
    items = [
        _resolved(
            _session(
                updated_at=datetime(2026, 7, 30, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 7, 30, 9, 0, tzinfo=TZ)),
                ],
            )
        ),
        _resolved(
            _session(
                updated_at=datetime(2026, 8, 4, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 4, 9, 0, tzinfo=TZ)),
                ],
            )
        ),
    ]
    assert repository_meta("repo", _scan(items)) == "Jul 30 – Aug 4 │ 2 msgs"


def test_repository_meta_empty_when_no_dates() -> None:
    items = [_resolved(_session())]
    assert repository_meta("repo", _scan(items)) == ""


def test_repository_meta_single_date() -> None:
    items = [
        _resolved(
            _session(
                updated_at=datetime(2026, 8, 5, tzinfo=TZ),
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 9, 0, tzinfo=TZ)),
                ],
            )
        )
    ]
    assert repository_meta("repo", _scan(items)) == "Aug 5 │ 1 msg"


def test_session_meta_renders_the_day_in_the_report_timezone() -> None:
    """Harnesses store UTC; a late-night local session must not read as the day before."""

    session = _session(
        activities=[_activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 18, tzinfo=UTC))]
    )

    assert session_meta(session, TZ) == "Aug 6 │ 1 msg"


def test_repository_meta_spans_days_in_the_report_timezone() -> None:
    items = [
        _resolved(
            _session(
                activities=[
                    _activity(ActivityType.USER_MESSAGE, datetime(2026, 8, 5, 18, tzinfo=UTC))
                ]
            )
        )
    ]

    assert repository_meta("repo", _scan(items)) == "Aug 6 │ 1 msg"
