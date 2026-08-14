import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from iiwi.errors import SessionParseError
from iiwi.harnesses.opencode.mapper import OpenCodeExportMapper
from iiwi.harnesses.opencode.source import OpenCodeCliSource
from iiwi.models.session import ActivityType, SessionDescriptor, UsageSemantics
from iiwi.process import CommandResult

FIXTURES = Path(__file__).parents[3] / "fixtures" / "opencode"


def test_load_uses_raw_export_by_default(fake_runner) -> None:
    fake_runner.stdout = '{"messages": []}'
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")

    source.load(SessionDescriptor(harness="opencode", session_id="s1"))

    assert fake_runner.calls[0] == ["opencode", "export", "s1"]


def test_load_adds_sanitize_when_enabled(fake_runner) -> None:
    fake_runner.stdout = '{"messages": []}'
    source = OpenCodeCliSource(
        runner=fake_runner,
        executable="opencode",
        sanitize=True,
    )

    source.load(SessionDescriptor(harness="opencode", session_id="s1"))

    assert fake_runner.calls[0] == ["opencode", "export", "s1", "--sanitize"]


def test_mapper_converts_text_and_tool_parts_to_stable_activities() -> None:
    payload = json.loads((FIXTURES / "export-root.json").read_text())
    descriptor = SessionDescriptor(harness="opencode", session_id="s1")

    session = OpenCodeExportMapper().map(payload, descriptor)

    assert session.title == "Build weekly report"
    assert session.working_directory == "/tmp/repo"
    assert [item.activity_id for item in session.activities] == ["m1:0", "m2:0", "m2:1"]
    assert session.activities[0].activity_type == ActivityType.USER_MESSAGE
    assert session.activities[1].activity_type == ActivityType.ASSISTANT_MESSAGE
    assert session.activities[2].activity_type == ActivityType.TOOL_CALL
    assert session.activities[2].tool_name == "bash"
    assert session.activities[2].content == "pytest -q"
    assert session.token_usage is not None
    assert session.token_usage.semantics == UsageSemantics.UNKNOWN


def test_load_raises_session_parse_error_on_export_failure(fake_runner) -> None:
    fake_runner.set_result(
        "export s1",
        CommandResult(returncode=1, stdout="", stderr="session missing"),
    )
    source = OpenCodeCliSource(runner=fake_runner, executable="opencode")

    with pytest.raises(SessionParseError, match="session missing"):
        source.load(SessionDescriptor(harness="opencode", session_id="s1"))


def test_mapper_falls_back_to_descriptor_title() -> None:
    descriptor = SessionDescriptor(
        harness="opencode",
        session_id="s1",
        title="Database title",
    )

    session = OpenCodeExportMapper().map({"info": {}, "messages": []}, descriptor)

    assert session.title == "Database title"


def test_mapper_prefers_export_title_over_descriptor_title() -> None:
    descriptor = SessionDescriptor(
        harness="opencode",
        session_id="s1",
        title="Database title",
    )

    session = OpenCodeExportMapper().map(
        {"info": {"title": "Export title"}, "messages": []},
        descriptor,
    )

    assert session.title == "Export title"


def test_mapper_keeps_message_without_time_timestamp_less() -> None:
    """A message with no per-message time must not inherit the descriptor's
    updated_at/created_at, or old and unknown-time content gets attributed to
    whatever week the descriptor timestamp falls in."""

    descriptor = SessionDescriptor(
        harness="opencode",
        session_id="s1",
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    payload = {
        "info": {},
        "messages": [
            {
                "info": {"id": "m1", "role": "user"},
                "parts": [{"type": "text", "text": "unknown time"}],
            }
        ],
    }

    session = OpenCodeExportMapper().map(payload, descriptor)

    assert session.activities[0].timestamp is None


def test_mapper_still_honors_message_time_created() -> None:
    """Removing the descriptor fallback must not break the message's own
    top-level time_created resolution path."""

    descriptor = SessionDescriptor(
        harness="opencode",
        session_id="s1",
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    payload = {
        "info": {},
        "messages": [
            {
                "info": {"id": "m1", "role": "user"},
                "time_created": "2026-07-22T10:00:00+08:00",
                "parts": [{"type": "text", "text": "prompt"}],
            }
        ],
    }

    session = OpenCodeExportMapper().map(payload, descriptor)

    assert session.activities[0].timestamp == datetime.fromisoformat(
        "2026-07-22T10:00:00+08:00"
    )
