from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.interactive.selection import (
    SelectionMark,
    SelectionState,
    noise_reason,
    without_repository,
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


def _resolved(session_id: str, repository_id: str, *, volume: int = 0) -> ResolvedSession:
    repository = RepositoryIdentity(
        repository_id=repository_id,
        display_name=repository_id,
        identity_type=RepositoryIdentityType.PATH_FALLBACK,
        working_directory=f"/tmp/{repository_id}",
        resolution_method="test",
    )
    session = AgentSession(
        harness="opencode",
        session_id=session_id,
        title=session_id,
        working_directory=f"/tmp/{repository_id}",
        activities=[
            SessionActivity(
                activity_id=f"{session_id}:m{index}",
                activity_type=ActivityType.ASSISTANT_MESSAGE,
                timestamp=datetime(2026, 7, 20, tzinfo=TZ),
                content="hi",
            )
            for index in range(volume)
        ],
    )
    return ResolvedSession(session=session, repository=repository)


def _scan() -> ScanResult:
    sessions = [
        _resolved("ses-a1", "repo-a"),
        _resolved("ses-a2", "repo-a"),
        _resolved("ses-b1", "repo-b"),
    ]
    return ScanResult(
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 21, tzinfo=TZ),
        ),
        candidate_session_count=5,
        loaded_session_count=3,
        failed_session_count=2,
        resolved_sessions=sessions,
        sessions_by_repository={
            "repo-a": sessions[:2],
            "repo-b": sessions[2:],
        },
        warnings=["one warning"],
        excluded_session_count=2,
    )


def test_selection_starts_with_every_session_selected() -> None:
    state = SelectionState.from_scan(_scan())

    assert state.selected_count == 3
    assert state.total_count == 3
    assert state.repository_mark("repo-a") is SelectionMark.ALL
    assert state.repository_mark("repo-b") is SelectionMark.ALL


def test_selection_reports_message_volume_for_the_selected_subset() -> None:
    sessions = [
        _resolved("ses-a1", "repo-a", volume=12),
        _resolved("ses-a2", "repo-a", volume=3),
        _resolved("ses-b1", "repo-b", volume=5),
    ]
    scan = ScanResult(
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 21, tzinfo=TZ),
        ),
        candidate_session_count=3,
        loaded_session_count=3,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions[:2], "repo-b": sessions[2:]},
    )
    state = SelectionState.from_scan(scan)

    state.toggle_session("ses-a2")

    assert state.selected_volume == 17
    assert state.total_volume == 20


def test_individual_toggle_derives_partial_repository_state() -> None:
    state = SelectionState.from_scan(_scan())

    state.toggle_session("ses-a1")

    assert state.repository_mark("repo-a") is SelectionMark.PARTIAL
    assert state.repository_mark("repo-b") is SelectionMark.ALL


def test_repository_toggle_selects_all_when_group_is_partial_then_deselects_all() -> None:
    state = SelectionState.from_scan(_scan())
    state.toggle_session("ses-a1")

    state.toggle_repository("repo-a")
    assert {"ses-a1", "ses-a2"} <= state.selected_session_ids

    state.toggle_repository("repo-a")
    assert not ({"ses-a1", "ses-a2"} & state.selected_session_ids)
    assert state.repository_mark("repo-a") is SelectionMark.NONE


def test_select_all_and_none_operate_on_every_session() -> None:
    state = SelectionState.from_scan(_scan())

    state.select_none()
    assert state.selected_count == 0

    state.select_all()
    assert state.selected_session_ids == {"ses-a1", "ses-a2", "ses-b1"}


def test_filtered_scan_preserves_scan_metadata_and_filters_groups() -> None:
    scan = _scan()
    state = SelectionState.from_scan(scan)
    state.toggle_session("ses-a2")
    state.toggle_session("ses-b1")

    filtered = state.filtered_scan()

    assert filtered.period == scan.period
    assert filtered.candidate_session_count == 5
    assert filtered.failed_session_count == 2
    assert filtered.excluded_session_count == 2
    assert filtered.warnings == ["one warning"]
    assert filtered.loaded_session_count == 1
    assert [item.session.session_id for item in filtered.resolved_sessions] == ["ses-a1"]
    assert list(filtered.sessions_by_repository) == ["repo-a"]


def test_zero_selection_produces_structurally_valid_empty_scan() -> None:
    state = SelectionState.from_scan(_scan())
    state.select_none()

    filtered = state.filtered_scan()

    assert filtered.loaded_session_count == 0
    assert filtered.resolved_sessions == []
    assert filtered.sessions_by_repository == {}


def test_unknown_session_or_repository_is_rejected() -> None:
    state = SelectionState.from_scan(_scan())

    with pytest.raises(KeyError, match="missing-session"):
        state.toggle_session("missing-session")
    with pytest.raises(KeyError, match="missing-repo"):
        state.toggle_repository("missing-repo")


def _session(*, title: str | None, activity_count: int) -> AgentSession:
    return AgentSession(
        harness="opencode",
        session_id="ses-1",
        title=title,
        activities=[
            SessionActivity(activity_id=f"act-{i}", activity_type=ActivityType.USER_MESSAGE)
            for i in range(activity_count)
        ],
    )


def test_noise_reason_flags_a_session_with_no_title() -> None:
    assert noise_reason(_session(title=None, activity_count=20)) == "No title"


def test_noise_reason_flags_a_session_with_almost_no_activity() -> None:
    assert noise_reason(_session(title="Quick check", activity_count=1)) == "Low activity"


def test_noise_reason_keeps_real_work_whose_title_mentions_test_or_debug() -> None:
    """Title wording is never a noise signal: these are real engineering sessions."""

    assert noise_reason(_session(title="Fix test flakiness in CI", activity_count=25)) is None
    assert noise_reason(_session(title="Debug the payment race", activity_count=38)) is None
    assert noise_reason(_session(title="Scratch parser rewrite", activity_count=40)) is None


def test_without_repository_removes_only_that_repository() -> None:
    filtered = without_repository(_scan(), "repo-a")
    assert "repo-a" not in filtered.sessions_by_repository
    assert "repo-b" in filtered.sessions_by_repository
    assert all(item.session.session_id != "ses-a1" for item in filtered.resolved_sessions)
    assert all(item.session.session_id != "ses-a2" for item in filtered.resolved_sessions)
    assert filtered.loaded_session_count == 1


def test_without_repository_keeps_scan_metadata() -> None:
    scan = _scan()
    filtered = without_repository(scan, "repo-a")
    assert filtered.period is scan.period
    assert filtered.candidate_session_count == 5
    assert filtered.failed_session_count == 2
    assert filtered.excluded_session_count == 2
    assert filtered.warnings == ["one warning"]


def test_without_repository_unknown_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        without_repository(_scan(), "repo-nope")


def test_exclude_repository_prunes_scan_and_selection() -> None:
    state = SelectionState.from_scan(_scan())
    state.exclude_repository("repo-a")
    assert "repo-a" not in state.scan.sessions_by_repository
    assert state.total_count == 1
    assert state.selected_count == 1
    assert state.selected_session_ids == {"ses-b1"}
