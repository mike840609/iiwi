from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from iiwi.errors import HarnessSourceError, ReportAlreadyExistsError, ReportOutputError
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.report_options import ReportType
from iiwi.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
)
from iiwi.models.time_range import DateRange
from iiwi.progress import ProgressReporter, ProgressStage
from iiwi.renderers.markdown import DetailLevel, MarkdownRenderer
from iiwi.services.report import ReportService
from iiwi.services.scan import ScanResult, ScanService
from iiwi.summarizers.opencode_run import OpenCodeRunError
from iiwi.summarizers.rule_based import RuleBasedSummarizer
from tests.integration.test_scan_service import FakeSource, StaticResolver
from tests.progress import RecordingProgressReporter

TZ = ZoneInfo("Asia/Taipei")


def period() -> DateRange:
    return DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )


def service(
    source: FakeSource,
    output: Path,
    *,
    progress: ProgressReporter | None = None,
    usage_provider: Callable[[ScanResult], str] | None = None,
    detail: DetailLevel = DetailLevel.FULL,
) -> ReportService:
    return ReportService(
        scan_service=ScanService(
            source=source,
            period=period(),
            resolver=StaticResolver(),
            progress=progress,
        ),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=usage_provider,
        usage_days=10 if usage_provider is not None else None,
        detail=detail,
        progress=progress,
    )


class FakeOpenCodeRunner:
    def __init__(self, narrative: str = "NARRATIVE BODY") -> None:
        self._narrative = narrative
        self.failures: list[OpenCodeRunError] = []
        self.calls: list[dict[str, str]] = []

    def run(self, *, transcript: str, prompt: str, title: str) -> str:
        self.calls.append({"transcript": transcript, "prompt": prompt, "title": title})
        if self.failures:
            raise self.failures.pop(0)
        return self._narrative


def reviewed_draft(*, detail: DetailLevel = DetailLevel.FULL) -> OutcomeReviewDraft:
    return OutcomeReviewDraft(
        report_type=ReportType.MANAGER,
        detail=detail,
        outcomes=[
            Outcome(
                id="reviewed",
                title="Reviewed delivery",
                status=OutcomeStatus.COMPLETED,
                impact="Kept the update focused.",
                rank=0,
                evidence_refs=[
                    EvidenceRef(
                        session_id="ses-reviewed",
                        repository_id="repo-reviewed",
                        commit="abc123",
                    )
                ],
            ),
            Outcome(
                id="user-added",
                title="User-authored follow-up",
                status=OutcomeStatus.IN_PROGRESS,
                impact="Carries the review decision forward.",
                rank=1,
                origin=OutcomeOrigin.USER_ADDED,
            ),
        ],
        blockers="Await stakeholder confirmation.",
        next_week="Ship the reviewed output.",
    )


class ExplodingSummarizer:
    def summarize(self, evidence):
        del evidence
        raise AssertionError("reviewed reports must not invoke the repository summarizer")


def narrative_service(
    source: FakeSource,
    output: Path,
    *,
    runner: FakeOpenCodeRunner,
    usage_provider: Callable[[ScanResult], str] | None = None,
    detail: DetailLevel = DetailLevel.FULL,
) -> ReportService:
    return ReportService(
        scan_service=ScanService(
            source=source,
            period=period(),
            resolver=StaticResolver(),
        ),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=usage_provider,
        usage_days=10 if usage_provider is not None else None,
        detail=detail,
        narrative=True,
        opencode_runner=runner,
        include_subagents=True,
        sanitized=False,
    )


class CompletedWorkSource:
    """A single session with a verified command, so the report has real content
    under Completed and Sessions alike.

    `RuleBasedSummarizer` always populates `sessions` from evidence regardless of
    detail level, so `#### Sessions` is a reliable differentiator: it renders at
    `full` and is dropped at `brief`. A verification command with `exit_code: 0`
    is the only path that produces a `Completed` item (see
    `extraction/pipeline.py`), giving a positive assertion that cannot pass on an
    empty report.
    """

    def discover(self, _period: DateRange) -> list[SessionDescriptor]:
        return [SessionDescriptor(harness="opencode", session_id="ses-verified")]

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        return AgentSession(
            harness="opencode",
            session_id=descriptor.session_id,
            activities=[
                SessionActivity(
                    activity_id=f"{descriptor.session_id}:cmd",
                    activity_type=ActivityType.COMMAND,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="pytest -q",
                    metadata={"exit_code": 0},
                )
            ],
        )


def test_brief_detail_reaches_the_renderer_and_produces_a_genuinely_brief_report(
    tmp_path: Path,
) -> None:
    """Closes a seam a mutation test found: dropping `detail=self._detail` from
    the `renderer.render(...)` call in `ReportService.generate` left the full
    suite green, so `--detail brief` could silently become a no-op end to end.
    """

    result = service(
        CompletedWorkSource(),
        tmp_path / "report.md",
        detail=DetailLevel.BRIEF,
    ).generate(force=False)

    assert "#### Sessions" not in result.content
    assert "## Usage" not in result.content
    assert "#### Completed" in result.content


def test_all_exports_failing_is_an_error(tmp_path: Path) -> None:
    source = FakeSource()
    source.fail_all = True

    with pytest.raises(HarnessSourceError, match="all opencode session loads failed"):
        service(source, tmp_path / "report.md").generate(force=False)


def test_report_service_writes_markdown_for_loaded_sessions(tmp_path: Path) -> None:
    source = FakeSource()
    source.fail_session_ids = {"bad"}
    output = tmp_path / "report.md"

    result = service(source, output).generate(force=False)

    assert result.output_path == output
    assert output.exists()
    assert "# Engineering Worklog" in output.read_text()
    assert result.report.repositories[0].display_name == "Iiwi"


class WarningSummarizer:
    def __init__(self) -> None:
        self._fallback = RuleBasedSummarizer()

    def summarize(self, evidence):
        return self._fallback.summarize(evidence)

    def drain_warnings(self) -> list[str]:
        return ["LLM summary unavailable; used deterministic fallback"]


def test_llm_failure_warning_is_written_into_report(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    progress = RecordingProgressReporter()
    report_service = ReportService(
        scan_service=ScanService(
            source=source,
            period=period(),
            resolver=StaticResolver(),
            progress=progress,
        ),
        summarizer=WarningSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        progress=progress,
    )

    result = report_service.generate(force=False)

    assert output.exists()
    assert any("LLM" in warning for warning in result.warnings)
    assert "LLM summary unavailable" in output.read_text()
    summary_start = progress.events.index(
        ("start", ProgressStage.SUMMARIZING_REPOSITORIES, 1)
    )
    assert progress.events[summary_start + 1] == ("advance", 1)


def test_usage_statistics_are_written_into_the_report(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=lambda _scan: "gpt-5-mini  1234 tokens",
        usage_days=10,
    )

    result = report_service.generate(force=False)

    assert result.report.usage_text == "gpt-5-mini  1234 tokens"
    assert result.report.usage_days == 10
    content = output.read_text()
    assert "## Usage" in content
    assert "gpt-5-mini  1234 tokens" in content


def test_usage_text_is_redacted_on_the_report_model(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=lambda _scan: "auth: Bearer super-secret-token\ngpt-5-mini  1234 tokens",
        usage_days=10,
    )

    result = report_service.generate(force=False)

    assert result.report.usage_text is not None
    assert "super-secret-token" not in result.report.usage_text
    assert "[REDACTED]" in result.report.usage_text
    assert "gpt-5-mini  1234 tokens" in result.report.usage_text


def test_usage_failure_becomes_a_warning(tmp_path: Path) -> None:
    def failing_provider(_scan: ScanResult) -> str:
        raise HarnessSourceError("stats unsupported")

    source = FakeSource()
    output = tmp_path / "report.md"
    report_service = ReportService(
        scan_service=ScanService(source=source, period=period(), resolver=StaticResolver()),
        summarizer=RuleBasedSummarizer(),
        renderer=MarkdownRenderer(),
        period=period(),
        output_path=output,
        now_factory=lambda: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        usage_provider=failing_provider,
        usage_days=10,
    )

    result = report_service.generate(force=False)

    assert result.report.usage_text is None
    assert any("usage statistics unavailable" in warning for warning in result.warnings)
    assert "## Usage" not in output.read_text()


def test_report_emits_repository_and_output_stages(tmp_path: Path) -> None:
    progress = RecordingProgressReporter()

    service(
        FakeSource(),
        tmp_path / "report.md",
        progress=progress,
        usage_provider=lambda _scan: "gpt-5-mini 1234 tokens",
    ).generate()

    assert progress.events == [
        ("start", ProgressStage.DISCOVERING_SESSIONS, None),
        ("start", ProgressStage.EXPORTING_SESSIONS, 3),
        ("advance", 1),
        ("advance", 2),
        ("advance", 3),
        ("start", ProgressStage.PREPARING_EVIDENCE, 1),
        ("advance", 1),
        ("start", ProgressStage.SUMMARIZING_REPOSITORIES, 1),
        ("advance", 1),
        ("start", ProgressStage.COLLECTING_USAGE, None),
        ("start", ProgressStage.RENDERING_REPORT, None),
        ("start", ProgressStage.WRITING_REPORT, None),
    ]


class FailOnUseSource(FakeSource):
    """A source that fails the test if the scan layer is ever touched."""

    def __init__(self) -> None:
        super().__init__()
        self.discovered = 0
        self.loaded = 0

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        del period
        self.discovered += 1
        raise AssertionError("scan must not run when the output file already exists")

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        self.loaded += 1
        raise AssertionError("scan must not run when the output file already exists")


def test_existing_output_fails_fast_before_scan_without_force(tmp_path: Path) -> None:
    output = tmp_path / "report.md"
    output.write_text("existing")
    source = FailOnUseSource()

    with pytest.raises(
        ReportOutputError,
        match=f"report already exists: {output}",
    ):
        service(source, output).generate(force=False)

    assert source.discovered == 0
    assert source.loaded == 0


def test_existing_output_is_overwritten_by_force(tmp_path: Path) -> None:
    output = tmp_path / "report.md"
    output.write_text("existing")
    source = FakeSource()

    result = service(source, output).generate(force=True)

    assert result.output_path == output
    assert "Engineering Worklog" in output.read_text()


def test_existing_output_is_allowed_by_dry_run(tmp_path: Path) -> None:
    output = tmp_path / "report.md"
    output.write_text("existing")
    source = FakeSource()

    service(source, output).generate(dry_run=True)

    assert output.read_text() == "existing"


def test_report_dry_run_skips_write_after_usage_failure(tmp_path: Path) -> None:
    def failing_provider(_scan: ScanResult) -> str:
        raise HarnessSourceError("stats unsupported")

    progress = RecordingProgressReporter()
    result = service(
        FakeSource(),
        tmp_path / "report.md",
        progress=progress,
        usage_provider=failing_provider,
    ).generate(dry_run=True)

    started = [
        event[1]
        for event in progress.events
        if event[0] == "start"
    ]
    assert ProgressStage.COLLECTING_USAGE in started
    assert ProgressStage.RENDERING_REPORT in started
    assert ProgressStage.WRITING_REPORT not in started
    assert any("usage statistics unavailable" in warning for warning in result.warnings)


def test_narrative_mode_emits_the_narrative_body(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    runner = FakeOpenCodeRunner()

    result = narrative_service(source, output, runner=runner).generate(force=False)

    assert result.report.narrative_text == "NARRATIVE BODY"
    assert result.report.repositories == []
    content = output.read_text()
    assert "# Engineering Worklog" in content
    assert "NARRATIVE BODY" in content


def test_narrative_mode_feeds_a_grouped_transcript(tmp_path: Path) -> None:
    source = FakeSource()
    runner = FakeOpenCodeRunner()

    narrative_service(
        source, tmp_path / "report.md", runner=runner
    ).generate(force=False)

    assert len(runner.calls) == 1
    transcript = runner.calls[0]["transcript"]
    assert "# Iiwi sessions grouped by repository" in transcript
    assert "## Project:" in transcript
    assert "Subagent sessions included: yes" in transcript
    assert "OpenCode" in runner.calls[0]["prompt"]


def test_narrative_failure_falls_back_to_the_structured_report(
    tmp_path: Path,
) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    runner = FakeOpenCodeRunner()
    runner.failures.append(OpenCodeRunError("opencode run failed"))

    result = narrative_service(source, output, runner=runner).generate(force=False)

    assert result.report.narrative_text is None
    assert result.report.repositories
    assert any(
        "opencode run unavailable" in warning for warning in result.warnings
    )
    content = output.read_text()
    assert "## Repositories" in content
    assert "NARRATIVE BODY" not in content


def test_narrative_mode_render_usage_and_warnings(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"
    runner = FakeOpenCodeRunner()

    result = narrative_service(
        source,
        output,
        runner=runner,
        usage_provider=lambda _scan: "gpt-5-mini  1234 tokens",
    ).generate(force=False)

    assert result.report.usage_text == "gpt-5-mini  1234 tokens"
    content = output.read_text()
    assert "## Usage" in content
    assert "gpt-5-mini  1234 tokens" in content


def test_narrative_brief_detail_changes_the_prompt_and_wrapper(tmp_path: Path) -> None:
    runner = FakeOpenCodeRunner()
    usage_calls: list[ScanResult] = []

    def usage_provider(scan: ScanResult) -> str:
        usage_calls.append(scan)
        return "gpt-5-mini  1234 tokens"

    result = narrative_service(
        FakeSource(),
        tmp_path / "report.md",
        runner=runner,
        usage_provider=usage_provider,
        detail=DetailLevel.BRIEF,
    ).generate()

    assert (
        "Do not include session IDs, file lists, command lists, or Usage."
        in runner.calls[0]["prompt"]
    )
    assert "## Usage" not in result.content
    assert result.report.usage_text is None
    assert usage_calls == []


def test_narrative_mode_is_off_by_default(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "report.md"

    result = service(source, output).generate(force=False)

    assert result.report.narrative_text is None
    assert result.report.repositories
    assert "## Repositories" in output.read_text()


def test_reviewed_report_uses_the_supplied_draft_and_returns_the_same_scan(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reviewed.md"
    report_service = service(FakeSource(), output)
    report_service._summarizer = ExplodingSummarizer()
    scan = ScanResult(
        period=period(),
        candidate_session_count=4,
        loaded_session_count=3,
        failed_session_count=1,
    )

    result = report_service.generate_reviewed(reviewed_draft(), scan=scan)

    assert result.scan is scan
    assert result.scan.loaded_session_count == 3
    assert "Reviewed delivery" in result.content
    assert "User-authored follow-up" in result.content
    assert "(User added)" in result.content


def test_reviewed_report_preserves_dry_run_and_output_conflict_behavior(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reviewed.md"
    output.write_text("existing", encoding="utf-8")
    report_service = service(FakeSource(), output)
    scan = ScanResult(
        period=period(),
        candidate_session_count=0,
        loaded_session_count=0,
        failed_session_count=0,
    )

    with pytest.raises(ReportAlreadyExistsError, match=f"report already exists: {output}"):
        report_service.generate_reviewed(reviewed_draft(), scan=scan)

    result = report_service.generate_reviewed(reviewed_draft(), scan=scan, dry_run=True)

    assert "Reviewed delivery" in result.content
    assert output.read_text(encoding="utf-8") == "existing"


def test_reviewed_report_redacts_draft_text_and_evidence_before_rendering(
    tmp_path: Path,
) -> None:
    draft = reviewed_draft()
    draft.outcomes[0].title = "Delivered token=title-secret"
    draft.outcomes[0].impact = "Impact token=impact-secret"
    draft.outcomes[0].evidence_refs[0] = EvidenceRef(
        session_id="token=session-secret",
        repository_id="token=repository-secret",
        commit="token=commit-secret",
        file="token=file-secret",
    )
    draft.blockers = "Blocked by token=blockers-secret"
    draft.next_week = "Next token=next-week-secret"

    result = service(FakeSource(), tmp_path / "reviewed.md").generate_reviewed(
        draft,
        scan=ScanResult(
            period=period(),
            candidate_session_count=0,
            loaded_session_count=0,
            failed_session_count=0,
        ),
    )

    for secret in (
        "title-secret",
        "impact-secret",
        "session-secret",
        "repository-secret",
        "commit-secret",
        "file-secret",
        "blockers-secret",
        "next-week-secret",
    ):
        assert secret not in result.content
    assert "[REDACTED]" in result.content


def test_reviewed_report_collects_usage_only_for_full_detail(tmp_path: Path) -> None:
    usage_calls: list[ScanResult] = []

    def usage_provider(scan: ScanResult) -> str:
        usage_calls.append(scan)
        return "gpt-5 123 tokens"

    scan = ScanResult(
        period=period(),
        candidate_session_count=0,
        loaded_session_count=0,
        failed_session_count=0,
    )
    brief_result = service(
        FakeSource(),
        tmp_path / "brief.md",
        usage_provider=usage_provider,
    ).generate_reviewed(reviewed_draft(detail=DetailLevel.BRIEF), scan=scan)
    full_result = service(
        FakeSource(),
        tmp_path / "full.md",
        usage_provider=usage_provider,
    ).generate_reviewed(reviewed_draft(detail=DetailLevel.FULL), scan=scan)

    assert brief_result.report.usage_text is None
    assert "## Usage" not in brief_result.content
    assert full_result.report.usage_text == "gpt-5 123 tokens"
    assert "## Usage" in full_result.content
    assert usage_calls == [scan]
