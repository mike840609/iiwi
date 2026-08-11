from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from iiwi.interactive.models import ReportDraft
from iiwi.models.report_options import ReportType
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.renderers.markdown import DetailLevel
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def test_report_type_applies_default_detail_until_detail_is_explicit() -> None:
    draft = ReportDraft(harness="opencode", period=_period(20))
    draft.set_report_type(ReportType.MANAGER)
    assert draft.detail is DetailLevel.BRIEF

    draft.set_detail(DetailLevel.FULL)
    draft.set_report_type(ReportType.ENGINEERING)
    draft.set_report_type(ReportType.MANAGER)
    assert draft.detail is DetailLevel.FULL


def _period(day: int) -> DateRange:
    return DateRange(
        since=datetime(2026, 7, day, tzinfo=TZ),
        until=datetime(2026, 7, day + 1, tzinfo=TZ),
    )


def _draft_with_scan() -> ReportDraft:
    draft = ReportDraft(harness="opencode", period=_period(20))
    draft.scan = object()  # type: ignore[assignment]
    draft.selected_session_ids = {"ses-a", "ses-b"}
    return draft


def test_period_change_clears_scan_and_selection() -> None:
    draft = _draft_with_scan()

    draft.set_period("Last 21 days", _period(21))

    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_harness_change_clears_scan_and_selection() -> None:
    draft = _draft_with_scan()

    draft.set_harness("codex")

    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_subagent_change_clears_scan_and_selection() -> None:
    draft = _draft_with_scan()

    draft.set_include_subagents(False)

    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_sanitize_change_clears_scan_and_selection() -> None:
    draft = _draft_with_scan()

    draft.set_sanitize(True)

    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_non_scan_identity_changes_keep_cached_scan_and_selection() -> None:
    draft = _draft_with_scan()
    scan = draft.scan

    draft.set_detail(DetailLevel.BRIEF)
    draft.set_narrative(False)
    draft.set_dry_run(True)

    assert draft.scan is scan
    assert draft.selected_session_ids == {"ses-a", "ses-b"}


def test_setting_same_scan_identity_value_does_not_clear_cache() -> None:
    draft = _draft_with_scan()
    scan = draft.scan

    draft.set_harness("opencode")
    draft.set_period("Last 20 days", _period(20))
    draft.set_include_subagents(True)
    draft.set_sanitize(False)

    assert draft.scan is scan
    assert draft.selected_session_ids == {"ses-a", "ses-b"}


def _resolved(session_id: str, *, title: str | None, activity_count: int) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=title,
            working_directory="/tmp/repo-a",
            activities=[
                SessionActivity(
                    activity_id=f"{session_id}-{i}",
                    activity_type=ActivityType.USER_MESSAGE,
                )
                for i in range(activity_count)
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="repo-a",
            display_name="repo-a",
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory="/tmp/repo-a",
            resolution_method="test",
        ),
    )


def test_set_scan_deselects_noise_sessions_but_keeps_substantive_work() -> None:
    draft = ReportDraft(harness="opencode", period=_period(20))
    sessions = [
        _resolved("ses-real", title="Fix sanitize export bug", activity_count=40),
        _resolved("ses-untitled", title=None, activity_count=40),
        _resolved("ses-thin", title="Quick check", activity_count=1),
    ]
    scan = ScanResult(
        period=_period(20),
        candidate_session_count=3,
        loaded_session_count=3,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )

    draft.set_scan(scan)

    assert draft.selected_session_ids == {"ses-real"}
