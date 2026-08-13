from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
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


def _synthesized_outcomes() -> list[Outcome]:
    """Quick Review declines to generate with nothing included, so stub one outcome."""
    return [
        Outcome(
            id="outcome-1",
            title="Outcome 1",
            status=OutcomeStatus.IN_PROGRESS,
            impact="Impact",
            rank=0,
            evidence_refs=[EvidenceRef(session_id="ses-0", repository_id="repo-a")],
        )
    ]


class ScriptedInput:
    def __init__(self, keys: list[KeyPress]) -> None:
        self._keys: Iterator[KeyPress] = iter(keys)

    def __enter__(self) -> ScriptedInput:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read_key(self) -> KeyPress:
        return next(self._keys)


def char(value: str) -> KeyPress:
    return KeyPress(char=value)


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _scan() -> ScanResult:
    session = AgentSession(
        harness="opencode",
        session_id="ses-1",
        title="Improve interactive mode",
        working_directory="/tmp/iiwi",
        activities=[
            SessionActivity(
                activity_id=f"act-{index}",
                activity_type=ActivityType.USER_MESSAGE,
                content="work",
            )
            for index in range(3)
        ],
    )
    resolved = ResolvedSession(
        session=session,
        repository=RepositoryIdentity(
            repository_id="repo-iiwi",
            display_name="iiwi",
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory="/tmp/iiwi",
            resolution_method="test",
        ),
    )
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
        sessions_by_repository={"repo-iiwi": [resolved]},
    )


def _actions(counters: dict[str, int]) -> InteractiveActions:
    draft = ReportDraft(harness="opencode", period=_period())

    def count(name: str) -> None:
        counters[name] = counters.get(name, 0) + 1

    def new_draft() -> ReportDraft:
        count("draft")
        return draft

    def scan(draft_value: ReportDraft) -> ScanResult:
        count("scan")
        return _scan()

    def generate(
        draft_value: ReportDraft,
        scan_value: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        count("generate")
        return InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report",
            repository_count=len(scan_value.sessions_by_repository),
            session_count=scan_value.loaded_session_count,
        )

    return InteractiveActions(
        new_draft=new_draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last 7 days", _period()),
        scan=scan,
        generate=generate,
        synthesize=lambda draft, scan: OutcomeReviewDraft(
            outcomes=_synthesized_outcomes(), report_type=draft.report_type
        ),
        generate_reviewed=lambda draft, scan, review, force: generate(
            draft, scan, force
        ),
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [f"{harness}: ok"],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def test_main_browse_entry_can_generate_from_the_same_activity_tree() -> None:
    counters: dict[str, int] = {}
    console = Console(
        file=StringIO(),
        color_system=None,
        force_terminal=False,
        width=100,
        height=25,
    )
    input_source = ScriptedInput(
        [
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("g"),
            char("g"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(counters),
        input_source=input_source,
        console=console,
    )

    assert counters.get("scan", 0) == 1
    assert counters.get("generate", 0) == 1
