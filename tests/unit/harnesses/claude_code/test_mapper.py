import json
from pathlib import Path

import pytest

from iiwi.harnesses.claude_code.mapper import ClaudeCodeJsonlMapper
from iiwi.models.session import ActivityType, SessionDescriptor, UsageSemantics

# Derived from this file, not from the working directory, so the test passes when
# pytest is invoked from a subdirectory.
FIXTURE = (
    Path(__file__).resolve().parents[3] / "fixtures" / "claude_code" / "session-basic.jsonl"
)

SECRET_MARKERS = (
    "HOOK_STDOUT_MARKER",
    "SYSTEM_REMINDER_MARKER",
    "THINKING_MARKER",
    "STDOUT_SECRET_MARKER",
    "STDERR_SECRET_MARKER",
)


@pytest.fixture
def descriptor() -> SessionDescriptor:
    return SessionDescriptor(
        harness="claude-code",
        session_id="sess-1",
        source_location=str(FIXTURE),
        project_id_hint="-repo-main",
    )


@pytest.fixture
def records() -> list[dict]:
    return [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_maps_only_human_prompts_to_user_messages(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    user_texts = [
        activity.content
        for activity in session.activities
        if activity.activity_type == ActivityType.USER_MESSAGE
    ]
    assert user_texts == ["Add retry to the price fetcher"]


def test_drops_every_secret_marker(records, descriptor) -> None:
    """stdout, stderr, thinking, hook output, and system reminders never reach the model."""

    session = ClaudeCodeJsonlMapper().map(records, descriptor)
    serialized = session.model_dump_json()

    for marker in SECRET_MARKERS:
        assert marker not in serialized, f"{marker} leaked into AgentSession"


def test_maps_tool_calls_with_result_flags(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    tool_calls = {
        activity.tool_call_id: activity
        for activity in session.activities
        if activity.activity_type == ActivityType.TOOL_CALL
    }

    bash = tool_calls["toolu-1"]
    assert bash.tool_name == "Bash"
    assert bash.content == "pytest -q"
    assert bash.metadata["stderr_empty"] is True
    assert bash.metadata["interrupted"] is False

    edit = tool_calls["toolu-2"]
    assert edit.tool_name == "Edit"
    assert edit.content == "/repo/worktree-feat/src/fetch.py"
    assert edit.metadata["stderr_empty"] is False


def test_carries_the_tool_result_error_flag(records, descriptor) -> None:
    """`is_error` is the outcome Claude Code actually observes.

    It is not an exit code, but it is not an inference either: the harness
    records whether the tool call failed. Dropping it is what left every
    Claude Code verification command with no observable outcome.
    """

    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    tool_calls = {
        activity.tool_call_id: activity
        for activity in session.activities
        if activity.activity_type == ActivityType.TOOL_CALL
    }

    assert tool_calls["toolu-1"].metadata["tool_failed"] is False
    # The record carries no `is_error`, so nothing was observed and nothing is
    # claimed — distinct from observing a success.
    assert tool_calls["toolu-2"].metadata["tool_failed"] is None


def test_a_failed_tool_call_keeps_its_error_flag(records, descriptor) -> None:
    """A failed call records `toolUseResult` as a plain error string, not an object.

    The structured stderr flags are unavailable for those records, but the
    block's own `is_error` still is — and it is the stronger signal. Requiring a
    mapping before reading it dropped every observed failure on this harness.
    """

    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    failed = next(
        activity
        for activity in session.activities
        if activity.tool_call_id == "toolu-3"
    )
    assert failed.tool_name == "Bash"
    assert failed.metadata["tool_failed"] is True
    # A string result carries no stderr field; absent must not read as empty.
    assert failed.metadata["stderr_empty"] is False


def test_uses_last_cwd_and_ai_title(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.working_directory == "/repo/worktree-feat"
    assert session.title == "Retry for the price fetcher"
    assert session.harness == "claude-code"


def test_accumulates_incremental_token_usage(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.token_usage is not None
    assert session.token_usage.semantics is UsageSemantics.INCREMENTAL
    assert session.token_usage.input_tokens == 15
    assert session.token_usage.output_tokens == 300
    assert session.token_usage.cache_read_tokens == 3000
    assert session.token_usage.cache_write_tokens == 50


def test_attaches_per_model_usage_to_one_activity_per_record(records, descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    per_model = [
        (activity.metadata["model"], activity.metadata["usage"])
        for activity in session.activities
        if "usage" in activity.metadata
    ]
    assert per_model == [
        (
            "claude-opus-5",
            {
                "input_tokens": 10,
                "output_tokens": 200,
                "cache_read_tokens": 1000,
                "cache_write_tokens": 50,
            },
        ),
        (
            "claude-sonnet-5",
            {
                "input_tokens": 5,
                "output_tokens": 100,
                "cache_read_tokens": 2000,
                "cache_write_tokens": 0,
            },
        ),
    ]


def _usage(*, input_tokens: int, output_tokens: int) -> dict:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def _thinking_only(uuid: str, *, usage: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "model": "claude-opus-5",
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "THINKING_MARKER"}],
            "usage": usage,
        },
        "uuid": uuid,
        "timestamp": "2026-07-21T01:00:00.000Z",
        "cwd": "/repo/main",
    }


def _tool_call(uuid: str, *, usage: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "model": "claude-opus-5",
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"toolu-{uuid}",
                    "name": "Bash",
                    "input": {"command": "pytest -q"},
                }
            ],
            "usage": usage,
        },
        "uuid": uuid,
        "timestamp": "2026-07-21T01:00:01.000Z",
        "cwd": "/repo/main",
    }


def test_thinking_only_usage_merges_into_the_next_activity(descriptor) -> None:
    """Thinking is output tokens; a record that emits no activity must still count."""

    session = ClaudeCodeJsonlMapper().map(
        [
            _thinking_only("a-1", usage=_usage(input_tokens=3, output_tokens=700)),
            _tool_call("a-2", usage=_usage(input_tokens=10, output_tokens=200)),
        ],
        descriptor,
    )

    carriers = [
        activity for activity in session.activities if "usage" in activity.metadata
    ]
    assert len(carriers) == 1
    assert carriers[0].metadata["usage"] == {
        "input_tokens": 13,
        "output_tokens": 900,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    assert session.token_usage is not None
    assert session.token_usage.input_tokens == 13
    assert session.token_usage.output_tokens == 900


def test_trailing_thinking_only_usage_joins_the_last_activity(descriptor) -> None:
    """A transcript ending in thinking has no later activity to merge forward into."""

    session = ClaudeCodeJsonlMapper().map(
        [
            _tool_call("a-1", usage=_usage(input_tokens=10, output_tokens=200)),
            _thinking_only("a-2", usage=_usage(input_tokens=3, output_tokens=700)),
        ],
        descriptor,
    )

    carriers = [
        activity for activity in session.activities if "usage" in activity.metadata
    ]
    assert len(carriers) == 1
    assert carriers[0].metadata["usage"] == {
        "input_tokens": 13,
        "output_tokens": 900,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    assert session.token_usage is not None
    assert session.token_usage.output_tokens == 900


def test_a_write_calls_content_never_reaches_the_session(descriptor) -> None:
    """`_tool_content` must prefer the path key over serializing the whole input.

    A `Write` input holds `file_path` and `content`. The JSON fallback sorts keys,
    so `content` would come first and the file body would be what is retained.
    """

    session = ClaudeCodeJsonlMapper().map(
        [
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "Write",
                            "input": {
                                "file_path": "/repo/main/src/fetch.py",
                                "content": "WRITE_CONTENT_MARKER def fetch(): ...",
                            },
                        }
                    ],
                },
                "uuid": "a-1",
                "timestamp": "2026-07-21T01:00:00.000Z",
                "cwd": "/repo/main",
            }
        ],
        descriptor,
    )

    assert [activity.content for activity in session.activities] == [
        "/repo/main/src/fetch.py"
    ]
    assert "WRITE_CONTENT_MARKER" not in session.model_dump_json()


def test_every_activity_has_a_timestamp(records, descriptor) -> None:
    """ScanService warns about timestamp-less activities; Claude Code always has them."""

    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.activities
    assert all(activity.timestamp is not None for activity in session.activities)


def test_uses_the_last_git_branch_seen(records, descriptor) -> None:
    """The fixture's `gitBranch` changes from "main" to "feat/retry" to "feat";
    the last one written wins, matching the branch checked out when the
    transcript ended."""

    session = ClaudeCodeJsonlMapper().map(records, descriptor)

    assert session.branch == "feat"


def test_no_git_branch_key_yields_none(descriptor) -> None:
    session = ClaudeCodeJsonlMapper().map(
        [
            {
                "type": "user",
                "origin": {"kind": "human"},
                "message": {"role": "user", "content": "Add retry to the price fetcher"},
                "uuid": "u-1",
                "timestamp": "2026-07-21T01:00:00.000Z",
                "cwd": "/repo/main",
            }
        ],
        descriptor,
    )

    assert session.branch is None
