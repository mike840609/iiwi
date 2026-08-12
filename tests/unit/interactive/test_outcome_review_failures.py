from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi import cli
from iiwi.errors import OutcomeSynthesisError, ReportAlreadyExistsError, ReportOutputError
from iiwi.interactive import cli_actions, controller
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeBucket,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeStatus,
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
FALLBACK_NOTICE = "Outcome synthesis unavailable; generated the session-based report."


def char(value: str) -> KeyPress:
    return KeyPress(char=value)


class ScriptedInput:
    def __init__(self, keys: list[KeyPress]) -> None:
        self._keys: Iterator[KeyPress] = iter(keys)

    def __enter__(self) -> ScriptedInput:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read_key(self) -> KeyPress:
        return next(self._keys)


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _scan() -> ScanResult:
    repository = RepositoryIdentity(
        repository_id="repo-a",
        display_name="repo-a",
        identity_type=RepositoryIdentityType.PATH_FALLBACK,
        working_directory="/tmp/repo-a",
        resolution_method="test",
    )
    sessions = []
    for session_id in ("ses-a", "ses-b"):
        session = AgentSession(
            harness="opencode",
            session_id=session_id,
            title=session_id,
            working_directory="/tmp/repo-a",
            activities=[
                SessionActivity(
                    activity_id=f"{session_id}-activity-{index}",
                    activity_type=ActivityType.USER_MESSAGE,
                )
                for index in range(5)
            ],
        )
        sessions.append(ResolvedSession(session=session, repository=repository))
    return ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )


def _outcome(
    identifier: str,
    rank: int,
    *,
    bucket: OutcomeBucket = OutcomeBucket.PRIMARY,
    included: bool = True,
    title: str | None = None,
    origin: OutcomeOrigin = OutcomeOrigin.SYNTHESIZED,
) -> Outcome:
    evidence_refs = (
        [EvidenceRef(session_id=f"ses-{identifier}", repository_id="repo-a")]
        if origin is OutcomeOrigin.SYNTHESIZED
        else []
    )
    return Outcome(
        id=identifier,
        title=title or f"Outcome {identifier}",
        status=OutcomeStatus.IN_PROGRESS,
        impact=f"Impact {identifier}",
        included=included,
        rank=rank,
        origin=origin,
        bucket=bucket,
        evidence_refs=evidence_refs,
    )


def _review(*outcomes: Outcome) -> OutcomeReviewDraft:
    return OutcomeReviewDraft(outcomes=list(outcomes) or [_outcome("a", 0)])


class ActionLog:
    def __init__(self) -> None:
        self.scan_count = 0
        self.synthesis_scans: list[ScanResult] = []
        self.session_calls: list[tuple[ReportDraft, ScanResult, bool, str | None]] = []
        self.session_results: list[InteractiveReportResult] = []
        self.reviewed_calls: list[
            tuple[ReportDraft, ScanResult, OutcomeReviewDraft, bool, bool]
        ] = []


def _actions(
    draft: ReportDraft,
    log: ActionLog,
    *,
    synthesize: Callable[[ReportDraft, ScanResult], OutcomeReviewDraft],
    generate_session: Callable[[ReportDraft, ScanResult, bool], InteractiveReportResult]
    | None = None,
    generate_reviewed: Callable[
        [ReportDraft, ScanResult, OutcomeReviewDraft, bool], InteractiveReportResult
    ]
    | None = None,
) -> InteractiveActions:
    scan = _scan()

    def do_scan(current: ReportDraft) -> ScanResult:
        log.scan_count += 1
        return scan

    def generate(
        current: ReportDraft,
        selected_scan: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        if generate_session is not None:
            return generate_session(current, selected_scan, force)
        notice = current.generation_notice
        log.session_calls.append((current, selected_scan, force, notice))
        result = InteractiveReportResult(
            output_path=Path("reports/session-based.md"),
            content=f"## Warnings\n\n- {notice}",
            repository_count=1,
            session_count=selected_scan.loaded_session_count,
        )
        log.session_results.append(result)
        return result

    def reviewed(
        current: ReportDraft,
        selected_scan: ScanResult,
        review: OutcomeReviewDraft,
        force: bool,
    ) -> InteractiveReportResult:
        log.reviewed_calls.append((current, selected_scan, review, force, current.dry_run))
        if generate_reviewed is not None:
            return generate_reviewed(current, selected_scan, review, force)
        return InteractiveReportResult(
            output_path=None if current.dry_run else Path("reports/reviewed.md"),
            content="reviewed-content",
            repository_count=1,
            session_count=selected_scan.loaded_session_count,
        )

    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("This week", _period()),
        scan=do_scan,
        generate=generate,
        synthesize=lambda current, selected_scan: (
            log.synthesis_scans.append(selected_scan) or synthesize(current, selected_scan)
        ),
        generate_reviewed=reviewed,
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def _run(
    draft: ReportDraft,
    log: ActionLog,
    keys: list[KeyPress],
    *,
    synthesize: Callable[[ReportDraft, ScanResult], OutcomeReviewDraft],
    generate_session: Callable[[ReportDraft, ScanResult, bool], InteractiveReportResult]
    | None = None,
    generate_reviewed: Callable[
        [ReportDraft, ScanResult, OutcomeReviewDraft, bool], InteractiveReportResult
    ]
    | None = None,
) -> tuple[list[Screen], str]:
    screens: list[Screen] = []
    original_render = controller._render_screen

    def capture(state, console: Console) -> None:
        screens.append(state.screen)
        original_render(state, console)

    controller._render_screen = capture
    stream = StringIO()
    try:
        run_interactive(
            actions=_actions(
                draft,
                log,
                synthesize=synthesize,
                generate_session=generate_session,
                generate_reviewed=generate_reviewed,
            ),
            input_source=ScriptedInput(keys),
            console=Console(
                file=stream,
                color_system=None,
                force_terminal=False,
                width=100,
                height=30,
            ),
        )
    finally:
        controller._render_screen = original_render
    return screens, stream.getvalue()


def _open_review_keys() -> list[KeyPress]:
    return [char("2"), char("r"), char("g")]


def test_synthesis_retry_reuses_filtered_scan_and_opens_quick_review() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review()
    log = ActionLog()
    attempts = 0

    def synthesize(current: ReportDraft, selected_scan: ScanResult) -> OutcomeReviewDraft:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OutcomeSynthesisError("temporary synthesis failure")
        return review

    screens, output = _run(
        draft,
        log,
        [*_open_review_keys(), KeyPress(key=Key.ENTER), char("b"), char("q"), char("q")],
        synthesize=synthesize,
    )

    assert attempts == 2
    assert log.scan_count == 1
    assert [item.session.session_id for item in log.synthesis_scans[0].resolved_sessions] == [
        item.session.session_id for item in log.synthesis_scans[1].resolved_sessions
    ]
    assert "Retry" in output
    assert Screen.OUTCOME_REVIEW in screens


def test_complete_synthesis_failure_can_generate_labeled_session_fallback() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog()

    def fail_synthesis(current: ReportDraft, selected_scan: ScanResult) -> OutcomeReviewDraft:
        raise OutcomeSynthesisError("synthesis unavailable")

    _, output = _run(
        draft,
        log,
        [
            *_open_review_keys(),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("q"),
            char("q"),
        ],
        synthesize=fail_synthesis,
    )

    assert "Use session-based report" in output
    assert len(log.session_calls) == 1
    assert log.session_calls[0][3] == FALLBACK_NOTICE
    assert FALLBACK_NOTICE in log.session_results[0].content
    assert draft.generation_notice is None


def test_session_fallback_notice_survives_output_conflict_overwrite() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog()

    def fail_synthesis(current: ReportDraft, selected_scan: ScanResult) -> OutcomeReviewDraft:
        raise OutcomeSynthesisError("synthesis unavailable")

    def conflict_once(
        current: ReportDraft,
        selected_scan: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        notice = current.generation_notice
        log.session_calls.append((current, selected_scan, force, notice))
        if not force:
            raise ReportAlreadyExistsError("session fallback exists")
        result = InteractiveReportResult(
            output_path=Path("reports/session-based.md"),
            content=f"## Warnings\n\n- {notice}",
            repository_count=1,
            session_count=selected_scan.loaded_session_count,
        )
        log.session_results.append(result)
        return result

    _, output = _run(
        draft,
        log,
        [
            *_open_review_keys(),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.ENTER),
            char("q"),
            char("q"),
        ],
        synthesize=fail_synthesis,
        generate_session=conflict_once,
    )

    assert "Overwrite once" in output
    assert [call[2] for call in log.session_calls] == [False, True]
    assert [call[3] for call in log.session_calls] == [FALLBACK_NOTICE, FALLBACK_NOTICE]
    assert FALLBACK_NOTICE in log.session_results[0].content
    assert draft.generation_notice is None


def test_session_generation_threads_only_an_explicit_fallback_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(
        harness="opencode",
        period=_period(),
        dry_run=True,
        generation_notice=FALLBACK_NOTICE,
    )
    captured: list[dict[str, object]] = []

    class FakeService:
        def generate(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                output_path=Path("reports/session-based.md"),
                content=f"## Warnings\n\n- {FALLBACK_NOTICE}",
                report=SimpleNamespace(narrative_text=None),
            )

    monkeypatch.setattr(
        cli,
        "_load_settings",
        lambda: SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei")),
    )
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 8, 10, 12, tzinfo=TZ),
    )
    monkeypatch.setattr(
        cli,
        "_default_output_path",
        lambda settings, period: Path("reports/session-based.md"),
    )
    monkeypatch.setattr(
        cli,
        "_build_report_service",
        lambda *args, **kwargs: captured.append(kwargs) or FakeService(),
    )

    result = cli_actions._generate(draft, _scan(), False)

    assert captured[0]["initial_warnings"] == [FALLBACK_NOTICE]
    assert FALLBACK_NOTICE in result.content
    assert ReportDraft(harness="opencode", period=_period()).generation_notice is None


def test_partial_synthesis_opens_review_with_primary_and_ungrouped_candidates() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog()
    review = _review(
        _outcome("primary", 0, title="Successful primary outcome"),
        _outcome(
            "failed",
            1,
            bucket=OutcomeBucket.UNGROUPED,
            title="Failed session candidate",
        ),
    )

    screens, output = _run(
        draft,
        log,
        [*_open_review_keys(), char("b"), char("q"), char("q")],
        synthesize=lambda current, selected_scan: review,
    )

    assert Screen.OUTCOME_REVIEW in screens
    assert "Successful primary outcome" in output
    assert "Ungrouped candidates" in output


def test_preview_error_back_restores_the_complete_in_memory_review() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog()
    review = _review(
        _outcome("b", 0, included=False),
        _outcome("a", 1, title="Edited outcome"),
        _outcome(
            "user-added",
            2,
            title="User-added outcome",
            origin=OutcomeOrigin.USER_ADDED,
        ),
    )
    review.blockers = "Waiting for approval"
    review.next_week = "Ship the reviewed change"

    def fail_preview(
        current: ReportDraft,
        selected_scan: ScanResult,
        received_review: OutcomeReviewDraft,
        force: bool,
    ) -> InteractiveReportResult:
        raise ReportOutputError("preview failed")

    screens, output = _run(
        draft,
        log,
        [
            *_open_review_keys(),
            char("p"),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
            char("q"),
        ],
        synthesize=lambda current, selected_scan: review,
        generate_reviewed=fail_preview,
    )

    assert "Back to Quick Review" in output
    assert screens.count(Screen.OUTCOME_REVIEW) >= 2
    assert log.reviewed_calls[0][2] is review
    assert [(item.id, item.included, item.title) for item in review.ordered()] == [
        ("b", False, "Outcome b"),
        ("a", True, "Edited outcome"),
        ("user-added", True, "User-added outcome"),
    ]
    assert review.outcomes[2].origin is OutcomeOrigin.USER_ADDED
    assert review.blockers == "Waiting for approval"
    assert review.next_week == "Ship the reviewed change"


def test_preview_retry_uses_the_same_review_draft_and_succeeds() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog()
    review = _review(_outcome("a", 0, included=False), _outcome("b", 1))
    attempts = 0

    def preview_once(
        current: ReportDraft,
        selected_scan: ScanResult,
        received_review: OutcomeReviewDraft,
        force: bool,
    ) -> InteractiveReportResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ReportOutputError("temporary preview failure")
        return InteractiveReportResult(
            output_path=None,
            content="reviewed preview",
            repository_count=1,
            session_count=2,
        )

    screens, output = _run(
        draft,
        log,
        [
            *_open_review_keys(),
            char("p"),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("b"),
            char("q"),
            char("q"),
        ],
        synthesize=lambda current, selected_scan: review,
        generate_reviewed=preview_once,
    )

    assert "Retry" in output
    assert attempts == 2
    assert [call[2] is review for call in log.reviewed_calls] == [True, True]
    assert [call[4] for call in log.reviewed_calls] == [True, True]
    assert review.outcomes[0].included is False
    assert Screen.REPORT_PREVIEW in screens


def test_reviewed_write_conflict_overwrites_with_reviewed_generation() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog()
    review = _review()

    def conflict_once(
        current: ReportDraft,
        selected_scan: ScanResult,
        received_review: OutcomeReviewDraft,
        force: bool,
    ) -> InteractiveReportResult:
        if not force:
            raise ReportAlreadyExistsError("reviewed report exists")
        return InteractiveReportResult(
            output_path=Path("reports/reviewed.md"),
            content="reviewed report",
            repository_count=1,
            session_count=2,
        )

    _, output = _run(
        draft,
        log,
        [*_open_review_keys(), char("g"), KeyPress(key=Key.ENTER), char("q"), char("q")],
        synthesize=lambda current, selected_scan: review,
        generate_reviewed=conflict_once,
    )

    assert "Overwrite once" in output
    assert [call[3] for call in log.reviewed_calls] == [False, True]
    assert [call[2] is review for call in log.reviewed_calls] == [True, True]
    assert log.session_calls == []
