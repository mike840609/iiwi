from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi.errors import ConfigurationError, OutcomeSynthesisError
from iiwi.interactive import controller
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.interactive.render import MORE_CANDIDATES_SECTION
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeBucket,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeSourceGroup,
    OutcomeStatus,
)
from iiwi.models.report_options import DetailLevel, ReportType
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.outcomes import (
    SynthesisBudgetEstimate,
    SynthesisBudgetExceededError,
)
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


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
    session = AgentSession(
        harness="opencode",
        session_id="ses-a",
        title="Session A",
        working_directory="/tmp/repo-a",
        activities=[
            SessionActivity(
                activity_id=f"activity-{index}",
                activity_type=ActivityType.USER_MESSAGE,
            )
            for index in range(5)
        ],
    )
    resolved = ResolvedSession(session=session, repository=repository)
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
        sessions_by_repository={"repo-a": [resolved]},
    )


def _outcome(identifier: str, rank: int, *, groups: int = 0) -> Outcome:
    refs = [
        EvidenceRef(session_id=f"ses-{identifier}-{index}", repository_id=f"repo-{index}")
        for index in range(max(1, groups))
    ]
    return Outcome(
        id=identifier,
        title=f"Outcome {identifier}",
        status=OutcomeStatus.IN_PROGRESS,
        impact=f"Impact {identifier}",
        rank=rank,
        evidence_refs=refs,
        source_groups=[
            OutcomeSourceGroup(
                id=f"group-{index}",
                title=f"Split {index}",
                evidence_refs=[ref],
            )
            for index, ref in enumerate(refs[:groups])
        ],
    )


def _review(*outcomes: Outcome) -> OutcomeReviewDraft:
    return OutcomeReviewDraft(
        outcomes=list(outcomes) or [_outcome("a", 0), _outcome("b", 1)],
        report_type=ReportType.MANAGER,
    )


class ActionLog:
    def __init__(self, review: OutcomeReviewDraft) -> None:
        self.review = review
        self.synthesis_scans: list[ScanResult] = []
        self.reviewed_calls: list[
            tuple[ReportDraft, ScanResult, OutcomeReviewDraft, bool, bool]
        ] = []
        self.gap_calls: list[tuple[str, str | None]] = []
        self.saved_report_types: list[ReportType] = []
        self.edited_outcome: Outcome | None = None
        self.added_outcome: Outcome | None = None
        self.gap_answers: Iterator[str | None] = iter([])


def _actions(draft: ReportDraft, log: ActionLog) -> InteractiveActions:
    scan = _scan()

    def synthesize(
        _draft: ReportDraft, selected_scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        log.synthesis_scans.append(selected_scan)
        return log.review

    def generate_reviewed(
        current_draft: ReportDraft,
        selected_scan: ScanResult,
        review: OutcomeReviewDraft,
        force: bool,
    ) -> InteractiveReportResult:
        log.reviewed_calls.append(
            (current_draft, selected_scan, review, force, current_draft.dry_run)
        )
        return InteractiveReportResult(
            output_path=None if current_draft.dry_run else Path("reports/reviewed.md"),
            content="reviewed-content",
            repository_count=len(selected_scan.sessions_by_repository),
            session_count=selected_scan.loaded_session_count,
        )

    def edit_outcome(outcome: Outcome) -> Outcome:
        return log.edited_outcome or outcome

    def add_outcome() -> Outcome | None:
        return log.added_outcome

    def edit_gap(label: str, current: str | None) -> str | None:
        log.gap_calls.append((label, current))
        return next(log.gap_answers)

    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("This week", _period()),
        scan=lambda current: scan,
        generate=lambda current, selected_scan, force: pytest.fail(
            "session-based generation is reserved for the Task 6 explicit fallback"
        ),
        synthesize=synthesize,
        generate_reviewed=generate_reviewed,
        edit_outcome=edit_outcome,
        add_outcome=add_outcome,
        edit_gap=edit_gap,
        save_report_type=log.saved_report_types.append,
        doctor=lambda harness: [],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def _run(
    monkeypatch: pytest.MonkeyPatch,
    draft: ReportDraft,
    log: ActionLog,
    keys: list[KeyPress],
) -> list[Screen]:
    screens: list[Screen] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: screens.append(state.screen),
    )
    run_interactive(
        actions=_actions(draft, log),
        input_source=ScriptedInput(keys),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )
    return screens


def _open_review_keys() -> list[KeyPress]:
    return [char("3"), char("r"), char("g")]


def test_g_synthesizes_selected_scan_once_and_opens_outcome_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog(_review())

    screens = _run(
        monkeypatch,
        draft,
        log,
        [*_open_review_keys(), char("b"), char("q"), char("q"), char("q")],
    )

    assert len(log.synthesis_scans) == 1
    assert log.synthesis_scans[0].loaded_session_count == 1
    assert Screen.OUTCOME_REVIEW in screens


@pytest.mark.parametrize(
    "setup_keys",
    [
        [char("g")],
        [KeyPress(key=Key.ENTER)],
    ],
)
def test_setup_generate_enters_quick_review_before_rendering_output(
    monkeypatch: pytest.MonkeyPatch,
    setup_keys: list[KeyPress],
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog(_review())

    screens = _run(
        monkeypatch,
        draft,
        log,
        [char("3"), *setup_keys, char("b"), char("q"), char("q"), char("q")],
    )

    assert Screen.OUTCOME_REVIEW in screens
    assert log.reviewed_calls == []


def test_reentering_quick_review_with_unchanged_selection_preserves_existing_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    original = _review(_outcome("first", 0), _outcome("second", 1))
    replacement = _review(_outcome("replacement", 0))
    syntheses = iter([original, replacement])
    log = ActionLog(original)

    def synthesize(
        _draft: ReportDraft, selected_scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        log.synthesis_scans.append(selected_scan)
        return next(syntheses)

    actions = replace(_actions(draft, log), synthesize=synthesize)
    screens: list[Screen] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: screens.append(state.screen),
    )

    run_interactive(
        actions=actions,
        input_source=ScriptedInput(
            [
                *_open_review_keys(),
                char("j"),
                KeyPress(key=Key.SPACE),
                char("b"),
                char("g"),
                char("g"),
                char("q"),
                char("q"),
            ]
        ),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    assert len(log.synthesis_scans) == 1
    assert [item.id for item in log.reviewed_calls[0][2].ordered()] == [
        "first",
        "second",
    ]
    assert log.reviewed_calls[0][2].outcomes[0].included is False
    assert Screen.OUTCOME_REVIEW in screens


def test_report_type_default_change_preserves_review_when_reentering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(
        harness="opencode",
        period=_period(),
        report_type=ReportType.MANAGER,
    )
    original = _review(_outcome("edited", 0), _outcome("kept", 1))
    replacement = _review(_outcome("replacement", 0))
    syntheses = iter([original, replacement])
    log = ActionLog(original)

    def synthesize(
        _draft: ReportDraft, selected_scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        log.synthesis_scans.append(selected_scan)
        return next(syntheses)

    actions = _actions(draft, log)
    actions = InteractiveActions(
        new_draft=actions.new_draft,
        choose_harness=actions.choose_harness,
        choose_period=actions.choose_period,
        scan=actions.scan,
        generate=actions.generate,
        synthesize=synthesize,
        generate_reviewed=actions.generate_reviewed,
        edit_outcome=actions.edit_outcome,
        add_outcome=actions.add_outcome,
        edit_gap=actions.edit_gap,
        save_report_type=actions.save_report_type,
        doctor=actions.doctor,
        restore_selection=actions.restore_selection,
        save_selection=actions.save_selection,
        exclude_repository=actions.exclude_repository,
    )
    monkeypatch.setattr(controller, "_render_screen", lambda state, console: None)

    run_interactive(
        actions=actions,
        input_source=ScriptedInput(
            [
                *_open_review_keys(),
                char("j"),
                KeyPress(key=Key.SPACE),
                char("k"),
                KeyPress(key=Key.ENTER),
                char("b"),
                char("g"),
                char("g"),
                char("q"),
                char("q"),
            ]
        ),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    assert len(log.synthesis_scans) == 1
    reviewed = log.reviewed_calls[0][2]
    assert reviewed is original
    assert reviewed.outcomes[0].included is False
    assert reviewed.report_type is ReportType.ENGINEERING
    assert reviewed.detail is DetailLevel.FULL
    assert draft.report_type is ReportType.ENGINEERING
    assert draft.detail is DetailLevel.FULL


def test_changing_detail_in_setup_regenerates_quick_review_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    original = _review(_outcome("full-detail", 0))
    replacement = _review(_outcome("brief-detail", 0))
    syntheses = iter([original, replacement])
    log = ActionLog(original)

    def synthesize(
        _draft: ReportDraft, selected_scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        log.synthesis_scans.append(selected_scan)
        return next(syntheses)

    actions = _actions(draft, log)
    actions = InteractiveActions(
        new_draft=actions.new_draft,
        choose_harness=actions.choose_harness,
        choose_period=actions.choose_period,
        scan=actions.scan,
        generate=actions.generate,
        synthesize=synthesize,
        generate_reviewed=actions.generate_reviewed,
        edit_outcome=actions.edit_outcome,
        add_outcome=actions.add_outcome,
        edit_gap=actions.edit_gap,
        save_report_type=actions.save_report_type,
        doctor=actions.doctor,
        restore_selection=actions.restore_selection,
        save_selection=actions.save_selection,
        exclude_repository=actions.exclude_repository,
    )

    run_interactive(
        actions=actions,
        input_source=ScriptedInput(
            [
                *_open_review_keys(),
                char("b"),
                char("b"),
                *[KeyPress(key=Key.DOWN) for _ in range(4)],
                KeyPress(key=Key.ENTER),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.ENTER),
                char("g"),
                char("g"),
                char("q"),
                char("q"),
            ]
        ),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    assert draft.detail is DetailLevel.BRIEF
    assert len(log.synthesis_scans) == 2
    assert log.reviewed_calls[0][2].ordered()[0].id == "brief-detail"


def test_up_down_changes_focus_and_space_toggles_the_focused_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review()
    log = ActionLog(review)

    _run(
        monkeypatch,
        draft,
        log,
        [
            *_open_review_keys(),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.SPACE),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.SPACE),
            KeyPress(key=Key.UP),
            char("b"),
            char("q"),
            char("q"),
            char("q"),
        ],
    )

    assert [outcome.included for outcome in review.ordered()] == [False, False]


@pytest.mark.parametrize(
    ("navigation", "reorder"),
    [
        ("jjk", "J"),
        ("jj", "K"),
    ],
)
def test_uppercase_j_and_k_reorder_while_lowercase_j_and_k_only_navigate(
    monkeypatch: pytest.MonkeyPatch,
    navigation: str,
    reorder: str,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review()
    log = ActionLog(review)

    _run(
        monkeypatch,
        draft,
        log,
        [
            *_open_review_keys(),
            *(char(value) for value in navigation),
            char(reorder),
            char("b"),
            char("q"),
            char("q"),
            char("q"),
        ],
    )

    assert [outcome.id for outcome in review.ordered()] == ["b", "a"]


def test_edit_applies_fields_without_losing_identity_or_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _outcome("a", 0)
    original_ref = original.evidence_refs[0]
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(original)
    log = ActionLog(review)
    log.edited_outcome = Outcome(
        id="replacement-id",
        title="Edited title",
        status=OutcomeStatus.COMPLETED,
        impact="Edited impact",
        rank=99,
        origin=OutcomeOrigin.USER_ADDED,
    )

    _run(
        monkeypatch,
        draft,
        log,
        [*_open_review_keys(), char("j"), char("e"), char("b"), char("q"), char("q"), char("q")],
    )

    edited = review.ordered()[0]
    assert (edited.title, edited.status, edited.impact) == (
        "Edited title",
        OutcomeStatus.COMPLETED,
        "Edited impact",
    )
    assert edited.id == "a"
    assert edited.evidence_refs == [original_ref]


def test_split_replaces_a_merged_outcome_with_its_two_source_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(_outcome("merged", 0, groups=2))
    log = ActionLog(review)

    _run(
        monkeypatch,
        draft,
        log,
        [*_open_review_keys(), char("j"), char("s"), char("b"), char("q"), char("q"), char("q")],
    )

    assert [outcome.id for outcome in review.ordered()] == [
        "merged:group-0",
        "merged:group-1",
    ]
    assert [len(outcome.evidence_refs) for outcome in review.ordered()] == [1, 1]


def test_add_creates_a_user_added_outcome_without_copying_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(_outcome("a", 0))
    log = ActionLog(review)
    log.added_outcome = Outcome(
        id="callback-id",
        title="Manual review",
        status=OutcomeStatus.COMPLETED,
        impact="Reduced ambiguity",
        rank=88,
        origin=OutcomeOrigin.USER_ADDED,
    )

    _run(
        monkeypatch,
        draft,
        log,
        [*_open_review_keys(), char("a"), char("b"), char("q"), char("q"), char("q")],
    )

    added = review.ordered()[-1]
    assert added.title == "Manual review"
    assert added.origin is OutcomeOrigin.USER_ADDED
    assert added.evidence_refs == []
    assert added.id != "callback-id"


def test_activating_blockers_and_next_week_edits_each_gap_and_preserves_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(_outcome("a", 0))
    log = ActionLog(review)
    log.gap_answers = iter([None, None])

    _run(
        monkeypatch,
        draft,
        log,
        [
            *_open_review_keys(),
            char("j"),
            char("j"),
            KeyPress(key=Key.ENTER),
            char("j"),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
            char("q"),
            char("q"),
        ],
    )

    assert log.gap_calls == [("Blockers", None), ("Next week", None)]
    assert review.blockers is None
    assert review.next_week is None


def test_report_type_persists_and_detail_defaults_stop_after_an_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(_outcome("a", 0))
    log = ActionLog(review)

    _run(
        monkeypatch,
        draft,
        log,
        [
            *_open_review_keys(),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
            char("q"),
            char("q"),
        ],
    )

    assert review.report_type is ReportType.ENGINEERING
    assert review.detail is DetailLevel.FULL
    assert log.saved_report_types == [ReportType.ENGINEERING]

    overridden = _review(_outcome("b", 0))
    overridden.set_detail(DetailLevel.FULL)
    second_log = ActionLog(overridden)
    _run(
        monkeypatch,
        draft,
        second_log,
        [
            *_open_review_keys(),
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
            char("q"),
            char("q"),
        ],
    )

    assert overridden.report_type is ReportType.MANAGER
    assert overridden.detail is DetailLevel.FULL
    assert second_log.saved_report_types == [
        ReportType.ENGINEERING,
        ReportType.MANAGER,
    ]


def test_report_type_persistence_failure_keeps_the_edited_review_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(
        harness="opencode",
        period=_period(),
        report_type=ReportType.MANAGER,
    )
    review = _review(_outcome("edited", 0))
    log = ActionLog(review)

    def fail_to_save(_report_type: ReportType) -> None:
        raise ConfigurationError("settings file is read-only")

    actions = replace(_actions(draft, log), save_report_type=fail_to_save)
    rendered_states: list[tuple[Screen, str | None]] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: rendered_states.append(
            (state.screen, state.outcome_message)
        ),
    )

    try:
        run_interactive(
            actions=actions,
            input_source=ScriptedInput(
                [
                    *_open_review_keys(),
                    char("j"),
                    KeyPress(key=Key.SPACE),
                    char("k"),
                    KeyPress(key=Key.ENTER),
                    char("b"),
                    char("q"),
                    char("q"),
                    char("q"),
                ]
            ),
            console=Console(file=StringIO(), color_system=None, force_terminal=False),
        )
    except ConfigurationError as exc:
        pytest.fail(f"Quick Review terminated after preference failure: {exc}")

    assert (
        Screen.OUTCOME_REVIEW,
        "Report type changed, but the preference could not be remembered: "
        "settings file is read-only",
    ) in rendered_states
    assert review.outcomes[0].included is False
    assert review.report_type is ReportType.ENGINEERING
    assert review.detail is DetailLevel.FULL
    assert draft.report_type is ReportType.ENGINEERING
    assert draft.detail is DetailLevel.FULL


def test_preview_and_write_use_the_same_review_draft_and_back_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(_outcome("a", 0), _outcome("b", 1))
    log = ActionLog(review)

    screens = _run(
        monkeypatch,
        draft,
        log,
        [
            *_open_review_keys(),
            char("p"),
            char("b"),
            char("j"),
            KeyPress(key=Key.SPACE),
            char("g"),
            char("q"),
            char("q"),
        ],
    )

    assert [call[2] is review for call in log.reviewed_calls] == [True, True]
    assert [call[4] for call in log.reviewed_calls] == [True, False]
    assert review.outcomes[0].included is False
    assert Screen.REPORT_PREVIEW in screens
    assert screens.count(Screen.OUTCOME_REVIEW) >= 2
    assert Screen.REPORT_RESULT in screens


def test_narrative_off_writes_the_session_report_without_synthesizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period(), narrative=False)
    log = ActionLog(_review())
    session_calls: list[ReportDraft] = []

    def generate(
        current_draft: ReportDraft,
        selected_scan: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        session_calls.append(current_draft)
        return InteractiveReportResult(
            output_path=Path("reports/session.md"),
            content="session-content",
            repository_count=len(selected_scan.sessions_by_repository),
            session_count=selected_scan.loaded_session_count,
        )

    def synthesize(
        _draft: ReportDraft, selected_scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        pytest.fail("Narrative off must not spend a synthesis run")

    actions = replace(_actions(draft, log), generate=generate, synthesize=synthesize)
    screens: list[Screen] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: screens.append(state.screen),
    )

    run_interactive(
        actions=actions,
        input_source=ScriptedInput([*_open_review_keys(), char("q"), char("q")]),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    assert len(session_calls) == 1
    assert Screen.REPORT_RESULT in screens
    assert Screen.OUTCOME_REVIEW not in screens


def test_narrative_on_still_routes_generate_into_quick_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period(), narrative=True)
    log = ActionLog(_review())

    screens = _run(
        monkeypatch,
        draft,
        log,
        [*_open_review_keys(), char("b"), char("q"), char("q"), char("q")],
    )

    assert len(log.synthesis_scans) == 1
    assert Screen.OUTCOME_REVIEW in screens


def _over_budget() -> SynthesisBudgetExceededError:
    # Holding three of five back means the payload ran past the budget:
    # over_limit reads the bytes, so the two have to agree.
    return SynthesisBudgetExceededError(
        SynthesisBudgetEstimate(
            selected_count=5,
            fit_count=2,
            bytes_used=52000,
            max_bytes=40000,
        )
    )


_OVER_BUDGET_GUIDANCE = (
    "5 selected; synthesis handles about 2. "
    "Narrow the period, deselect what does not belong in the update, or "
    "press G to group the newest that fit and leave the rest as ungrouped "
    "candidates. (52000 / 40000 bytes)"
)


def test_over_budget_selection_blocks_synthesis_with_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog(_review())
    forced: list[bool] = []

    def synthesize(
        _draft: ReportDraft, selected_scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        forced.append(force)
        raise _over_budget()

    actions = replace(_actions(draft, log), synthesize=synthesize)
    frames: list[tuple[Screen, str | None]] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: frames.append((state.screen, state.review_message)),
    )

    run_interactive(
        actions=actions,
        input_source=ScriptedInput([*_open_review_keys(), char("q"), char("q"), char("q")]),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    # One consultation of the synthesis layer, which is also the one that
    # measured: nothing extracts the selection a second time.
    assert forced == [False]
    assert (Screen.SESSION_REVIEW, _OVER_BUDGET_GUIDANCE) in frames
    assert Screen.OUTCOME_REVIEW not in [screen for screen, _ in frames]


def test_capital_g_groups_an_over_budget_selection_anyway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard reports the cost; refusing the work outright is not its call."""

    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog(_review())
    forced: list[bool] = []

    def synthesize(
        _draft: ReportDraft, selected_scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        forced.append(force)
        if not force:
            raise _over_budget()
        log.synthesis_scans.append(selected_scan)
        return log.review

    actions = replace(_actions(draft, log), synthesize=synthesize)
    screens: list[Screen] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: screens.append(state.screen),
    )

    run_interactive(
        actions=actions,
        input_source=ScriptedInput(
            [*_open_review_keys(), char("G"), char("q"), char("q"), char("q"), char("q")]
        ),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    # The refusal, then the run that produced the review: forcing pays for no
    # measurement it then ignores.
    assert forced == [False, True]
    assert len(log.synthesis_scans) == 1
    assert Screen.OUTCOME_REVIEW in screens


def test_an_over_budget_refusal_clears_the_error_it_returns_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every other exit from generation clears it; a stale error would outlive it."""

    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog(_review())
    attempts = 0

    def synthesize(
        _draft: ReportDraft, selected_scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OutcomeSynthesisError("temporary synthesis failure")
        raise _over_budget()

    actions = replace(_actions(draft, log), synthesize=synthesize)
    frames: list[tuple[Screen, bool]] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: frames.append((state.screen, state.error is None)),
    )

    run_interactive(
        actions=actions,
        input_source=ScriptedInput(
            [*_open_review_keys(), KeyPress(key=Key.ENTER), char("q"), char("q"), char("q")]
        ),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    assert attempts == 2
    assert (Screen.RECOVERABLE_ERROR, False) in frames
    assert (Screen.SESSION_REVIEW, True) in frames


def test_returning_to_a_cached_review_does_not_synthesize_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached review already cleared the guard; synthesizing re-extracts everything."""

    draft = ReportDraft(harness="opencode", period=_period())
    log = ActionLog(_review())
    screens: list[Screen] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: screens.append(state.screen),
    )

    run_interactive(
        actions=_actions(draft, log),
        input_source=ScriptedInput(
            [*_open_review_keys(), char("b"), char("g"), char("q"), char("q"), char("q"), char("q")]
        ),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    assert len(log.synthesis_scans) == 1
    assert Screen.OUTCOME_REVIEW in screens


@pytest.mark.parametrize("action", ["g", "p"])
def test_excluding_every_outcome_blocks_generation_with_a_message(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(_outcome("a", 0))
    review.outcomes[0].included = False
    log = ActionLog(review)
    frames: list[tuple[Screen, str | None]] = []
    monkeypatch.setattr(
        controller,
        "_render_screen",
        lambda state, console: frames.append((state.screen, state.outcome_message)),
    )

    run_interactive(
        actions=_actions(draft, log),
        input_source=ScriptedInput(
            [*_open_review_keys(), char(action), char("q"), char("q"), char("q"), char("q")]
        ),
        console=Console(file=StringIO(), color_system=None, force_terminal=False),
    )

    assert log.reviewed_calls == []
    messages = [message for screen, message in frames if screen is Screen.OUTCOME_REVIEW]
    assert messages and any(
        message is not None and "outcome" in message.lower() for message in messages
    )
    assert Screen.REPORT_PREVIEW not in [item for item, _ in frames]
    assert Screen.REPORT_RESULT not in [item for item, _ in frames]


def test_one_included_outcome_is_enough_to_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(_outcome("a", 0), _outcome("b", 1))
    review.outcomes[0].included = False
    log = ActionLog(review)

    screens = _run(
        monkeypatch,
        draft,
        log,
        [*_open_review_keys(), char("g"), char("q"), char("q")],
    )

    assert len(log.reviewed_calls) == 1
    assert Screen.REPORT_RESULT in screens


def _more_outcome(identifier: str, rank: int) -> Outcome:
    candidate = _outcome(identifier, rank)
    candidate.included = False
    candidate.bucket = OutcomeBucket.MORE
    return candidate


def _outcome_state(review: OutcomeReviewDraft) -> controller._State:
    return controller._State(
        screen=Screen.OUTCOME_REVIEW,
        outcome_review=review,
        expanded_evidence={MORE_CANDIDATES_SECTION},
    )


def test_toggling_a_more_candidate_keeps_the_cursor_on_it() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(
        _outcome("a", 0),
        _outcome("b", 1),
        _outcome("c", 2),
        _outcome("d", 3),
        _outcome("e", 4),
        _more_outcome("candidate", 5),
    )
    log = ActionLog(review)
    actions = _actions(draft, log)
    state = _outcome_state(review)
    rows = controller._outcome_review_rows(state)
    candidate_index = next(
        index
        for index, row in enumerate(rows)
        if row.kind == "outcome" and row.outcome_id == "candidate"
    )

    for _ in range(candidate_index):
        controller._outcome_review_key(state, KeyPress(key=Key.DOWN), actions)
    assert (
        controller._outcome_review_rows(state)[state.outcome_cursor].outcome_id
        == "candidate"
    )

    controller._outcome_review_key(state, KeyPress(key=Key.SPACE), actions)

    focused = controller._outcome_review_rows(state)[state.outcome_cursor]
    assert focused.kind == "outcome"
    assert focused.outcome_id == "candidate"
    assert next(
        outcome for outcome in review.outcomes if outcome.id == "candidate"
    ).included is True


def test_toggling_a_primary_outcome_keeps_the_cursor_stable() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    review = _review(_outcome("a", 0), _outcome("b", 1))
    log = ActionLog(review)
    actions = _actions(draft, log)
    state = _outcome_state(review)

    controller._outcome_review_key(state, KeyPress(key=Key.DOWN), actions)
    controller._outcome_review_key(state, KeyPress(key=Key.DOWN), actions)
    assert (
        controller._outcome_review_rows(state)[state.outcome_cursor].outcome_id == "b"
    )

    controller._outcome_review_key(state, KeyPress(key=Key.SPACE), actions)

    focused = controller._outcome_review_rows(state)[state.outcome_cursor]
    assert focused.kind == "outcome"
    assert focused.outcome_id == "b"
    assert review.outcomes[1].included is False
