from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from iiwi import cli
from iiwi.interactive.controller import InteractiveActions, InteractiveReportResult
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

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


def _scan() -> ScanResult:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="ses-1",
            title="Session 1",
            working_directory="/tmp/repo-a",
            activities=[
                SessionActivity(
                    activity_id=f"act-{i}",
                    activity_type=ActivityType.USER_MESSAGE,
                )
                for i in range(5)
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
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
        sessions_by_repository={"repo-a": [resolved]},
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