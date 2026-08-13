from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from iiwi.models import EvidenceRef, Outcome, OutcomeBucket, OutcomeOrigin, OutcomeStatus
from iiwi.models.daily import DailySection, DailyStatementSource
from iiwi.models.repository import RepositoryIdentity, RepositoryIdentityType, ResolvedSession
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.services.daily_projection import build_daily_fallback, project_daily_standup
from iiwi.services.daily_scan import DailyScanResult, daily_window
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")
YESTERDAY = datetime(2026, 8, 12, 9, 0, tzinfo=TZ)
TODAY = datetime(2026, 8, 13, 9, 0, tzinfo=TZ)
NOW = datetime(2026, 8, 13, 10, 0, tzinfo=TZ)


def activity(
    activity_id: str,
    timestamp: datetime | None,
    *,
    activity_type: ActivityType = ActivityType.USER_MESSAGE,
    content: str = "Implement the Daily view",
    tool_name: str | None = None,
    exit_code: int | None = None,
) -> SessionActivity:
    metadata: dict[str, object] = {}
    if exit_code is not None:
        metadata["exit_code"] = exit_code
    return SessionActivity(
        activity_id=activity_id,
        activity_type=activity_type,
        timestamp=timestamp,
        content=content,
        tool_name=tool_name,
        metadata=metadata,
    )


def resolved_session(
    session_id: str,
    activities: list[SessionActivity],
    *,
    harness: str = "codex",
    repository_id: str = "git:github.com/example/iiwi",
    display_name: str = "iiwi",
    title: str | None = "Daily work",
) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness=harness,
            session_id=session_id,
            title=title,
            activities=activities,
        ),
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=display_name,
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            normalized_remote=repository_id.removeprefix("git:"),
            resolution_method="git_origin_remote",
        ),
    )


def daily_scan(
    sessions: list[ResolvedSession],
    *,
    warnings: list[str] | None = None,
    coverage_warnings: tuple[str, ...] = (),
) -> DailyScanResult:
    window = daily_window(NOW)
    repositories: dict[str, list[ResolvedSession]] = {}
    for session in sessions:
        repositories.setdefault(session.repository.repository_id, []).append(session)
    scan = ScanResult(
        period=window.period,
        candidate_session_count=len(sessions),
        loaded_session_count=len(sessions),
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository=repositories,
        warnings=warnings or [],
    )
    return DailyScanResult(
        window=window,
        scan=scan,
        successful_harnesses=("codex",),
        unavailable_harnesses=("claude-code",) if coverage_warnings else (),
        coverage_warnings=coverage_warnings,
    )


def evidence_ref(
    session_id: str,
    activity_ids: list[str],
    *,
    harness: str = "codex",
    repository_id: str = "git:github.com/example/iiwi",
) -> EvidenceRef:
    return EvidenceRef(
        harness=harness,
        session_id=session_id,
        repository_id=repository_id,
        activity_ids=activity_ids,
    )


def outcome(
    identifier: str,
    refs: list[EvidenceRef],
    *,
    status: OutcomeStatus = OutcomeStatus.IN_PROGRESS,
    rank: int = 0,
    title: str | None = None,
) -> Outcome:
    return Outcome(
        id=identifier,
        title=title or f"Outcome {identifier}",
        status=status,
        rank=rank,
        evidence_refs=refs,
    )


def test_one_grouped_outcome_projects_actual_activity_into_both_sections() -> None:
    session = resolved_session(
        "s1",
        [
            activity("y1", YESTERDAY, activity_type=ActivityType.FILE_CHANGE),
            activity("t1", TODAY, activity_type=ActivityType.FILE_CHANGE),
        ],
    )
    grouped = outcome("o1", [evidence_ref("s1", ["y1", "t1"])], title="Build Daily")

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    assert len(draft.work_items) == 1
    work = draft.work_items[0]
    assert work.source_outcome_ids == ["o1"]
    assert work.repository_ids == ["git:github.com/example/iiwi"]
    assert work.yesterday is not None
    assert work.today is not None
    assert work.yesterday.source is DailyStatementSource.ACTIVITY_YESTERDAY
    assert work.today.source is DailyStatementSource.ACTIVITY_TODAY
    assert work.yesterday.statement == "Build Daily"
    assert work.today.statement == "Build Daily"
    assert work.yesterday.evidence_refs[0].activity_ids == ["y1"]
    assert work.today.evidence_refs[0].activity_ids == ["t1"]


def test_projection_uses_half_open_windows_and_never_guesses_missing_timestamps() -> None:
    window = daily_window(NOW)
    session = resolved_session(
        "s1",
        [
            activity(
                "before",
                window.yesterday_start - timedelta(microseconds=1),
                activity_type=ActivityType.FILE_CHANGE,
            ),
            activity("y-start", window.yesterday_start, activity_type=ActivityType.FILE_CHANGE),
            activity("t-start", window.today_start, activity_type=ActivityType.FILE_CHANGE),
            activity("now", window.now, activity_type=ActivityType.FILE_CHANGE),
            activity("untimed", None, activity_type=ActivityType.FILE_CHANGE),
        ],
    )
    grouped = outcome(
        "o1",
        [evidence_ref("s1", ["before", "y-start", "t-start", "now", "untimed"])],
    )

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    work = draft.work_items[0]
    assert work.yesterday is not None
    assert work.today is not None
    assert work.yesterday.evidence_refs[0].activity_ids == ["y-start"]
    assert work.today.evidence_refs[0].activity_ids == ["t-start"]


def test_yesterday_in_progress_goal_with_tangible_work_suggests_today() -> None:
    session = resolved_session(
        "s1",
        [
            activity("goal", YESTERDAY),
            activity("file", YESTERDAY, activity_type=ActivityType.FILE_CHANGE),
        ],
    )
    grouped = outcome("o1", [evidence_ref("s1", ["goal", "file"])])

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    today = draft.work_items[0].today
    assert today is not None
    assert today.source is DailyStatementSource.SUGGESTED_FROM_YESTERDAY
    assert today.statement == "Outcome o1"
    assert today.evidence_refs[0].activity_ids == ["goal"]
    assert today.new_activity is False


def test_completed_yesterday_outcome_does_not_suggest_today() -> None:
    session = resolved_session(
        "s1",
        [
            activity("goal", YESTERDAY),
            activity("file", YESTERDAY, activity_type=ActivityType.FILE_CHANGE),
        ],
    )
    grouped = outcome(
        "o1",
        [evidence_ref("s1", ["goal", "file"])],
        status=OutcomeStatus.COMPLETED,
    )

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    assert draft.work_items[0].today is None


def test_plan_without_evidence_does_not_suggest_today() -> None:
    plan = Outcome(
        id="plan",
        title="Plan tomorrow",
        status=OutcomeStatus.IN_PROGRESS,
        rank=0,
        origin=OutcomeOrigin.USER_ADDED,
    )

    draft = project_daily_standup(daily_scan=daily_scan([]), outcomes=[plan])

    assert draft.work_items == []


def test_timestamp_less_support_does_not_suggest_today() -> None:
    session = resolved_session("s1", [activity("goal", None)])
    grouped = outcome("o1", [evidence_ref("s1", ["goal"])])

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    assert draft.work_items == []


def test_unresolved_failed_command_is_an_excluded_blocker_candidate() -> None:
    session = resolved_session(
        "s1",
        [
            activity("goal", YESTERDAY),
            activity(
                "failure",
                TODAY,
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=1,
            ),
        ],
    )
    grouped = outcome("o1", [evidence_ref("s1", ["goal", "failure"])])

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    blocker = draft.work_items[0].blocker
    assert blocker is not None
    assert blocker.source is DailyStatementSource.DETECTED_BLOCKER
    assert blocker.statement == "uv run pytest"
    assert blocker.included is False


def test_later_completion_in_the_same_source_resolves_blocker_candidate() -> None:
    session = resolved_session(
        "s1",
        [
            activity(
                "failure",
                YESTERDAY,
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=1,
            ),
            activity(
                "success",
                TODAY,
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=0,
            ),
        ],
    )
    grouped = outcome("o1", [evidence_ref("s1", ["failure", "success"])])

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    assert draft.work_items[0].blocker is None


def test_later_successful_retry_of_an_ordinary_command_resolves_blocker_candidate() -> None:
    session = resolved_session(
        "s1",
        [
            activity(
                "failure",
                YESTERDAY,
                activity_type=ActivityType.COMMAND,
                content="git push",
                exit_code=1,
            ),
            activity(
                "success",
                TODAY,
                activity_type=ActivityType.COMMAND,
                content="git push",
                exit_code=0,
            ),
        ],
    )
    # Extraction de-duplicates the identical successful retry from the source ref.
    grouped = outcome("o1", [evidence_ref("s1", ["failure"])])

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    assert draft.work_items[0].blocker is None


def test_failure_after_a_successful_retry_remains_a_blocker_candidate() -> None:
    session = resolved_session(
        "s1",
        [
            activity(
                "failure-1",
                YESTERDAY,
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=1,
            ),
            activity(
                "success",
                TODAY.replace(minute=10),
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=0,
            ),
            activity(
                "failure-2",
                TODAY.replace(minute=20),
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=1,
            ),
        ],
    )
    grouped = outcome(
        "o1",
        # The repeated final failure is absent after evidence de-duplication.
        [evidence_ref("s1", ["failure-1", "success"])],
    )

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    blocker = draft.work_items[0].blocker
    assert blocker is not None
    assert blocker.statement == "uv run pytest"
    assert blocker.evidence_refs[0].activity_ids == ["failure-2"]


def test_completed_grouped_outcome_does_not_create_blocker_candidate() -> None:
    session = resolved_session(
        "s1",
        [
            activity(
                "failure",
                YESTERDAY,
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=1,
            )
        ],
    )
    grouped = outcome(
        "o1",
        [evidence_ref("s1", ["failure"])],
        status=OutcomeStatus.COMPLETED,
    )

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    assert draft.work_items[0].blocker is None


def test_completion_in_another_source_does_not_resolve_blocker_candidate() -> None:
    failed = resolved_session(
        "failed",
        [
            activity(
                "failure",
                YESTERDAY,
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=1,
            )
        ],
    )
    completed = resolved_session(
        "completed",
        [
            activity(
                "success",
                TODAY,
                activity_type=ActivityType.COMMAND,
                content="uv run pytest",
                exit_code=0,
            )
        ],
    )
    grouped = outcome(
        "o1",
        [evidence_ref("failed", ["failure"]), evidence_ref("completed", ["success"])],
    )

    draft = project_daily_standup(
        daily_scan=daily_scan([failed, completed]),
        outcomes=[grouped],
    )

    assert draft.work_items[0].blocker is not None


def test_yesterday_and_today_cap_primary_items_but_blockers_are_not_capped() -> None:
    sessions: list[ResolvedSession] = []
    outcomes: list[Outcome] = []
    for rank in range(6):
        session_id = f"s{rank}"
        ids = [f"y{rank}", f"t{rank}", f"failure{rank}"]
        sessions.append(
            resolved_session(
                session_id,
                [
                    activity(
                        ids[0],
                        YESTERDAY,
                        activity_type=ActivityType.FILE_CHANGE,
                    ),
                    activity(ids[1], TODAY, activity_type=ActivityType.FILE_CHANGE),
                    activity(
                        ids[2],
                        TODAY,
                        activity_type=ActivityType.COMMAND,
                        content=f"pytest failing-{rank}",
                        exit_code=1,
                    ),
                ],
            )
        )
        outcomes.append(outcome(f"o{rank}", [evidence_ref(session_id, ids)], rank=rank))

    draft = project_daily_standup(daily_scan=daily_scan(sessions), outcomes=outcomes)

    for section in (DailySection.YESTERDAY, DailySection.TODAY):
        items = [item for _, item in draft.ordered_items(section)]
        assert [item.bucket for item in items] == [OutcomeBucket.PRIMARY] * 5 + [
            OutcomeBucket.MORE
        ]
        assert [item.included for item in items] == [True] * 5 + [False]
    blockers = [item for _, item in draft.ordered_items(DailySection.BLOCKERS)]
    assert len(blockers) == 6
    assert all(item.bucket is OutcomeBucket.PRIMARY for item in blockers)
    assert all(item.included is False for item in blockers)


def test_goal_only_session_does_not_become_factual_yesterday_activity() -> None:
    session = resolved_session(
        "s1",
        [activity("plan", YESTERDAY, content="Plan the migration tomorrow")],
    )
    grouped = outcome("o1", [evidence_ref("s1", ["plan"])])

    draft = project_daily_standup(daily_scan=daily_scan([session]), outcomes=[grouped])

    assert draft.work_items == []


def test_fallback_omits_a_goal_only_session() -> None:
    session = resolved_session(
        "s1",
        [activity("plan", YESTERDAY, content="Plan the migration tomorrow")],
    )

    draft = build_daily_fallback(daily_scan=daily_scan([session]))

    assert draft.work_items == []


def test_fallback_uses_goal_text_to_label_tangible_activity() -> None:
    session = resolved_session(
        "s1",
        [
            activity("goal", YESTERDAY, content="Migrate the database"),
            activity(
                "file",
                YESTERDAY.replace(hour=11),
                activity_type=ActivityType.FILE_CHANGE,
                content="migrations/001.sql",
            ),
        ],
    )

    draft = build_daily_fallback(daily_scan=daily_scan([session]))

    yesterday = draft.work_items[0].yesterday
    assert yesterday is not None
    assert yesterday.statement == "Migrate the database"


def test_projection_appends_synthesis_warnings_after_scan_warnings() -> None:
    scan = daily_scan([], warnings=["scan warning"])

    draft = project_daily_standup(
        daily_scan=scan,
        outcomes=[],
        synthesis_warnings=["evidence budget omitted one session"],
    )

    assert draft.warnings == [
        "scan warning",
        "evidence budget omitted one session",
    ]


def test_fallback_uses_local_evidence_priority_and_preserves_scan_metadata() -> None:
    session = resolved_session(
        "s1",
        [
            activity("goal", YESTERDAY, content="Build Daily"),
            activity(
                "claim",
                YESTERDAY.replace(hour=11),
                activity_type=ActivityType.ASSISTANT_MESSAGE,
                content="Implemented Daily projection",
            ),
            activity("today", TODAY, content="Continue Daily"),
            activity(
                "today-file",
                TODAY.replace(minute=30),
                activity_type=ActivityType.FILE_CHANGE,
                content="src/daily.py",
            ),
        ],
        title="token=secret-title",
    )
    scan = daily_scan(
        [session],
        warnings=["scan warning"],
        coverage_warnings=("Claude Code activity could not be loaded.",),
    )

    draft = build_daily_fallback(daily_scan=scan)

    assert draft.fallback is True
    assert draft.warnings == ["scan warning"]
    assert draft.coverage_warnings == ["Claude Code activity could not be loaded."]
    assert draft.successful_harnesses == ["codex"]
    assert draft.unavailable_harnesses == ["claude-code"]
    assert draft.repository_count == 1
    assert draft.session_count == 1
    assert len(draft.work_items) == 1
    work = draft.work_items[0]
    assert work.yesterday is not None
    assert work.today is not None
    assert work.yesterday.statement == "Implemented Daily projection"
    assert work.yesterday.source is DailyStatementSource.ACTIVITY_YESTERDAY
    assert work.today.statement == "Continue Daily"
    assert work.today.source is DailyStatementSource.ACTIVITY_TODAY


def test_fallback_suggests_best_yesterday_statement_when_an_in_progress_goal_supports_it() -> None:
    session = resolved_session(
        "s1",
        [
            activity("goal", YESTERDAY, content="Build Daily"),
            activity(
                "claim",
                YESTERDAY.replace(hour=11),
                activity_type=ActivityType.ASSISTANT_MESSAGE,
                content="Implemented the first Daily slice",
            ),
        ],
    )

    draft = build_daily_fallback(daily_scan=daily_scan([session]))

    today = draft.work_items[0].today
    assert today is not None
    assert today.statement == "Implemented the first Daily slice"
    assert today.source is DailyStatementSource.SUGGESTED_FROM_YESTERDAY
    assert today.evidence_refs[0].activity_ids == ["goal"]


def test_fallback_redacts_session_title_when_no_statement_evidence_exists() -> None:
    session = resolved_session(
        "s1",
        [
            activity(
                "file",
                TODAY,
                activity_type=ActivityType.FILE_CHANGE,
                content="src/daily.py",
            )
        ],
        title="Fix token=super-secret-value",
    )

    draft = build_daily_fallback(daily_scan=daily_scan([session]))

    today = draft.work_items[0].today
    assert today is not None
    assert today.statement == "Fix token=[REDACTED]"
