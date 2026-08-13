from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.daily_state import DAILY_STATE_DIR_VARIABLE, save_daily_draft
from iiwi.errors import DailySourceUnavailableError, OutcomeSynthesisError
from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import EvidenceRef, Outcome, OutcomeStatus, OutcomeSynthesisResult
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.services.daily_scan import DailyScanResult, DailyWindow
from iiwi.services.daily_workflow import DailyWorkflowService
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 13, 10, 0, tzinfo=TZ)


def _daily_scan(
    window: DailyWindow,
    *,
    activity: bool,
    metadata_only: bool = False,
) -> DailyScanResult:
    resolved: list[ResolvedSession] = []
    repositories: dict[str, list[ResolvedSession]] = {}
    if activity or metadata_only:
        session = ResolvedSession(
            session=AgentSession(
                harness="codex",
                session_id="session-1",
                activities=(
                    [
                        SessionActivity(
                            activity_id="activity-1",
                            activity_type=ActivityType.FILE_CHANGE,
                            timestamp=datetime(2026, 8, 13, 9, 0, tzinfo=TZ),
                            content="src/iiwi/services/daily_workflow.py",
                        )
                    ]
                    if activity
                    else []
                ),
            ),
            repository=RepositoryIdentity(
                repository_id="repo-a",
                display_name="repo-a",
                identity_type=RepositoryIdentityType.PATH_FALLBACK,
                working_directory="/tmp/repo-a",
                resolution_method="test",
            ),
        )
        resolved = [session]
        repositories = {"repo-a": resolved}
    scan = ScanResult(
        period=window.period,
        candidate_session_count=len(resolved),
        loaded_session_count=len(resolved),
        failed_session_count=0,
        resolved_sessions=resolved,
        sessions_by_repository=repositories,
        warnings=["scan warning"],
    )
    return DailyScanResult(
        window=window,
        scan=scan,
        successful_harnesses=("codex",),
        unavailable_harnesses=("claude-code",),
        coverage_warnings=("Claude Code activity could not be loaded.",),
    )


def _outcome() -> Outcome:
    return Outcome(
        id="outcome-1",
        title="Wire Daily workflow",
        status=OutcomeStatus.IN_PROGRESS,
        rank=0,
        evidence_refs=[
            EvidenceRef(
                harness="codex",
                session_id="session-1",
                repository_id="repo-a",
                activity_ids=["activity-1"],
            )
        ],
    )


class _Coordinator:
    def __init__(
        self,
        window: DailyWindow,
        *,
        activity: bool,
        metadata_only: bool = False,
        error: DailySourceUnavailableError | None = None,
    ) -> None:
        self.window = window
        self.activity = activity
        self.metadata_only = metadata_only
        self.error = error

    def scan(self) -> DailyScanResult:
        if self.error is not None:
            raise self.error
        return _daily_scan(
            self.window,
            activity=self.activity,
            metadata_only=self.metadata_only,
        )


class _Outcomes:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        failed_session_ids: list[str] | None = None,
    ) -> None:
        self.error = error
        self.failed_session_ids = failed_session_ids or []
        self.calls: list[ScanResult] = []

    def synthesize(self, scan: ScanResult) -> OutcomeSynthesisResult:
        self.calls.append(scan)
        if self.error is not None:
            raise self.error
        return OutcomeSynthesisResult(
            outcomes=[_outcome()],
            warnings=["synthesis warning"],
            failed_session_ids=self.failed_session_ids,
        )


def _service(
    *,
    now_factory,
    outcomes: _Outcomes,
    activity: bool = True,
    metadata_only: bool = False,
    source_error: DailySourceUnavailableError | None = None,
) -> DailyWorkflowService:
    return DailyWorkflowService(
        scan_coordinator_factory=lambda window: _Coordinator(
            window,
            activity=activity,
            metadata_only=metadata_only,
            error=source_error,
        ),
        outcome_service=outcomes,  # type: ignore[arg-type]
        now_factory=now_factory,
    )


def _reviewed_draft(standup_date: date, statement: str) -> DailyStandupDraft:
    scan_until = datetime.combine(standup_date, datetime.min.time(), tzinfo=TZ)
    return DailyStandupDraft(
        standup_date=standup_date,
        scan_since=scan_until.replace(day=standup_date.day - 1),
        scan_until=scan_until,
        work_items=[
            DailyStandupWorkItem(
                id=f"manual-{standup_date}",
                today=DailySectionItem(
                    statement=statement,
                    source=DailyStatementSource.USER_ADDED,
                    user_edited=True,
                ),
            )
        ],
    )


def test_refresh_reads_clock_once_and_synthesizes_once_with_separate_warnings() -> None:
    clock_reads: list[None] = []
    outcomes = _Outcomes()

    def now_factory() -> datetime:
        clock_reads.append(None)
        return NOW

    draft = _service(now_factory=now_factory, outcomes=outcomes).refresh()

    assert len(clock_reads) == 1
    assert len(outcomes.calls) == 1
    assert draft.fallback is False
    assert draft.warnings == ["scan warning", "synthesis warning"]
    assert draft.coverage_warnings == ["Claude Code activity could not be loaded."]
    assert draft.work_items[0].today is not None
    assert draft.work_items[0].today.statement == "Wire Daily workflow"


def test_refresh_bypasses_synthesis_for_a_successful_zero_activity_scan() -> None:
    outcomes = _Outcomes(error=AssertionError("zero activity must not synthesize"))

    draft = _service(
        now_factory=lambda: NOW,
        outcomes=outcomes,
        activity=False,
    ).refresh()

    assert outcomes.calls == []
    assert draft.work_items == []
    assert draft.fallback is False


def test_refresh_keeps_synthesis_extraction_omissions_as_review_only_warnings() -> None:
    outcomes = _Outcomes(failed_session_ids=["session-omitted"])

    draft = _service(now_factory=lambda: NOW, outcomes=outcomes).refresh()

    assert any("1 session" in warning and "omitted" in warning for warning in draft.warnings)
    assert draft.coverage_warnings == ["Claude Code activity could not be loaded."]


def test_refresh_bypasses_synthesis_for_a_metadata_only_resolved_session() -> None:
    outcomes = _Outcomes(error=OutcomeSynthesisError("must not synthesize"))

    draft = _service(
        now_factory=lambda: NOW,
        outcomes=outcomes,
        activity=False,
        metadata_only=True,
    ).refresh()

    assert outcomes.calls == []
    assert draft.fallback is False
    assert draft.work_items == []
    assert draft.repository_count == 1
    assert draft.session_count == 1
    assert draft.successful_harnesses == ["codex"]
    assert draft.unavailable_harnesses == ["claude-code"]


def test_refresh_uses_deterministic_fallback_on_outcome_synthesis_error() -> None:
    outcomes = _Outcomes(error=OutcomeSynthesisError("model unavailable"))

    draft = _service(now_factory=lambda: NOW, outcomes=outcomes).refresh()

    assert len(outcomes.calls) == 1
    assert draft.fallback is True
    assert draft.work_items


def test_refresh_reconciles_reviewer_wording_from_the_supplied_same_day_draft() -> None:
    previous = _service(now_factory=lambda: NOW, outcomes=_Outcomes()).refresh()
    assert previous.work_items[0].today is not None
    previous.work_items[0].today.statement = "My reviewed wording"
    previous.work_items[0].today.user_edited = True

    refreshed = _service(now_factory=lambda: NOW, outcomes=_Outcomes()).refresh(previous)

    assert refreshed.work_items[0].today is not None
    assert refreshed.work_items[0].today.statement == "My reviewed wording"
    assert refreshed.work_items[0].today.user_edited is True


def test_refresh_loads_only_the_current_standup_date_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(DAILY_STATE_DIR_VARIABLE, str(tmp_path))
    save_daily_draft(_reviewed_draft(date(2026, 8, 13), "Yesterday plan"))
    save_daily_draft(_reviewed_draft(date(2026, 8, 14), "Current plan"))
    now = datetime(2026, 8, 14, 8, 0, tzinfo=TZ)

    draft = _service(
        now_factory=lambda: now,
        outcomes=_Outcomes(),
        activity=False,
    ).refresh()

    statements = [
        item.today.statement
        for item in draft.work_items
        if item.today is not None
    ]
    assert statements == ["Current plan"]


def test_refresh_reloads_date_keyed_state_when_the_clock_crosses_midnight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(DAILY_STATE_DIR_VARIABLE, str(tmp_path))
    save_daily_draft(_reviewed_draft(date(2026, 8, 13), "Yesterday plan"))
    save_daily_draft(_reviewed_draft(date(2026, 8, 14), "Current plan"))
    ticks = iter(
        [
            datetime(2026, 8, 13, 23, 59, tzinfo=TZ),
            datetime(2026, 8, 14, 0, 1, tzinfo=TZ),
        ]
    )
    service = _service(
        now_factory=lambda: next(ticks),
        outcomes=_Outcomes(),
        activity=False,
    )

    yesterday = service.refresh()
    today = service.refresh(yesterday)

    assert yesterday.work_items[0].today is not None
    assert yesterday.work_items[0].today.statement == "Yesterday plan"
    assert today.work_items[0].today is not None
    assert today.work_items[0].today.statement == "Current plan"


def test_refresh_appends_a_state_load_warning_without_changing_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(DAILY_STATE_DIR_VARIABLE, str(tmp_path))
    (tmp_path / "2026-08-13.json").write_text("not json", encoding="utf-8")

    draft = _service(
        now_factory=lambda: NOW,
        outcomes=_Outcomes(),
        activity=False,
    ).refresh()

    assert draft.warnings[0] == "scan warning"
    assert "Could not load reviewed Daily state" in draft.warnings[1]
    assert draft.coverage_warnings == ["Claude Code activity could not be loaded."]


def test_refresh_propagates_the_original_daily_source_error() -> None:
    original = DailySourceUnavailableError(
        unavailable_harnesses=("codex",),
        standup_date=NOW.date(),
        since=datetime(2026, 8, 12, tzinfo=TZ),
        until=NOW,
    )

    with pytest.raises(DailySourceUnavailableError) as caught:
        _service(
            now_factory=lambda: NOW,
            outcomes=_Outcomes(),
            source_error=original,
        ).refresh()

    assert caught.value is original
