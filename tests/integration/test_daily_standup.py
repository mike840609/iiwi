"""End-to-end contract coverage for the Daily Standup workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi import cli
from iiwi.daily_state import DAILY_STATE_DIR_VARIABLE
from iiwi.errors import DailySourceUnavailableError, HarnessSourceError
from iiwi.harnesses.base import HarnessSessionSource
from iiwi.history import HISTORY_FILE_VARIABLE, HistoryKind, read_history
from iiwi.interactive import cli_actions, render
from iiwi.models.daily import DailySection, DailyStatementSource
from iiwi.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
)
from iiwi.models.time_range import DateRange
from iiwi.process import CommandRunner
from iiwi.repositories.resolver import RepositoryResolver
from iiwi.services.daily_scan import DailyScanCoordinator, DailyWindow
from iiwi.services.daily_workflow import DailyWorkflowService
from iiwi.services.outcomes import OutcomeSynthesisService
from iiwi.services.scan import ScanService

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 13, 10, 30, tzinfo=TZ)
YESTERDAY = datetime(2026, 8, 12, 9, 0, tzinfo=TZ)
TODAY = datetime(2026, 8, 13, 9, 0, tzinfo=TZ)

CROSS_REPOSITORY_TITLE = "Ship shared Daily flow TASK-42"
RESOLVED_TITLE = "Resolve flaky verification TASK-99"
BLOCKED_TITLE = "Fix blocker task"
NEW_WORK_TITLE = "Implement new status panel"

IIWI_REPOSITORY = "git:github.com/example/iiwi"
WEB_REPOSITORY = "git:github.com/example/web"
API_REPOSITORY = "git:github.com/example/api"


def _activity(
    activity_id: str,
    activity_type: ActivityType,
    timestamp: datetime,
    content: str,
    *,
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
        metadata=metadata,
    )


def _session(
    harness: str,
    session_id: str,
    title: str,
    working_directory: Path,
    activities: list[SessionActivity],
    *,
    parent_session_id: str | None = None,
) -> AgentSession:
    timestamps = [
        activity.timestamp
        for activity in activities
        if activity.timestamp is not None
    ]
    assert timestamps
    return AgentSession(
        harness=harness,
        session_id=session_id,
        parent_session_id=parent_session_id,
        title=title,
        created_at=min(timestamps),
        updated_at=max(timestamps),
        working_directory=str(working_directory),
        activities=activities,
    )


class MutableHarnessSource(HarnessSessionSource):
    """An injected transcript store; the real scanner owns all filtering."""

    def __init__(self, harness: str, sessions: list[AgentSession]) -> None:
        self.harness = harness
        self.sessions = sessions
        self.unavailable = False
        self.periods: list[DateRange] = []

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        self.periods.append(period)
        if self.unavailable:
            raise HarnessSourceError(f"{self.harness} fixture unavailable")
        return [
            SessionDescriptor(
                harness=session.harness,
                session_id=session.session_id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                working_directory_hint=session.working_directory,
                parent_session_id=session.parent_session_id,
            )
            for session in self.sessions
        ]

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        return next(
            session
            for session in self.sessions
            if session.session_id == descriptor.session_id
        )


class GroupingRunner:
    """A deterministic grouping boundary around the real synthesis service."""

    def __init__(self) -> None:
        self.fail = False
        self.calls: list[dict[str, object]] = []

    def run(self, *, transcript: str, prompt: str, title: str) -> str:
        if self.fail:
            raise OSError("grouping fixture unavailable")
        payload = json.loads(transcript)
        self.calls.append(payload)
        sessions = payload["sessions"]
        assert isinstance(sessions, list)
        cross_repository = [
            session
            for session in sessions
            if session.get("title") == CROSS_REPOSITORY_TITLE
        ]
        outcomes: list[dict[str, object]] = []
        if cross_repository:
            outcomes.append(
                {
                    "title": CROSS_REPOSITORY_TITLE,
                    "status": "in_progress",
                    "source_ids": [session["source_id"] for session in cross_repository],
                    "confidence": "high",
                    "linkage_signals": [
                        {"kind": "branch_or_issue", "value": "TASK-42"},
                        {"kind": "direct_reference", "value": "TASK-42"},
                    ],
                }
            )
        for session in sessions:
            session_title = session.get("title")
            if session_title == CROSS_REPOSITORY_TITLE:
                continue
            outcomes.append(
                {
                    "title": session_title,
                    "status": "in_progress",
                    "source_ids": [session["source_id"]],
                    "confidence": "high",
                    "linkage_signals": [],
                }
            )
        return json.dumps({"outcomes": outcomes})


@dataclass
class DailyFixture:
    sources: dict[str, MutableHarnessSource]
    runner: GroupingRunner
    resolver: RepositoryResolver
    repositories: dict[str, Path]
    now: datetime = NOW

    def workflow(self) -> DailyWorkflowService:
        def coordinator(window: DailyWindow) -> DailyScanCoordinator:
            scanners = {
                harness: ScanService(
                    source=source,
                    period=window.period,
                    resolver=self.resolver,
                )
                for harness, source in self.sources.items()
            }
            return DailyScanCoordinator(window=window, scanners=scanners)

        return DailyWorkflowService(
            scan_coordinator_factory=coordinator,
            outcome_service=OutcomeSynthesisService(self.runner),  # type: ignore[arg-type]
            now_factory=lambda: self.now,
        )


def _full_sources(
    repositories: dict[str, Path],
) -> dict[str, MutableHarnessSource]:
    opencode = MutableHarnessSource(
        "opencode",
        [
            _session(
                "opencode",
                "same-id",
                CROSS_REPOSITORY_TITLE,
                repositories[IIWI_REPOSITORY],
                [
                    _activity(
                        "opencode-goal",
                        ActivityType.USER_MESSAGE,
                        YESTERDAY,
                        CROSS_REPOSITORY_TITLE,
                    ),
                    _activity(
                        "opencode-file",
                        ActivityType.FILE_CHANGE,
                        YESTERDAY.replace(minute=15),
                        "src/iiwi/daily.py",
                    ),
                ],
            ),
            _session(
                "opencode",
                "resolved-failure",
                RESOLVED_TITLE,
                repositories[API_REPOSITORY],
                [
                    _activity(
                        "resolved-goal",
                        ActivityType.USER_MESSAGE,
                        YESTERDAY.replace(hour=10),
                        RESOLVED_TITLE,
                    ),
                    _activity(
                        "resolved-failure",
                        ActivityType.COMMAND,
                        YESTERDAY.replace(hour=10, minute=15),
                        "uv run pytest tests/flaky.py",
                        exit_code=1,
                    ),
                    _activity(
                        "resolved-success",
                        ActivityType.COMMAND,
                        TODAY.replace(hour=8),
                        "uv run pytest tests/flaky.py",
                        exit_code=0,
                    ),
                ],
            ),
        ],
    )
    claude = MutableHarnessSource(
        "claude-code",
        [
            _session(
                "claude-code",
                "same-id",
                CROSS_REPOSITORY_TITLE,
                repositories[WEB_REPOSITORY],
                [
                    _activity(
                        "claude-goal",
                        ActivityType.USER_MESSAGE,
                        TODAY,
                        CROSS_REPOSITORY_TITLE,
                    ),
                    _activity(
                        "claude-file",
                        ActivityType.FILE_CHANGE,
                        TODAY.replace(minute=15),
                        "src/web/daily.ts",
                    ),
                ],
            )
        ],
    )
    codex = MutableHarnessSource(
        "codex",
        [
            _session(
                "codex",
                "blocked-command",
                BLOCKED_TITLE,
                repositories[IIWI_REPOSITORY],
                [
                    _activity(
                        "blocked-goal",
                        ActivityType.USER_MESSAGE,
                        TODAY.replace(minute=5),
                        BLOCKED_TITLE,
                    ),
                    _activity(
                        "blocked-file",
                        ActivityType.FILE_CHANGE,
                        TODAY.replace(minute=20),
                        "src/iiwi/blocker.py",
                    ),
                    _activity(
                        "blocked-failure",
                        ActivityType.COMMAND,
                        TODAY.replace(minute=30),
                        "uv run pytest tests/blocker.py",
                        exit_code=1,
                    ),
                ],
                parent_session_id="codex-parent",
            )
        ],
    )
    return {"opencode": opencode, "claude-code": claude, "codex": codex}


def _create_git_repository(
    root: Path,
    name: str,
    *,
    runner: CommandRunner,
) -> Path:
    repository = root / name
    repository.parent.mkdir(parents=True, exist_ok=True)
    initialized = runner.run(["git", "init", "-q", str(repository)])
    assert initialized.returncode == 0, initialized.stderr
    remote = runner.run(
        [
            "git",
            "-C",
            str(repository),
            "remote",
            "add",
            "origin",
            f"https://github.com/example/{name}.git",
        ]
    )
    assert remote.returncode == 0, remote.stderr
    return repository


@pytest.fixture
def daily_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> DailyFixture:
    monkeypatch.setenv(DAILY_STATE_DIR_VARIABLE, str(tmp_path / "daily-state"))
    monkeypatch.setenv(HISTORY_FILE_VARIABLE, str(tmp_path / "history.jsonl"))
    monkeypatch.setenv(
        "IIWI_REPORT__OUTPUT_DIRECTORY",
        str(tmp_path / "reports"),
    )
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: NOW)
    command_runner = CommandRunner(timeout_seconds=5)
    repositories = {
        repository_id: _create_git_repository(
            tmp_path / "repositories",
            repository_id.rsplit("/", 1)[-1],
            runner=command_runner,
        )
        for repository_id in (IIWI_REPOSITORY, WEB_REPOSITORY, API_REPOSITORY)
    }
    return DailyFixture(
        sources=_full_sources(repositories),
        runner=GroupingRunner(),
        resolver=RepositoryResolver(runner=command_runner),
        repositories=repositories,
    )


def _item_with_statement(draft, statement: str):
    return next(
        work_item
        for work_item in draft.work_items
        if any(
            section is not None and section.statement == statement
            for section in (
                work_item.yesterday,
                work_item.today,
                work_item.blocker,
            )
        )
    )


def test_first_run_preserves_provenance_and_generates_the_reviewed_artifact(
    daily_fixture: DailyFixture,
) -> None:
    draft = daily_fixture.workflow().refresh()

    grouped = _item_with_statement(draft, CROSS_REPOSITORY_TITLE)
    assert grouped.yesterday is not None
    assert grouped.today is not None
    assert set(grouped.repository_ids) == {IIWI_REPOSITORY, WEB_REPOSITORY}
    assert grouped.yesterday.source is DailyStatementSource.ACTIVITY_YESTERDAY
    assert grouped.today.source is DailyStatementSource.ACTIVITY_TODAY
    assert grouped.yesterday.evidence_refs[0].activity_ids == [
        "opencode-file",
        "opencode-goal",
    ]
    assert grouped.today.evidence_refs[0].activity_ids == [
        "claude-file",
        "claude-goal",
    ]
    assert {
        (reference.harness, reference.session_id)
        for section in (grouped.yesterday, grouped.today)
        for reference in section.evidence_refs
    } == {("opencode", "same-id"), ("claude-code", "same-id")}

    blocked = _item_with_statement(draft, BLOCKED_TITLE)
    assert blocked.blocker is not None
    assert blocked.blocker.statement == "uv run pytest tests/blocker.py"
    assert blocked.blocker.included is False
    assert blocked.blocker.source is DailyStatementSource.DETECTED_BLOCKER
    resolved = _item_with_statement(draft, RESOLVED_TITLE)
    assert resolved.blocker is None
    assert resolved.today is not None
    assert {
        activity_id
        for reference in resolved.today.evidence_refs
        for activity_id in reference.activity_ids
    } == {"resolved-success"}

    console_stream = StringIO()
    render.render_daily_review(
        Console(
            file=console_stream,
            color_system=None,
            force_terminal=False,
            width=180,
            height=80,
        ),
        draft,
        cursor=0,
        expanded=set(),
    )
    review_text = console_stream.getvalue()
    assert "Activity today" in review_text
    assert "Detected blocker" in review_text
    assert "New activity" in review_text

    preview = cli_actions._preview_daily(draft)
    generated = cli_actions._generate_daily(draft)

    assert generated.output_path is not None
    assert generated.output_path.name == "daily-standup-2026-08-13.md"
    assert preview.content.encode() == generated.output_path.read_bytes()
    assert preview.content == generated.content
    assert (
        preview.content.index("## Yesterday")
        < preview.content.index("## Today")
        < preview.content.index("## Blockers")
    )
    expected_repositories = f"[{API_REPOSITORY}]"
    assert expected_repositories in preview.content
    assert (
        f"[{IIWI_REPOSITORY}, {WEB_REPOSITORY}] {CROSS_REPOSITORY_TITLE}"
        in preview.content
    )
    assert "Activity today" not in preview.content
    assert "Detected blocker" not in preview.content
    assert "New activity" not in preview.content

    entry = read_history()[-1]
    assert entry.kind is HistoryKind.DAILY_STANDUP
    assert entry.harnesses == ("opencode", "claude-code", "codex")
    assert entry.unavailable_harnesses == ()
    assert entry.output_path.is_absolute()


def test_same_day_refresh_preserves_review_and_atomically_replaces_output(
    daily_fixture: DailyFixture,
) -> None:
    draft = daily_fixture.workflow().refresh()
    grouped = _item_with_statement(draft, CROSS_REPOSITORY_TITLE)
    blocked = _item_with_statement(draft, BLOCKED_TITLE)
    first_generated = cli_actions._generate_daily(draft)
    assert first_generated.output_path is not None
    first_bytes = first_generated.output_path.read_bytes()

    draft.edit(DailySection.TODAY, grouped.id, "Reviewed shared Daily wording")
    draft.toggle_included(DailySection.YESTERDAY, grouped.id)
    manual = draft.add_user_item(DailySection.BLOCKERS, "Waiting for release approval")
    draft.move(DailySection.TODAY, blocked.id, -1)
    reviewed_today_order = [
        item.id for item, _ in draft.ordered_items(DailySection.TODAY)
    ]
    assert cli_actions._persist_daily(draft) is None

    claude_same_id = daily_fixture.sources["claude-code"].sessions[0]
    claude_same_id.activities.append(
        _activity(
            "claude-new-file",
            ActivityType.FILE_CHANGE,
            TODAY.replace(hour=10),
            "src/web/status.ts",
        )
    )
    claude_same_id.updated_at = TODAY.replace(hour=10)
    daily_fixture.sources["codex"].sessions.append(
        _session(
            "codex",
            "new-work",
            NEW_WORK_TITLE,
            daily_fixture.repositories[IIWI_REPOSITORY],
            [
                _activity(
                    "new-goal",
                    ActivityType.USER_MESSAGE,
                    TODAY.replace(hour=10, minute=5),
                    NEW_WORK_TITLE,
                ),
                _activity(
                    "new-file",
                    ActivityType.FILE_CHANGE,
                    TODAY.replace(hour=10, minute=10),
                    "src/iiwi/status.py",
                ),
            ],
        )
    )

    refreshed = daily_fixture.workflow().refresh()

    refreshed_grouped = next(item for item in refreshed.work_items if item.id == grouped.id)
    assert refreshed_grouped.today is not None
    assert refreshed_grouped.today.statement == "Reviewed shared Daily wording"
    assert refreshed_grouped.today.user_edited is True
    assert refreshed_grouped.yesterday is not None
    assert refreshed_grouped.yesterday.included is False
    assert "claude-new-file" in {
        activity_id
        for reference in refreshed_grouped.today.evidence_refs
        for activity_id in reference.activity_ids
    }
    assert refreshed_grouped.today.new_activity is True
    refreshed_manual = next(item for item in refreshed.work_items if item.id == manual.id)
    assert refreshed_manual.blocker is not None
    assert refreshed_manual.blocker.statement == "Waiting for release approval"
    assert [
        item.id for item, _ in refreshed.ordered_items(DailySection.TODAY)
    ][: len(reviewed_today_order)] == reviewed_today_order
    new_work = _item_with_statement(refreshed, NEW_WORK_TITLE)
    assert new_work.today is not None
    assert new_work.today.new_activity is True

    second_generated = cli_actions._generate_daily(refreshed)

    assert second_generated.output_path == first_generated.output_path
    assert second_generated.output_path is not None
    assert second_generated.output_path.read_bytes() == second_generated.content.encode()
    assert second_generated.output_path.read_bytes() != first_bytes
    assert "Reviewed shared Daily wording" in second_generated.content
    assert CROSS_REPOSITORY_TITLE not in second_generated.content.split("## Today", 1)[1]
    assert "Waiting for release approval" in second_generated.content


def test_partial_source_failure_keeps_normal_review_warning_and_history(
    daily_fixture: DailyFixture,
) -> None:
    daily_fixture.sources["claude-code"].unavailable = True

    draft = daily_fixture.workflow().refresh()
    generated = cli_actions._generate_daily(draft)

    assert draft.fallback is False
    assert draft.successful_harnesses == ["opencode", "codex"]
    assert draft.unavailable_harnesses == ["claude-code"]
    assert draft.coverage_warnings == ["Claude Code activity could not be loaded."]
    review_stream = StringIO()
    render.render_daily_review(
        Console(
            file=review_stream,
            color_system=None,
            force_terminal=False,
            width=180,
            height=80,
        ),
        draft,
        cursor=0,
        expanded=set(),
    )
    assert "Claude Code activity could not be loaded." in review_stream.getvalue()
    assert generated.content.startswith(
        "# Daily Standup — 2026-08-13\n\n"
        "> Warning: Claude Code activity could not be loaded.\n\n"
        "## Yesterday\n"
    )
    entry = read_history()[-1]
    assert entry.harnesses == ("opencode", "codex")
    assert entry.unavailable_harnesses == ("claude-code",)


def test_all_source_failure_continue_preserves_original_window_and_manual_review(
    daily_fixture: DailyFixture,
) -> None:
    for source in daily_fixture.sources.values():
        source.unavailable = True

    with pytest.raises(DailySourceUnavailableError) as caught:
        daily_fixture.workflow().refresh()

    error = caught.value
    assert error.standup_date.isoformat() == "2026-08-13"
    assert error.since == datetime(2026, 8, 12, 0, 0, tzinfo=TZ)
    assert error.until == NOW
    continued = cli_actions._continue_daily_empty(error, None)
    manual = continued.add_user_item(DailySection.TODAY, "Coordinate a manual update")
    preview = cli_actions._preview_daily(continued)

    assert continued.scan_since == error.since
    assert continued.scan_until == error.until
    assert continued.work_items == [manual]
    assert continued.successful_harnesses == []
    assert continued.unavailable_harnesses == [
        "opencode",
        "claude-code",
        "codex",
    ]
    assert preview.content.startswith(
        "# Daily Standup — 2026-08-13\n\n"
        "> Warning: All Daily Standup activity sources are unavailable.\n\n"
    )
    assert "- Coordinate a manual update" in preview.content


def test_all_successful_zero_activity_sources_open_an_empty_normal_review(
    daily_fixture: DailyFixture,
) -> None:
    for source in daily_fixture.sources.values():
        source.sessions.clear()

    draft = daily_fixture.workflow().refresh()
    preview = cli_actions._preview_daily(draft)

    assert draft.work_items == []
    assert draft.fallback is False
    assert draft.coverage_warnings == []
    assert draft.successful_harnesses == ["opencode", "claude-code", "codex"]
    assert daily_fixture.runner.calls == []
    assert preview.content == (
        "# Daily Standup — 2026-08-13\n\n"
        "## Yesterday\n"
        "- None\n\n"
        "## Today\n"
        "- None\n\n"
        "## Blockers\n"
        "- None\n"
    )


def test_synthesis_failure_uses_daily_fallback_without_speculative_today(
    daily_fixture: DailyFixture,
) -> None:
    daily_fixture.sources["opencode"].sessions = [
        _session(
            "opencode",
            "fallback-work",
            "Touched fallback implementation",
            daily_fixture.repositories[IIWI_REPOSITORY],
            [
                _activity(
                    "fallback-file",
                    ActivityType.FILE_CHANGE,
                    YESTERDAY,
                    "src/iiwi/fallback.py",
                )
            ],
        )
    ]
    daily_fixture.sources["claude-code"].sessions.clear()
    daily_fixture.sources["codex"].sessions.clear()
    daily_fixture.runner.fail = True

    draft = daily_fixture.workflow().refresh()

    assert draft.fallback is True
    assert len(draft.ordered_items(DailySection.YESTERDAY)) == 1
    assert draft.ordered_items(DailySection.TODAY) == []
    assert cli_actions._preview_daily(draft).content.endswith(
        "## Today\n- None\n\n## Blockers\n- None\n"
    )


def test_next_day_does_not_copy_the_previous_days_reviewed_today_plan(
    daily_fixture: DailyFixture,
) -> None:
    previous = daily_fixture.workflow().refresh()
    previous.add_user_item(DailySection.TODAY, "Tomorrow's manual plan")
    assert cli_actions._persist_daily(previous) is None
    for source in daily_fixture.sources.values():
        source.sessions.clear()
    daily_fixture.now = datetime(2026, 8, 14, 8, 0, tzinfo=TZ)

    next_day = daily_fixture.workflow().refresh(previous)

    assert next_day.standup_date.isoformat() == "2026-08-14"
    assert next_day.work_items == []
    assert "Tomorrow's manual plan" not in cli_actions._preview_daily(next_day).content
