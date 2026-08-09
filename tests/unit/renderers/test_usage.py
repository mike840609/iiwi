from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.errors import HarnessSourceError
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.renderers.usage import render_activity_usage
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, tzinfo=TZ),
    until=datetime(2026, 7, 27, tzinfo=TZ),
)


def _activity(activity_id: str, model: str, usage: dict[str, int]) -> SessionActivity:
    return SessionActivity(
        activity_id=activity_id,
        activity_type=ActivityType.ASSISTANT_MESSAGE,
        timestamp=datetime(2026, 7, 21, tzinfo=TZ),
        content="did the thing",
        metadata={"model": model, "usage": usage},
    )


def _scan(*activities: SessionActivity) -> ScanResult:
    session = AgentSession(
        harness="claude-code",
        session_id="sess-1",
        activities=list(activities),
    )
    resolved = ResolvedSession(
        session=session,
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )
    return ScanResult(
        period=PERIOD,
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
    )


def test_renders_one_row_per_model_plus_a_total() -> None:
    scan = _scan(
        _activity(
            "a-1",
            "claude-opus-5",
            {
                "input_tokens": 10,
                "output_tokens": 200,
                "cache_read_tokens": 1000,
                "cache_write_tokens": 50,
            },
        ),
        _activity(
            "a-2",
            "claude-opus-5",
            {"input_tokens": 5, "output_tokens": 100, "cache_read_tokens": 0},
        ),
        _activity(
            "a-3",
            "claude-sonnet-5",
            {"input_tokens": 1, "output_tokens": 2},
        ),
    )

    text = render_activity_usage(scan, harness="claude-code")
    lines = text.splitlines()

    assert lines[0].startswith("Model")
    for label in ("Input", "Output", "Cache read", "Cache write"):
        assert label in lines[0]
    assert "claude-opus-5" in lines[1]
    assert "300" in lines[1]  # 200 + 100 output tokens
    assert "1,000" in lines[1]  # thousands separator
    assert "claude-sonnet-5" in lines[2]
    assert lines[3].startswith("Total")
    assert "302" in lines[3]  # 300 + 2 output tokens


def test_orders_models_by_output_tokens_descending() -> None:
    scan = _scan(
        _activity("a-1", "small-model", {"output_tokens": 1}),
        _activity("a-2", "big-model", {"output_tokens": 999}),
    )

    lines = render_activity_usage(scan, harness="claude-code").splitlines()

    assert "big-model" in lines[1]
    assert "small-model" in lines[2]


def test_skips_a_model_whose_totals_are_all_zero() -> None:
    """Claude Code writes `<synthetic>` for local and error placeholders."""

    scan = _scan(
        _activity("a-1", "claude-opus-5", {"input_tokens": 10, "output_tokens": 200}),
        _activity(
            "a-2",
            "<synthetic>",
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
        ),
    )

    text = render_activity_usage(scan, harness="claude-code")

    assert "<synthetic>" not in text
    assert len(text.splitlines()) == 3  # header, one model, total


def test_raises_when_every_model_total_is_zero() -> None:
    scan = _scan(_activity("a-1", "<synthetic>", {"input_tokens": 0}))

    with pytest.raises(HarnessSourceError):
        render_activity_usage(scan, harness="claude-code")


def test_raises_when_no_activity_carries_usage() -> None:
    """ReportService turns HarnessSourceError into a report warning."""

    scan = _scan(
        SessionActivity(
            activity_id="a-1",
            activity_type=ActivityType.ASSISTANT_MESSAGE,
            timestamp=datetime(2026, 7, 21, tzinfo=TZ),
            content="no usage metadata",
        )
    )

    with pytest.raises(HarnessSourceError, match="Claude Code sessions carried no"):
        render_activity_usage(scan, harness="claude-code")


def test_error_uses_the_codex_display_name_not_the_slug() -> None:
    """The harness argument is the `Harness.value` slug (e.g. "codex"), but the
    error text should read as prose, matching what Claude Code got before the
    usage renderer moved out of the harness package.
    """

    scan = _scan(
        SessionActivity(
            activity_id="a-1",
            activity_type=ActivityType.ASSISTANT_MESSAGE,
            timestamp=datetime(2026, 7, 21, tzinfo=TZ),
            content="no usage metadata",
        )
    )

    with pytest.raises(HarnessSourceError, match="Codex sessions carried no"):
        render_activity_usage(scan, harness="codex")
