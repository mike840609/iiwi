from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from iiwi import cli
from iiwi.errors import (
    DailySourceUnavailableError,
    OutcomeSynthesisError,
    ReportOutputError,
)
from iiwi.history import HistoryKind
from iiwi.interactive import cli_actions
from iiwi.interactive.models import ReportDraft
from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import (
    Outcome,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.report_options import DetailLevel, ReportType
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import AgentSession
from iiwi.models.time_range import DateRange
from iiwi.progress import ProgressStage
from iiwi.services.scan import ScanResult
from iiwi.summarizers.opencode_run import OpenCodeRunError
from tests.progress import RecordingProgressReporter

TZ = ZoneInfo("Asia/Taipei")


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _scan() -> ScanResult:
    return ScanResult(
        period=_period(),
        candidate_session_count=0,
        loaded_session_count=0,
        failed_session_count=0,
        resolved_sessions=[],
        sessions_by_repository={},
    )


def _review() -> OutcomeReviewDraft:
    return OutcomeReviewDraft(
        outcomes=[
            Outcome(
                id="user-added",
                title="Reviewed launch plan",
                status=OutcomeStatus.IN_PROGRESS,
                rank=0,
                origin=OutcomeOrigin.USER_ADDED,
            )
        ],
        report_type=ReportType.MANAGER,
    )


def _daily_draft(*, standup_date: date = date(2026, 8, 13)) -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=standup_date,
        scan_since=datetime(2026, 8, 12, tzinfo=TZ),
        scan_until=datetime(2026, 8, 13, 10, tzinfo=TZ),
        work_items=[
            DailyStandupWorkItem(
                id="manual",
                today=DailySectionItem(
                    statement="Keep the reviewed plan",
                    source=DailyStatementSource.USER_ADDED,
                    user_edited=True,
                ),
            )
        ],
        successful_harnesses=["opencode", "codex"],
        unavailable_harnesses=["claude-code"],
        repository_count=2,
        session_count=3,
    )


def test_new_draft_uses_saved_manager_type_and_its_brief_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        report=SimpleNamespace(
            timezone="Asia/Taipei",
            quick_review_report_type=ReportType.MANAGER,
        )
    )
    now = datetime(2026, 8, 10, 12, tzinfo=TZ)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)
    monkeypatch.setattr(cli, "_enabled_harnesses", lambda settings: [cli.Harness.CODEX])

    draft = cli_actions._new_draft()

    assert draft.report_type is ReportType.MANAGER
    assert draft.detail is DetailLevel.BRIEF


def test_synthesize_builds_one_runner_and_uses_the_filtered_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = _scan()
    settings = SimpleNamespace(
        harnesses=SimpleNamespace(
            opencode=SimpleNamespace(
                cli=SimpleNamespace(
                    executable="custom-opencode",
                    model="review-model",
                    run_timeout_seconds=321.0,
                )
            )
        ),
        report=SimpleNamespace(quick_review_max_evidence_bytes=4321),
    )
    runner_timeouts: list[float] = []
    opencode_arguments: list[dict[str, object]] = []
    synthesized_scans: list[ScanResult] = []
    evidence_budgets: list[int] = []

    class FakeCommandRunner:
        def __init__(self, *, timeout_seconds: float) -> None:
            runner_timeouts.append(timeout_seconds)

    class FakeOpenCodeRunner:
        def __init__(self, **kwargs: object) -> None:
            opencode_arguments.append(kwargs)

    class FakeSynthesisService:
        def __init__(self, runner: object, *, max_evidence_bytes: int) -> None:
            assert isinstance(runner, FakeOpenCodeRunner)
            evidence_budgets.append(max_evidence_bytes)

        def synthesize(self, received: ScanResult) -> SimpleNamespace:
            synthesized_scans.append(received)
            return SimpleNamespace(
                outcomes=_review().outcomes,
                warnings=["3 older session(s) did not fit"],
            )

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli_actions, "CommandRunner", FakeCommandRunner)
    monkeypatch.setattr(cli_actions, "OpenCodeRunner", FakeOpenCodeRunner, raising=False)
    monkeypatch.setattr(
        cli_actions,
        "OutcomeSynthesisService",
        FakeSynthesisService,
        raising=False,
    )
    draft = ReportDraft(
        harness="codex",
        period=_period(),
        report_type=ReportType.MANAGER,
    )

    review = cli_actions._synthesize(draft, scan)

    assert runner_timeouts == [321.0]
    assert len(opencode_arguments) == 1
    assert opencode_arguments[0]["executable"] == "custom-opencode"
    assert opencode_arguments[0]["model"] == "review-model"
    assert synthesized_scans == [scan]
    assert synthesized_scans[0] is scan
    assert evidence_budgets == [4321]
    assert review.warnings == ["3 older session(s) did not fit"]
    assert review.report_type is ReportType.MANAGER
    assert review.detail is DetailLevel.BRIEF
    assert review.detail_overridden is False


def test_synthesize_reports_progress_while_the_model_call_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this the TUI holds its last frame for the whole opencode run."""

    settings = SimpleNamespace(
        harnesses=SimpleNamespace(
            opencode=SimpleNamespace(
                cli=SimpleNamespace(
                    executable="opencode",
                    model=None,
                    run_timeout_seconds=600.0,
                )
            )
        ),
        report=SimpleNamespace(quick_review_max_evidence_bytes=4321),
    )
    recorder = RecordingProgressReporter()
    stages_during_call: list[object] = []

    class FakeReporter:
        @contextmanager
        def progress(self):
            yield recorder

    class FakeSynthesisService:
        def __init__(self, runner: object, *, max_evidence_bytes: int) -> None:
            pass

        def synthesize(self, received: ScanResult) -> SimpleNamespace:
            stages_during_call.extend(recorder.events)
            return SimpleNamespace(outcomes=_review().outcomes, warnings=[])

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli_actions, "CommandRunner", lambda **kwargs: object())
    monkeypatch.setattr(cli_actions, "OpenCodeRunner", lambda **kwargs: object())
    monkeypatch.setattr(cli_actions, "ConsoleReporter", FakeReporter)
    monkeypatch.setattr(
        cli_actions,
        "OutcomeSynthesisService",
        FakeSynthesisService,
    )
    draft = ReportDraft(harness="codex", period=_period(), report_type=ReportType.MANAGER)

    cli_actions._synthesize(draft, _scan())

    assert stages_during_call == [
        ("start", ProgressStage.SYNTHESIZING_OUTCOMES, None)
    ]


def test_synthesize_translates_real_opencode_failure_for_controller_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = RepositoryIdentity(
        repository_id="repo-a",
        display_name="repo-a",
        identity_type=RepositoryIdentityType.PATH_FALLBACK,
        working_directory="/tmp/repo-a",
        resolution_method="test",
    )
    resolved = ResolvedSession(
        session=AgentSession(
            harness="codex",
            session_id="ses-a",
            working_directory="/tmp/repo-a",
        ),
        repository=repository,
    )
    scan = ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
        sessions_by_repository={"repo-a": [resolved]},
    )
    settings = SimpleNamespace(
        harnesses=SimpleNamespace(
            opencode=SimpleNamespace(
                cli=SimpleNamespace(
                    executable="missing-opencode",
                    model="",
                    run_timeout_seconds=1.0,
                )
            )
        ),
        report=SimpleNamespace(quick_review_max_evidence_bytes=40000),
    )

    class FailingOpenCodeRunner:
        def run(self, *, transcript: str, prompt: str, title: str) -> str:
            del transcript, prompt, title
            raise OpenCodeRunError("missing-opencode: executable not found")

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli_actions,
        "OpenCodeRunner",
        lambda **kwargs: FailingOpenCodeRunner(),
    )

    with pytest.raises(
        OutcomeSynthesisError,
        match="missing-opencode: executable not found",
    ):
        cli_actions._synthesize(
            ReportDraft(harness="codex", period=_period()),
            scan,
        )


def test_synthesize_translates_temp_io_failure_for_controller_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        harnesses=SimpleNamespace(
            opencode=SimpleNamespace(
                cli=SimpleNamespace(
                    executable="opencode",
                    model="",
                    run_timeout_seconds=1.0,
                )
            )
        ),
        report=SimpleNamespace(quick_review_max_evidence_bytes=40000),
    )

    class BrokenSynthesisService:
        def __init__(self, runner: object, *, max_evidence_bytes: int) -> None:
            del runner, max_evidence_bytes

        def synthesize(self, scan: ScanResult) -> object:
            del scan
            raise OSError("cannot write synthesis transcript")

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli_actions,
        "OutcomeSynthesisService",
        BrokenSynthesisService,
        raising=False,
    )

    with pytest.raises(
        OutcomeSynthesisError,
        match="cannot write synthesis transcript",
    ):
        cli_actions._synthesize(
            ReportDraft(harness="codex", period=_period()),
            _scan(),
        )


def test_generate_reviewed_passes_the_same_review_object_to_report_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = _scan()
    review = _review()
    draft = ReportDraft(harness="codex", period=_period(), dry_run=True)
    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 10, 12, tzinfo=TZ)
    received: list[tuple[OutcomeReviewDraft, dict[str, object]]] = []

    class FakeService:
        def generate_reviewed(
            self,
            received_review: OutcomeReviewDraft,
            **kwargs: object,
        ) -> SimpleNamespace:
            received.append((received_review, kwargs))
            return SimpleNamespace(output_path=None, content="reviewed report")

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)
    monkeypatch.setattr(cli, "_default_output_path", lambda settings, period: None)
    monkeypatch.setattr(cli, "_build_report_service", lambda *args, **kwargs: FakeService())

    result = cli_actions._generate_reviewed(draft, scan, review, False)

    assert len(received) == 1
    assert received[0][0] is review
    assert received[0][1] == {
        "scan": scan,
        "force": False,
        "dry_run": True,
    }
    assert result.content == "reviewed report"


def test_save_report_type_writes_only_the_quick_review_preference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli_actions.config_store,
        "set_value",
        lambda key, value: writes.append((key, value)),
        raising=False,
    )

    cli_actions._save_report_type(ReportType.ENGINEERING)

    assert writes == [("report.quick_review_report_type", "engineering")]


def test_edit_and_add_callbacks_prompt_only_for_user_editable_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = iter(
        [
            "Edited title",
            "Supported impact",
            "completed",
            "Manual review",
            "Reduced ambiguity",
            "in_progress",
        ]
    )
    monkeypatch.setattr(cli_actions.typer, "prompt", lambda *args, **kwargs: next(prompts))
    original = _review().outcomes[0]

    edited = cli_actions._edit_outcome(original)
    added = cli_actions._add_outcome()

    assert (edited.title, edited.impact, edited.status) == (
        "Edited title",
        "Supported impact",
        OutcomeStatus.COMPLETED,
    )
    assert edited.id == original.id
    assert added is not None
    assert (added.title, added.impact, added.status) == (
        "Manual review",
        "Reduced ambiguity",
        OutcomeStatus.IN_PROGRESS,
    )
    assert added.origin is OutcomeOrigin.USER_ADDED


@pytest.mark.parametrize("answer", ["", "none", "NoNe"])
def test_edit_gap_normalizes_blank_and_none_to_none(
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    monkeypatch.setattr(cli_actions.typer, "prompt", lambda *args, **kwargs: answer)

    assert cli_actions._edit_gap("Blockers", "Existing") is None


def test_edit_gap_enter_clears_an_existing_value_with_the_real_prompt() -> None:
    app = cli_actions.typer.Typer()

    @app.command()
    def edit_gap() -> None:
        value = cli_actions._edit_gap("Blockers", "Waiting on review")
        cli_actions.typer.echo("<none>" if value is None else value)

    result = CliRunner().invoke(app, input="\n")

    assert result.exit_code == 0
    assert "Blockers" in result.stdout
    assert "Waiting on review" in result.stdout
    assert "<none>" in result.stdout


def test_choose_harness_cycles_enabled_values_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_load_settings", lambda: object())
    monkeypatch.setattr(
        cli,
        "_enabled_harnesses",
        lambda settings: [cli.Harness.OPENCODE, cli.Harness.CLAUDE_CODE, cli.Harness.CODEX],
    )
    monkeypatch.setattr(
        cli,
        "_prompt",
        lambda prompt: pytest.fail(f"typed prompt should not run: {prompt}"),
    )

    assert cli_actions._choose_harness("opencode") == "claude-code"
    assert cli_actions._choose_harness("claude-code") == "codex"
    assert cli_actions._choose_harness("codex") == "opencode"


def test_choose_harness_keeps_only_enabled_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_load_settings", lambda: object())
    monkeypatch.setattr(
        cli,
        "_enabled_harnesses",
        lambda settings: [cli.Harness.CODEX],
    )

    assert cli_actions._choose_harness("codex") == "codex"


def test_choose_period_reaches_every_named_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The arrow advertises five windows, so pressing it must reach all five.

    The old cycle located the current window by comparing its timestamps against a
    freshly derived list. A rolling window's `until` is the moment it was built, so
    the comparison failed on every other press and snapped back to the first entry:
    `Last 14 days` and `Last 30 days` could not be reached at all. The previous test
    missed it by freezing the clock, which is the one thing that made it work.
    """

    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_prompt",
        lambda prompt: pytest.fail(f"typed prompt should not run: {prompt}"),
    )

    # A clock that advances between presses, as a real one does.
    ticks = iter(datetime(2026, 8, 7, 12, second=tick, tzinfo=TZ) for tick in range(30))
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: next(ticks))

    label: str | None = None
    seen: list[str] = []
    for _ in range(6):
        label, _range = cli_actions._choose_period(label)
        seen.append(label)

    assert seen == [
        "This week",
        "Last week",
        "Last 7 days",
        "Last 14 days",
        "Last 30 days",
        "This week",
    ]


def test_choose_period_starts_the_cycle_for_an_unnamed_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `--since` range carries no name, so the arrow starts the cycle rather than guessing."""

    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 7, 12, tzinfo=TZ)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)

    label, period = cli_actions._choose_period(None)

    assert label == "This week"
    assert period == DateRange.current_week(now=now)


def test_exclude_repository_appends_to_the_exclusion_setting(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))

    message = cli_actions._exclude_repository(
        "git:github.com/mike/dotfiles", "Dotfiles"
    )

    assert "Dotfiles" in message
    assert "future scans will skip it" in message
    settings = cli._load_settings()
    assert settings.report.excluded_repository_ids() == ("git:github.com/mike/dotfiles",)


def test_exclude_repository_keeps_already_configured_exclusions(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    cli_actions._exclude_repository("git:github.com/mike/notes", "Notes")

    cli_actions._exclude_repository("git:github.com/mike/dotfiles", "Dotfiles")

    settings = cli._load_settings()
    assert settings.report.excluded_repository_ids() == (
        "git:github.com/mike/notes",
        "git:github.com/mike/dotfiles",
    )


def test_exclude_repository_refuses_when_the_environment_owns_the_setting(
    monkeypatch, tmp_path
) -> None:
    """An exported override outranks the settings file, so persisting an
    exclusion there would be a lie the next run ignores: refuse to write and
    say which variable owns the setting instead."""

    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv(
        "IIWI_REPORT__EXCLUDE_REPOSITORIES",
        "git:github.com/mike/env-driven",
    )

    message = cli_actions._exclude_repository(
        "git:github.com/mike/dotfiles", "Dotfiles"
    )

    assert "IIWI_REPORT__EXCLUDE_REPOSITORIES" in message
    assert not (tmp_path / "config.env").exists()


def test_exclude_repository_is_idempotent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    cli_actions._exclude_repository("git:github.com/mike/dotfiles", "Dotfiles")

    message = cli_actions._exclude_repository("git:github.com/mike/dotfiles", "Dotfiles")

    assert "already excluded" in message
    assert cli._load_settings().report.excluded_repository_ids() == (
        "git:github.com/mike/dotfiles",
    )


def test_save_and_restore_round_trip_through_the_state_file(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("IIWI_STATE_FILE", str(tmp_path / "state.json"))

    assert cli_actions._restore_selection("opencode", _period(), True) is None

    cli_actions._save_selection(
        "opencode", _period(), True, {"ses-a", "ses-b"}
    )

    assert cli_actions._restore_selection("opencode", _period(), True) == {
        "ses-a",
        "ses-b",
    }


def test_start_daily_builds_every_enabled_harness_with_one_shared_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        report=SimpleNamespace(
            timezone="Asia/Taipei",
            quick_review_max_evidence_bytes=40000,
        ),
        harnesses=SimpleNamespace(
            opencode=SimpleNamespace(
                cli=SimpleNamespace(
                    executable="opencode",
                    model=None,
                    run_timeout_seconds=600.0,
                    sanitize=True,
                )
            )
        ),
    )
    calls: list[tuple[object, bool, cli.Harness, bool]] = []

    class EmptyScanService:
        def __init__(self, period: DateRange) -> None:
            self.period = period

        def scan(self) -> ScanResult:
            return ScanResult(
                period=self.period,
                candidate_session_count=0,
                loaded_session_count=0,
                failed_session_count=0,
            )

    def build_scan_service(
        received_settings: object,
        period: DateRange,
        root_only: bool,
        *,
        harness: cli.Harness,
        sanitize: bool,
        progress: object = None,
    ) -> EmptyScanService:
        del progress
        assert received_settings is settings
        calls.append((period, root_only, harness, sanitize))
        return EmptyScanService(period)

    monkeypatch.setenv("IIWI_DAILY_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 8, 13, 10, tzinfo=TZ),
    )
    monkeypatch.setattr(
        cli,
        "_enabled_harnesses",
        lambda value: [
            cli.Harness.OPENCODE,
            cli.Harness.CLAUDE_CODE,
            cli.Harness.CODEX,
        ],
    )
    monkeypatch.setattr(cli, "_build_scan_service", build_scan_service)

    draft = cli_actions._start_daily(None)

    assert draft.work_items == []
    assert [call[2] for call in calls] == [
        cli.Harness.OPENCODE,
        cli.Harness.CLAUDE_CODE,
        cli.Harness.CODEX,
    ]
    assert len({id(call[0]) for call in calls}) == 1
    assert all(call[1] is False for call in calls)
    assert [call[3] for call in calls] == [True, False, False]


def test_continue_daily_empty_reuses_original_error_window_and_same_day_review() -> None:
    previous = _daily_draft()
    error = DailySourceUnavailableError(
        unavailable_harnesses=("opencode", "claude-code", "codex"),
        standup_date=date(2026, 8, 13),
        since=datetime(2026, 8, 12, tzinfo=TZ),
        until=datetime(2026, 8, 13, 23, 59, tzinfo=TZ),
    )

    draft = cli_actions._continue_daily_empty(error, previous)

    assert draft.standup_date == error.standup_date
    assert draft.scan_since == error.since
    assert draft.scan_until == error.until
    assert draft.successful_harnesses == []
    assert draft.unavailable_harnesses == list(error.unavailable_harnesses)
    assert len(draft.coverage_warnings) == 1
    assert "unavailable" in draft.coverage_warnings[0].casefold()
    assert draft.work_items[0].today is not None
    assert draft.work_items[0].today.statement == "Keep the reviewed plan"


@pytest.mark.parametrize(
    "failure",
    [OSError("disk full"), ReportOutputError("secure write failed")],
)
def test_persist_daily_returns_a_review_warning_without_printing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
) -> None:
    monkeypatch.setattr(
        cli_actions,
        "save_daily_draft",
        lambda draft: (_ for _ in ()).throw(failure),
    )

    warning = cli_actions._persist_daily(_daily_draft())

    assert warning is not None
    assert "save" in warning.casefold()
    assert capsys.readouterr().out == ""


def test_preview_daily_only_renders_the_supplied_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _daily_draft()
    received: list[DailyStandupDraft] = []

    class FakeDailyReportService:
        def preview(self, current: DailyStandupDraft) -> SimpleNamespace:
            received.append(current)
            return SimpleNamespace(
                output_path=None,
                content="# Daily\n",
                repository_count=2,
                session_count=3,
            )

        def generate(self, *args: object, **kwargs: object) -> None:
            pytest.fail("preview must not generate or write")

    monkeypatch.setattr(cli_actions, "DailyReportService", FakeDailyReportService)

    result = cli_actions._preview_daily(draft)

    assert received == [draft]
    assert result.output_path is None
    assert result.content == "# Daily\n"


def test_generate_daily_orders_artifact_state_and_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    draft = _daily_draft()
    now = datetime(2026, 8, 13, 11, tzinfo=TZ)
    settings = SimpleNamespace(
        report=SimpleNamespace(
            output_directory=tmp_path,
            timezone="Asia/Taipei",
        )
    )
    events: list[tuple[str, object]] = []

    class FakeDailyReportService:
        def generate(
            self,
            current: DailyStandupDraft,
            *,
            output_path: Path,
        ) -> SimpleNamespace:
            assert current is draft
            events.append(("write", output_path))
            return SimpleNamespace(
                output_path=output_path,
                content="# Daily\n",
                repository_count=2,
                session_count=3,
            )

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)
    monkeypatch.setattr(cli_actions, "DailyReportService", FakeDailyReportService)
    monkeypatch.setattr(
        cli_actions,
        "save_daily_draft",
        lambda current: events.append(("state", current)),
    )
    monkeypatch.setattr(
        cli_actions,
        "append_history",
        lambda entry: events.append(("history", entry)),
    )

    result = cli_actions._generate_daily(draft)

    expected_path = tmp_path / "daily-standup-2026-08-13.md"
    assert [event[0] for event in events] == ["write", "state", "history"]
    assert events[0][1] == expected_path
    assert events[1][1] is draft
    entry = events[2][1]
    assert entry.kind is HistoryKind.DAILY_STANDUP
    assert entry.generated_at == now
    assert entry.since == draft.scan_since
    assert entry.until == draft.scan_until
    assert entry.output_path == expected_path
    assert entry.harnesses == ("opencode", "codex")
    assert entry.unavailable_harnesses == ("claude-code",)
    assert result.output_path == expected_path


def test_generate_daily_stops_before_bookkeeping_when_the_artifact_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        report=SimpleNamespace(output_directory=tmp_path, timezone="Asia/Taipei")
    )

    class FailingDailyReportService:
        def generate(self, *args: object, **kwargs: object) -> None:
            raise ReportOutputError("disk unavailable")

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli_actions, "DailyReportService", FailingDailyReportService)
    monkeypatch.setattr(
        cli_actions,
        "save_daily_draft",
        lambda draft: pytest.fail("state must follow a successful artifact write"),
    )
    monkeypatch.setattr(
        cli_actions,
        "append_history",
        lambda entry: pytest.fail("history must follow a successful artifact write"),
    )

    with pytest.raises(ReportOutputError, match="disk unavailable"):
        cli_actions._generate_daily(_daily_draft())


def test_generate_daily_rejects_a_stale_review_before_any_side_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        report=SimpleNamespace(output_directory=tmp_path, timezone="Asia/Taipei")
    )
    events: list[str] = []

    class FakeDailyReportService:
        def generate(self, *args: object, **kwargs: object) -> SimpleNamespace:
            events.append("write")
            return SimpleNamespace(
                output_path=tmp_path / "daily-standup-2026-08-13.md",
                content="# Daily\n",
                repository_count=2,
                session_count=3,
            )

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 8, 14, 0, 1, tzinfo=TZ),
    )
    monkeypatch.setattr(cli_actions, "DailyReportService", FakeDailyReportService)
    monkeypatch.setattr(
        cli_actions,
        "save_daily_draft",
        lambda draft: events.append("state"),
    )
    monkeypatch.setattr(
        cli_actions,
        "append_history",
        lambda entry: events.append("history"),
    )

    with pytest.raises(ReportOutputError, match="Refresh Daily Standup"):
        cli_actions._generate_daily(_daily_draft())

    assert events == []


def test_generate_daily_contains_state_and_history_bookkeeping_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        report=SimpleNamespace(output_directory=tmp_path, timezone="Asia/Taipei")
    )
    events: list[str] = []

    class FakeDailyReportService:
        def generate(self, *args: object, **kwargs: object) -> SimpleNamespace:
            events.append("write")
            return SimpleNamespace(
                output_path=tmp_path / "daily-standup-2026-08-13.md",
                content="# Daily\n",
                repository_count=2,
                session_count=3,
            )

    def fail_state(draft: DailyStandupDraft) -> None:
        events.append("state")
        raise ReportOutputError("state unavailable")

    def fail_history(entry: object) -> None:
        events.append("history")
        raise OSError("history unavailable")

    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 8, 13, 11, tzinfo=TZ),
    )
    monkeypatch.setattr(cli_actions, "DailyReportService", FakeDailyReportService)
    monkeypatch.setattr(cli_actions, "save_daily_draft", fail_state)
    monkeypatch.setattr(cli_actions, "append_history", fail_history)

    result = cli_actions._generate_daily(_daily_draft())

    assert events == ["write", "state", "history"]
    assert result.content == "# Daily\n"


def test_build_interactive_actions_wires_all_daily_callbacks() -> None:
    actions = cli_actions.build_interactive_actions()

    assert actions.start_daily is cli_actions._start_daily
    assert actions.continue_daily_empty is cli_actions._continue_daily_empty
    assert actions.persist_daily is cli_actions._persist_daily
    assert actions.preview_daily is cli_actions._preview_daily
    assert actions.generate_daily is cli_actions._generate_daily
    assert actions.edit_daily_statement is cli_actions._edit_daily_statement
    assert actions.add_daily_statement is cli_actions._add_daily_statement
