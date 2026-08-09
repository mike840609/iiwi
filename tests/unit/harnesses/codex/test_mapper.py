from datetime import datetime
from typing import Any

import pytest

from iiwi.harnesses.codex.mapper import CodexRolloutMapper
from iiwi.models.session import ActivityType, SessionDescriptor

DESCRIPTOR = SessionDescriptor(
    harness="codex",
    session_id="thread-1",
    source_location="/rollouts/thread-1.jsonl",
    title="Add retry",
    working_directory_hint="/worktrees/agent",
)


def _record(timestamp: str, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"timestamp": timestamp, "type": record_type, "payload": payload}


def _map(records: list[dict[str, Any]]):
    return CodexRolloutMapper().map(records, DESCRIPTOR)


def test_user_messages_become_user_activities() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "event_msg",
                {"type": "user_message", "message": "Add retry to the price fetcher"},
            )
        ]
    )

    assert [activity.activity_type for activity in session.activities] == [
        ActivityType.USER_MESSAGE
    ]
    assert session.activities[0].content == "Add retry to the price fetcher"
    assert session.activities[0].timestamp == datetime.fromisoformat(
        "2026-07-21T01:00:00+00:00"
    )


def test_raw_bash_output_user_message_is_dropped_but_a_real_one_survives() -> None:
    """A `<bash-stdout>` envelope is machine-injected output, not a human goal.

    An absence-only assertion would also pass against a mapper that dropped
    every user message, so this also asserts the adjacent real prompt still
    produces its goal.
    """

    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "event_msg",
                {
                    "type": "user_message",
                    "message": "<bash-stdout>\n/tmp/secret-output.txt\n</bash-stdout>",
                },
            ),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "user_message", "message": "Add retry to the price fetcher"},
            ),
        ]
    )

    user_messages = [
        activity
        for activity in session.activities
        if activity.activity_type == ActivityType.USER_MESSAGE
    ]
    assert [activity.content for activity in user_messages] == [
        "Add retry to the price fetcher"
    ]
    assert "<bash-stdout>" not in str(session.model_dump())


def test_attachment_envelope_user_message_is_dropped_but_a_real_one_survives() -> None:
    """`# Files mentioned by the user:` can embed a genuine request under a nested
    heading, but the whole envelope is dropped rather than parsed apart — see
    `_MACHINE_INJECTED_USER_MESSAGE_MARKERS`. The adjacent real prompt must still
    produce its goal, so this is not an absence-only assertion.
    """

    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "event_msg",
                {
                    "type": "user_message",
                    "message": (
                        "# Files mentioned by the user:\n"
                        "/tmp/notes.txt\n\n"
                        "## My request for Codex: please look at this"
                    ),
                },
            ),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "user_message", "message": "Review the retry helper"},
            ),
        ]
    )

    user_messages = [
        activity
        for activity in session.activities
        if activity.activity_type == ActivityType.USER_MESSAGE
    ]
    assert [activity.content for activity in user_messages] == [
        "Review the retry helper"
    ]
    assert "Files mentioned by the user" not in str(session.model_dump())


@pytest.mark.parametrize(
    "message",
    [
        "<bash-input>ls -la</bash-input>",
        "<bash-stdout>total 0</bash-stdout>",
        "<bash-stderr>permission denied</bash-stderr>",
        "<local-command-stdout>ok</local-command-stdout>",
        '<in-app-browser-context url="https://example.com">body</in-app-browser-context>',
        "<command-name>/compact</command-name>",
        "<task-notification>build finished</task-notification>",
        "# Files mentioned by the user:\n/tmp/a.txt",
        "This session is being continued from a previous conversation, summarized below",
    ],
)
def test_every_machine_injected_marker_produces_no_activity(message: str) -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "event_msg",
                {"type": "user_message", "message": message},
            )
        ]
    )

    assert session.activities == []


def test_agent_messages_are_not_filtered_by_the_same_markers() -> None:
    """The marker filter is specific to `user_message`; an `agent_message` that
    happens to start with the same text (e.g. quoting a bash block back) is
    still the assistant's own words and must survive.
    """

    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "event_msg",
                {"type": "agent_message", "message": "<bash-stdout>ok</bash-stdout>"},
            )
        ]
    )

    assert session.activities[0].activity_type == ActivityType.ASSISTANT_MESSAGE
    assert session.activities[0].content == "<bash-stdout>ok</bash-stdout>"


def test_agent_messages_become_assistant_activities() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "I implemented the retry."},
            )
        ]
    )

    assert session.activities[0].activity_type == ActivityType.ASSISTANT_MESSAGE
    assert session.activities[0].content == "I implemented the retry."


def test_exec_command_becomes_a_command_activity() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:02.000Z",
                "response_item",
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": '{"cmd": "pytest -q", "workdir": "/worktrees/agent"}',
                },
            )
        ]
    )

    activity = session.activities[0]
    assert activity.activity_type == ActivityType.COMMAND
    assert activity.content == "pytest -q"
    assert activity.tool_name == "exec_command"
    assert activity.tool_call_id == "call-1"


def test_no_outcome_signal_is_ever_recorded() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:02.000Z",
                "response_item",
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": '{"cmd": "pytest -q"}',
                },
            )
        ]
    )

    metadata = session.activities[0].metadata
    assert "exit_code" not in metadata
    assert "stderr_empty" not in metadata


def test_exec_javascript_never_reaches_activity_content() -> None:
    javascript = 'const r = await tools.exec_command({"cmd":"rm -rf /"}); text(r);'
    session = _map(
        [
            _record(
                "2026-07-21T01:00:03.000Z",
                "response_item",
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "call-2",
                    "input": javascript,
                },
            )
        ]
    )

    activity = session.activities[0]
    assert activity.activity_type == ActivityType.TOOL_CALL
    assert activity.content == ""
    assert activity.tool_name == "exec"
    assert javascript not in str(session.model_dump())


def test_applied_patches_become_one_file_change_per_path() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:04.000Z",
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "call_id": "call-3",
                    "success": True,
                    "changes": {
                        "/worktrees/agent/src/fetch.py": {
                            "type": "update",
                            "content": "SECRET_FILE_BODY",
                        },
                        "/worktrees/agent/tests/test_fetch.py": {
                            "type": "add",
                            "content": "SECRET_FILE_BODY",
                        },
                    },
                },
            )
        ]
    )

    paths = [activity.content for activity in session.activities]
    assert sorted(paths) == [
        "/worktrees/agent/src/fetch.py",
        "/worktrees/agent/tests/test_fetch.py",
    ]
    assert all(
        activity.activity_type == ActivityType.FILE_CHANGE
        for activity in session.activities
    )
    assert len({activity.activity_id for activity in session.activities}) == 2
    assert "SECRET_FILE_BODY" not in str(session.model_dump())


def test_failed_patches_produce_no_file_change() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:05.000Z",
                "event_msg",
                {
                    "type": "patch_apply_end",
                    "call_id": "call-4",
                    "success": False,
                    "changes": {"/worktrees/agent/src/fetch.py": {"type": "update"}},
                },
            )
        ]
    )

    assert session.activities == []


def test_working_directory_follows_the_last_turn_context() -> None:
    session = _map(
        [
            _record(
                "2026-07-21T01:00:00.000Z",
                "session_meta",
                {"session_id": "thread-1", "cwd": "/worktrees/agent"},
            ),
            _record(
                "2026-07-21T01:00:06.000Z",
                "turn_context",
                {"turn_id": "t-1", "cwd": "/worktrees/assets", "model": "gpt-5.6-sol"},
            ),
        ]
    )

    assert session.working_directory == "/worktrees/assets"


def test_session_identity_comes_from_the_descriptor() -> None:
    session = _map([])

    assert session.harness == "codex"
    assert session.session_id == "thread-1"
    assert session.title == "Add retry"
    assert session.working_directory == "/worktrees/agent"


def test_torn_records_do_not_stop_the_mapping() -> None:
    session = _map(
        [
            {"timestamp": "2026-07-21T01:00:00.000Z", "type": "event_msg"},
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "still mapped"},
            ),
        ]
    )

    assert [activity.content for activity in session.activities] == ["still mapped"]


def _token_count(timestamp: str, total: dict[str, int]) -> dict[str, Any]:
    return _record(
        timestamp,
        "event_msg",
        {"type": "token_count", "info": {"total_token_usage": total}},
    )


def _turn_context(timestamp: str, model: str) -> dict[str, Any]:
    return _record(timestamp, "turn_context", {"turn_id": "t", "model": model})


def test_usage_is_the_delta_of_the_running_total() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z",
                {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cached_input_tokens": 40,
                    "cache_write_input_tokens": 5,
                },
            ),
            _record(
                "2026-07-21T01:00:03.000Z",
                "event_msg",
                {"type": "agent_message", "message": "second"},
            ),
            _token_count(
                "2026-07-21T01:00:04.000Z",
                {
                    "input_tokens": 250,
                    "output_tokens": 30,
                    "cached_input_tokens": 90,
                    "cache_write_input_tokens": 5,
                },
            ),
        ]
    )

    first, second = session.activities
    assert first.metadata["usage"] == {
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_read_tokens": 40,
        "cache_write_tokens": 5,
    }
    # The second turn's delta, not its running total.
    assert second.metadata["usage"] == {
        "input_tokens": 150,
        "output_tokens": 20,
        "cache_read_tokens": 50,
    }
    assert session.token_usage.input_tokens == 250
    assert session.token_usage.output_tokens == 30
    assert session.token_usage.cache_read_tokens == 90
    assert session.token_usage.cache_write_tokens == 5


def test_a_reset_running_total_is_taken_at_face_value() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z", {"input_tokens": 500, "output_tokens": 50}
            ),
            _record(
                "2026-07-21T01:00:03.000Z",
                "event_msg",
                {"type": "agent_message", "message": "after compaction"},
            ),
            _token_count(
                "2026-07-21T01:00:04.000Z", {"input_tokens": 20, "output_tokens": 3}
            ),
        ]
    )

    assert session.activities[1].metadata["usage"] == {
        "input_tokens": 20,
        "output_tokens": 3,
    }


def test_usage_follows_the_model_the_turn_context_names() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "first"},
            ),
            _token_count("2026-07-21T01:00:02.000Z", {"output_tokens": 10}),
            _turn_context("2026-07-21T01:00:03.000Z", "gpt-5.6-terra"),
            _record(
                "2026-07-21T01:00:04.000Z",
                "event_msg",
                {"type": "agent_message", "message": "second"},
            ),
            _token_count("2026-07-21T01:00:05.000Z", {"output_tokens": 25}),
        ]
    )

    assert session.activities[0].metadata["model"] == "gpt-5.6-sol"
    assert session.activities[1].metadata["model"] == "gpt-5.6-terra"


def test_usage_with_no_activity_yet_joins_the_next_one() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _token_count("2026-07-21T01:00:01.000Z", {"output_tokens": 40}),
            _record(
                "2026-07-21T01:00:02.000Z",
                "event_msg",
                {"type": "agent_message", "message": "after the reasoning"},
            ),
            _token_count("2026-07-21T01:00:03.000Z", {"output_tokens": 60}),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 60}


def test_trailing_usage_joins_the_last_activity_of_that_model() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "answer"},
            ),
            _token_count("2026-07-21T01:00:02.000Z", {"output_tokens": 10}),
            # A trailing reasoning-only turn emits no activity of its own.
            _token_count("2026-07-21T01:00:03.000Z", {"output_tokens": 18}),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 18}


def test_reasoning_output_tokens_are_not_counted_twice() -> None:
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _record(
                "2026-07-21T01:00:01.000Z",
                "event_msg",
                {"type": "agent_message", "message": "answer"},
            ),
            _token_count(
                "2026-07-21T01:00:02.000Z",
                {"output_tokens": 100, "reasoning_output_tokens": 40},
            ),
        ]
    )

    assert session.activities[0].metadata["usage"] == {"output_tokens": 100}


def test_usage_stranded_by_a_model_switch_counts_in_the_total_but_not_the_table() -> None:
    # Model A's token_count arrives before it has any activity of its own, then
    # Codex switches to model B before A ever gets one. A's usage has nowhere
    # safe to land: attaching it to B's activity would misattribute it, so it
    # is dropped from the per-model table while still reaching the session
    # grand total. This pins that documented trade-off so a future change
    # cannot silently start misattributing it instead.
    session = _map(
        [
            _turn_context("2026-07-21T01:00:00.000Z", "gpt-5.6-sol"),
            _token_count("2026-07-21T01:00:01.000Z", {"output_tokens": 40}),
            _turn_context("2026-07-21T01:00:02.000Z", "gpt-5.6-terra"),
            _record(
                "2026-07-21T01:00:03.000Z",
                "event_msg",
                {"type": "agent_message", "message": "second model's answer"},
            ),
            _token_count("2026-07-21T01:00:04.000Z", {"output_tokens": 65}),
        ]
    )

    # The grand total still includes model A's 40 tokens (65 - 40 = 25 for B).
    assert session.token_usage.output_tokens == 65
    # But the only activity belongs to model B and carries only B's usage —
    # model A's tokens reach no activity's metadata at all.
    assert len(session.activities) == 1
    assert session.activities[0].metadata["model"] == "gpt-5.6-terra"
    assert session.activities[0].metadata["usage"] == {"output_tokens": 25}
