from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console
from typer.testing import CliRunner

from iiwi import cli
from iiwi.errors import ReportOutputError
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft
from iiwi.models.outcome import (
    Outcome,
    OutcomeBucket,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.report_options import ReportType
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.renderers.markdown import MarkdownRenderer
from iiwi.services import outcomes as outcome_service
from iiwi.services.outcomes import OutcomeSynthesisService
from iiwi.services.report import ReportService
from iiwi.services.scan import ScanResult, ScanService
from iiwi.summarizers.opencode_run import OpenCodeRunner
from iiwi.summarizers.rule_based import RuleBasedSummarizer

runner = CliRunner()
TZ = ZoneInfo("Asia/Taipei")


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


def _scan(*session_ids: str) -> ScanResult:
    session_ids = session_ids or ("ses-1",)
    repository = RepositoryIdentity(
        repository_id="repo-a",
        display_name="repo-a",
        identity_type=RepositoryIdentityType.PATH_FALLBACK,
        working_directory="/tmp/repo-a",
        resolution_method="test",
    )
    resolved = [
        ResolvedSession(
            session=AgentSession(
                harness="opencode",
                session_id=session_id,
                title=f"Session {session_id}",
                working_directory="/tmp/repo-a",
                activities=[
                    SessionActivity(
                        activity_id=f"{session_id}-act-{i}",
                        activity_type=ActivityType.USER_MESSAGE,
                    )
                    for i in range(5)
                ],
            ),
            repository=repository,
        )
        for session_id in session_ids
    ]
    return ScanResult(
        period=_period(),
        candidate_session_count=len(resolved),
        loaded_session_count=len(resolved),
        failed_session_count=0,
        resolved_sessions=resolved,
        sessions_by_repository={"repo-a": resolved},
    )


class StaticSynthesisRunner:
    def __init__(self, payload: dict[str, object]) -> None:
        self.output = json.dumps(payload)

    def run(self, *, transcript: str, prompt: str, title: str) -> str:
        assert transcript
        assert prompt
        assert title == "Iiwi outcome synthesis"
        return self.output


def _synthesis_payload(
    items: list[tuple[str, str, str]],
) -> dict[str, object]:
    return {
        "outcomes": [
            {
                "title": title,
                "status": "completed",
                "impact": impact,
                "source_session_ids": [session_id],
                "confidence": "high",
                "linkage_signals": [],
            }
            for session_id, title, impact in items
        ]
    }


def _quick_review_actions(
    *,
    draft: ReportDraft,
    scan: ScanResult,
    payload: dict[str, object],
    output_path: Path,
    review_calls: list[tuple[OutcomeReviewDraft, bool]],
    edited: Outcome | None = None,
    added: Outcome | None = None,
    gaps: dict[str, str] | None = None,
    preview_failures: int = 0,
) -> InteractiveActions:
    runner = StaticSynthesisRunner(payload)
    synthesis = OutcomeSynthesisService(cast(OpenCodeRunner, runner))
    attempts = 0

    def synthesize(
        current: ReportDraft,
        selected_scan: ScanResult,
    ) -> OutcomeReviewDraft:
        result = synthesis.synthesize(selected_scan)
        return OutcomeReviewDraft(
            outcomes=result.outcomes,
            report_type=current.report_type,
        )

    def generate_reviewed(
        current: ReportDraft,
        selected_scan: ScanResult,
        review: OutcomeReviewDraft,
        force: bool,
    ) -> InteractiveReportResult:
        nonlocal attempts
        review_calls.append((review, current.dry_run))
        if current.dry_run:
            attempts += 1
            if attempts <= preview_failures:
                raise ReportOutputError("deterministic preview failure")
        service = ReportService(
            scan_service=cast(ScanService, object()),
            summarizer=RuleBasedSummarizer(),
            renderer=MarkdownRenderer(),
            period=_period(),
            output_path=output_path,
            now_factory=lambda: datetime(2026, 8, 10, 12, tzinfo=TZ),
        )
        result = service.generate_reviewed(
            review,
            scan=selected_scan,
            force=force,
            dry_run=current.dry_run,
        )
        return InteractiveReportResult(
            output_path=None if current.dry_run else result.output_path,
            content=result.content,
            repository_count=len(selected_scan.sessions_by_repository),
            session_count=selected_scan.loaded_session_count,
        )

    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("This week", _period()),
        scan=lambda current: scan,
        generate=lambda current, selected_scan, force: pytest.fail(
            "Quick Review must not use session-based generation"
        ),
        synthesize=synthesize,
        generate_reviewed=generate_reviewed,
        edit_outcome=lambda outcome: edited or outcome,
        add_outcome=lambda: added,
        edit_gap=lambda label, current: (gaps or {}).get(label),
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [],
        edit_settings=lambda: None,
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def test_bare_real_tty_dispatches_key_driven_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[object] = []
    fake_input = object()

    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(cli, "_supports_key_navigation", lambda: True)
    monkeypatch.setattr(cli, "TerminalInput", lambda: fake_input)
    monkeypatch.setattr(
        cli,
        "run_interactive",
        lambda **kwargs: called.append(kwargs),
    )

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 0, result.stdout
    assert len(called) == 1
    assert called[0]["input_source"] is fake_input
    assert called[0]["actions"] is not None
    assert called[0]["console"] is not None


def test_bare_command_runs_generate_select_result_main_quit_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    generated: list[list[str]] = []

    def generate(
        _draft: ReportDraft,
        selected_scan: ScanResult,
        _force: bool,
    ) -> InteractiveReportResult:
        generated.append(
            [item.session.session_id for item in selected_scan.resolved_sessions]
        )
        return InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report",
            repository_count=1,
            session_count=selected_scan.loaded_session_count,
        )

    actions = InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: current,
        scan=lambda value: _scan(),
        generate=generate,
        synthesize=lambda current, selected_scan: OutcomeReviewDraft(
            outcomes=[
                Outcome(
                    id="reviewed",
                    title="Reviewed outcome",
                    status=OutcomeStatus.COMPLETED,
                    rank=0,
                    evidence_refs=[],
                    origin=OutcomeOrigin.USER_ADDED,
                )
            ]
        ),
        generate_reviewed=lambda current, selected_scan, review, force: generate(
            current, selected_scan, force
        ),
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [],
        edit_settings=lambda: None,
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )
    scripted = ScriptedInput(
        [
            char("2"),
            char("r"),
            KeyPress(key=Key.SPACE),
            KeyPress(key=Key.SPACE),
            char("g"),
            char("g"),
            char("q"),
            char("q"),
        ]
    )

    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(cli, "_supports_key_navigation", lambda: True)
    monkeypatch.setattr(cli, "TerminalInput", lambda: scripted)
    monkeypatch.setattr(cli, "build_interactive_actions", lambda: actions)

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 0, result.stdout
    assert generated == [["ses-1"]]


def test_named_subcommand_never_dispatches_key_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_interactive",
        lambda **kwargs: pytest.fail("interactive controller must not run"),
        raising=False,
    )

    result = runner.invoke(cli.app, ["config", "path"])

    assert result.exit_code == 0, result.stdout


def test_help_never_dispatches_key_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "run_interactive",
        lambda **kwargs: pytest.fail("interactive controller must not run"),
        raising=False,
    )

    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0, result.stdout
    assert "Usage" in result.stdout


def test_non_tty_bare_invocation_keeps_exit_code_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 3
    assert "needs a terminal" in result.stdout
    assert "subcommand" in result.stdout


def test_quick_review_writes_the_exact_reviewed_draft(tmp_path: Path) -> None:
    output_path = tmp_path / "reviewed.md"
    draft = ReportDraft(
        harness="opencode",
        period=_period(),
        report_type=ReportType.ENGINEERING,
    )
    scan = _scan("ses-1", "ses-2", "ses-3")
    review_calls: list[tuple[OutcomeReviewDraft, bool]] = []
    edited = Outcome(
        id="callback-id",
        title="Edited rollout",
        status=OutcomeStatus.COMPLETED,
        impact="Verified customer rollout",
        rank=99,
        origin=OutcomeOrigin.USER_ADDED,
    )
    added = Outcome(
        id="callback-manual",
        title="Manual follow-up",
        status=OutcomeStatus.COMPLETED,
        impact="Confirmed with support",
        rank=99,
        origin=OutcomeOrigin.USER_ADDED,
    )
    actions = _quick_review_actions(
        draft=draft,
        scan=scan,
        payload=_synthesis_payload(
            [
                ("ses-1", "Excluded candidate", "Unsupported impact to omit"),
                ("ses-2", "Original rollout", "Original impact"),
                ("ses-3", "Stable delivery", ""),
            ]
        ),
        output_path=output_path,
        review_calls=review_calls,
        edited=edited,
        added=added,
        gaps={
            "Blockers": "Waiting for security approval",
            "Next week": "Ship the verified rollout",
        },
    )
    keys = [
        char("2"),
        char("r"),
        char("g"),
        char("j"),
        KeyPress(key=Key.SPACE),
        char("j"),
        char("e"),
        char("K"),
        char("a"),
        char("j"),
        KeyPress(key=Key.ENTER),
        char("j"),
        KeyPress(key=Key.ENTER),
        char("p"),
        char("b"),
        char("g"),
        char("q"),
        char("q"),
    ]

    run_interactive(
        actions=actions,
        input_source=ScriptedInput(keys),
        console=Console(
            file=StringIO(),
            color_system=None,
            force_terminal=False,
            width=100,
            height=30,
        ),
    )

    content = output_path.read_text(encoding="utf-8")
    assert content.index("Edited rollout") < content.index("Stable delivery")
    assert content.index("Stable delivery") < content.index("Manual follow-up")
    assert "Verified customer rollout" in content
    assert "Manual follow-up _(User added)_" in content
    assert "Waiting for security approval" in content
    assert "Ship the verified rollout" in content
    assert "Session: `ses-2`" in content
    assert "Session: `ses-3`" in content
    assert "Excluded candidate" not in content
    assert "Unsupported impact to omit" not in content
    assert "- Stable delivery\n  - Impact:" not in content
    assert [dry_run for _, dry_run in review_calls] == [True, False]
    assert review_calls[0][0] is review_calls[1][0]


def test_twenty_line_quick_review_expands_more_evidence_and_recovers_preview(
    tmp_path: Path,
) -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    scan = _scan(*(f"ses-{index}" for index in range(1, 7)))
    review_calls: list[tuple[OutcomeReviewDraft, bool]] = []
    stream = StringIO()
    actions = _quick_review_actions(
        draft=draft,
        scan=scan,
        payload=_synthesis_payload(
            [
                (f"ses-{index}", f"Outcome {index}", f"Impact {index}")
                for index in range(1, 7)
            ]
        ),
        output_path=tmp_path / "preview.md",
        review_calls=review_calls,
        preview_failures=1,
    )
    keys = [
        char("2"),
        char("r"),
        char("g"),
        char("j"),
        KeyPress(key=Key.SPACE),
        *(char("j") for _ in range(5)),
        KeyPress(key=Key.ENTER),
        char("j"),
        KeyPress(key=Key.SPACE),
        char("v"),
        char("p"),
        KeyPress(key=Key.DOWN),
        KeyPress(key=Key.ENTER),
        char("p"),
        char("b"),
        char("b"),
        char("q"),
        char("q"),
    ]

    run_interactive(
        actions=actions,
        input_source=ScriptedInput(keys),
        console=Console(
            file=stream,
            color_system=None,
            force_terminal=False,
            width=80,
            height=20,
        ),
    )

    output = stream.getvalue()
    assert "More candidates" in output
    assert "Session" in output and "ses-6" in output
    assert "deterministic preview failure" in output
    assert "Back to Quick Review" in output
    assert "Report Preview" in output
    assert [dry_run for _, dry_run in review_calls] == [True, True]
    assert review_calls[0][0] is review_calls[1][0]
    reviewed = review_calls[0][0].ordered()
    assert sum(item.included for item in reviewed) == 5
    assert reviewed[0].included is False
    assert reviewed[5].included is True
    assert not (tmp_path / "preview.md").exists()


def test_partial_synthesis_retains_failures_without_preselecting_over_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = _scan(*(f"ses-{index}" for index in range(1, 8)))
    original_extract = outcome_service.extract_evidence

    def fail_last(resolved: ResolvedSession):
        if resolved.session.session_id == "ses-7":
            raise RuntimeError("deterministic extraction failure")
        return original_extract(resolved)

    monkeypatch.setattr(outcome_service, "extract_evidence", fail_last)
    synthesis = OutcomeSynthesisService(
        cast(
            OpenCodeRunner,
            StaticSynthesisRunner(
                _synthesis_payload(
                    [
                        (f"ses-{index}", f"Outcome {index}", "")
                        for index in range(1, 7)
                    ]
                )
            ),
        )
    )

    result = synthesis.synthesize(scan)

    assert len(result.outcomes) == 7
    assert sum(outcome.included for outcome in result.outcomes) == 5
    assert result.outcomes[5].bucket is OutcomeBucket.MORE
    assert result.outcomes[5].included is False
    assert result.outcomes[6].bucket is OutcomeBucket.UNGROUPED
    assert result.outcomes[6].included is False
