"""Map Codex rollout JSONL records into canonical session models."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from iiwi.harnesses.codex.rollout_catalog import parse_timestamp
from iiwi.harnesses.codex.thread_catalog import HARNESS_NAME
from iiwi.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
    TokenUsage,
    UsageSemantics,
)

# Codex writes several kinds of machine-generated payload into the transcript
# as `event_msg/user_message` records — indistinguishable by `type` from a
# prompt the operator actually typed. Each entry below opens one of them, so
# a message that starts with it is not a human goal:
#   - `<bash-input>`, `<bash-stdout>`, `<bash-stderr>`: an attached shell
#     command and its raw output, injected alongside a real message rather
#     than typed by a human.
#   - `<local-command-stdout>`: output from a local slash command.
#   - `<in-app-browser-context`: an envelope carrying page/browser state
#     (note: no closing bracket — the tag carries attributes).
#   - `<command-name>`: a slash-command invocation record.
#   - `<task-notification>`: a background-task completion notice.
#   - `# Files mentioned by the user:`: an attachment envelope. It can embed
#     a genuine request under a nested `## My request for Codex: …` heading,
#     but the whole envelope is dropped rather than parsed apart — this
#     project's stance is to lose a goal rather than mis-attribute one out of
#     an undocumented format.
#   - `This session is being continued from a previous conversation`: a
#     resume/compaction summary Codex injects, not an operator prompt.
_MACHINE_INJECTED_USER_MESSAGE_MARKERS = (
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<local-command-stdout>",
    "<in-app-browser-context",
    "<command-name>",
    "<task-notification>",
    "# Files mentioned by the user:",
    "This session is being continued from a previous conversation",
)

# The one Codex tool whose arguments name a command as a field. `exec` is a
# general JavaScript sandbox — its input calls MCP tools, drives a browser, or
# loops over `tools.exec_command` — so it is not a command source. A strict parse
# for a single wrapped `exec_command` call matched 0 of 4,963 measured `exec`
# calls, which is why none is attempted.
_COMMAND_TOOL = "exec_command"

_TOOL_CALL_TYPES = frozenset({"function_call", "custom_tool_call"})

# Canonical name -> Codex `total_token_usage` key. `reasoning_output_tokens` is
# deliberately absent: it is a subset of `output_tokens`, so counting it would
# double the reasoning tokens in every row of the usage table.
_USAGE_FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_tokens": "cached_input_tokens",
    "cache_write_tokens": "cache_write_input_tokens",
}


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _tool_arguments(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a `function_call`'s parsed arguments.

    A `custom_tool_call` carries free-form `input` instead, which is never parsed
    — see `_COMMAND_TOOL`.
    """

    raw = payload.get("arguments")
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _int_value(value: object) -> int | None:
    # bool is an int subclass; a JSON true would otherwise add 1 to a token total.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _accumulate(target: dict[str, int], source: Mapping[str, int]) -> dict[str, int]:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value
    return target


def _usage_delta(
    total: Mapping[str, Any],
    previous: dict[str, int],
) -> dict[str, int]:
    """Return one turn's usage from Codex's running totals.

    Summing `last_token_usage` instead over-counts: Codex emits some
    `token_count` events more than once, which on one measured session inflated
    the sum to 2,635,327 against Codex's own total of 2,540,568. Differencing the
    running total reproduces that total exactly, and still attributes the tokens
    to a point in the session so period filtering can narrow them.

    A total that has gone backwards means Codex reset it — a fork or a context
    compaction — so the raw value is taken as that turn's usage.
    """

    values: dict[str, int] = {}
    reset = False
    for canonical, source_key in _USAGE_FIELDS.items():
        value = _int_value(total.get(source_key))
        if value is None:
            continue
        values[canonical] = value
        if value < previous.get(canonical, 0):
            reset = True

    delta = {
        canonical: value if reset else value - previous.get(canonical, 0)
        for canonical, value in values.items()
    }
    previous.update(values)
    return {canonical: value for canonical, value in delta.items() if value}


class CodexRolloutMapper:
    """Convert Codex rollout records to an AgentSession, dropping raw output.

    Two things never leave this mapper: the JavaScript an `exec` call carries,
    and the file bodies a `patch_apply_end` record carries in
    `changes[path].content`. Codex has no `--sanitize` upstream, and the
    300-character evidence cap downstream is a backstop, not a reason to carry
    them this far.

    A third thing never becomes a goal: an `event_msg/user_message` whose text
    opens with one of `_MACHINE_INJECTED_USER_MESSAGE_MARKERS`. Codex uses that
    same record type for machine-injected payloads — attached shell output,
    browser context, resume summaries — and nothing upstream marks them as
    non-human the way Claude Code's `origin.kind` does, so the mapper is the
    only place that can tell them apart from a real prompt.
    """

    def map(
        self,
        records: list[Mapping[str, Any]],
        descriptor: SessionDescriptor,
    ) -> AgentSession:
        activities: list[SessionActivity] = []
        working_directory: str | None = None
        first_timestamp: datetime | None = None
        last_timestamp: datetime | None = None
        totals: dict[str, int] = {}
        previous_total: dict[str, int] = {}
        pending_usage: dict[str, dict[str, int]] = {}
        attached_usage: dict[str, dict[str, int]] = {}
        model: str | None = None

        for index, record in enumerate(records):
            payload = _as_mapping(record.get("payload"))
            if not payload:
                continue
            record_type = record.get("type")
            timestamp = parse_timestamp(record.get("timestamp"))
            if timestamp is not None:
                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp

            if record_type in {"session_meta", "turn_context"}:
                # A session can move between worktrees; the last one is where the
                # work ended, which is what the repository resolver should see.
                working_directory = _text(payload.get("cwd")) or working_directory
                # The model changes mid-session — one measured session alternates
                # between two — so the turn's own context beats the thread's.
                model = _text(payload.get("model")) or model
                continue

            if record_type == "event_msg":
                if payload.get("type") == "token_count":
                    delta = _usage_delta(
                        _as_mapping(_as_mapping(payload.get("info")).get(
                            "total_token_usage"
                        )),
                        previous_total,
                    )
                    if delta:
                        _accumulate(totals, delta)
                        self._attach_usage(
                            delta=delta,
                            model=model,
                            activities=activities,
                            pending_usage=pending_usage,
                            attached_usage=attached_usage,
                        )
                    continue
                activities.extend(
                    self._event_activities(
                        payload=payload,
                        record_index=index,
                        timestamp=timestamp,
                    )
                )
                continue

            if record_type == "response_item" and payload.get("type") in _TOOL_CALL_TYPES:
                activity = self._tool_activity(
                    payload=payload,
                    record_index=index,
                    timestamp=timestamp,
                )
                if activity is not None:
                    activities.append(activity)

        # Usage still held when the rollout ends — a session whose last turns
        # under a given model were reasoning-only — joins the last activity
        # that carried the same model, so the table's total matches the
        # session's own total.
        #
        # A model can also be stranded rather than merely trailing: its
        # `token_count` arrives while `activities` is still empty, then Codex
        # switches to a different model before that first model ever gets an
        # activity of its own. `attached_usage` has no entry for it, so
        # `attached` is None and the branch below is skipped — its tokens
        # already reached `totals` above, so `AgentSession.token_usage` still
        # counts them, but no `activity.metadata["usage"]` ever will, so the
        # per-model table omits them. This mirrors the same trade-off
        # `claude_code/mapper.py`'s drain loop documents: attaching a
        # stranded model's tokens to an activity that ran under a different
        # model would misattribute them, which is worse than the table
        # under-reporting that model, so this loop leaves them out rather
        # than guessing an owner.
        for pending_model, leftover in pending_usage.items():
            attached = attached_usage.get(pending_model)
            if attached is not None:
                _accumulate(attached, leftover)

        return AgentSession(
            harness=HARNESS_NAME,
            session_id=descriptor.session_id,
            parent_session_id=descriptor.parent_session_id,
            title=descriptor.title,
            created_at=first_timestamp or descriptor.created_at,
            updated_at=last_timestamp or descriptor.updated_at,
            working_directory=working_directory or descriptor.working_directory_hint,
            project_id_hint=descriptor.project_id_hint,
            activities=activities,
            token_usage=TokenUsage(
                semantics=UsageSemantics.INCREMENTAL,
                input_tokens=totals.get("input_tokens"),
                output_tokens=totals.get("output_tokens"),
                cache_read_tokens=totals.get("cache_read_tokens"),
                cache_write_tokens=totals.get("cache_write_tokens"),
            ),
        )

    @staticmethod
    def _attach_usage(
        *,
        delta: dict[str, int],
        model: str | None,
        activities: list[SessionActivity],
        pending_usage: dict[str, dict[str, int]],
        attached_usage: dict[str, dict[str, int]],
    ) -> None:
        """Hang one turn's usage on an activity so period filtering can see it.

        A model that has not been named yet — usage before the first
        `turn_context` — still reaches `AgentSession.token_usage`, but cannot
        reach the per-model table, which reads activities.
        """

        if model is None:
            return
        carrier = activities[-1] if activities else None
        if carrier is not None and "usage" not in carrier.metadata:
            usage = _accumulate(pending_usage.pop(model, {}), delta)
            carrier.metadata["model"] = model
            carrier.metadata["usage"] = usage
            attached_usage[model] = usage
            return
        _accumulate(pending_usage.setdefault(model, {}), delta)

    def _event_activities(
        self,
        *,
        payload: Mapping[str, Any],
        record_index: int,
        timestamp: datetime | None,
    ) -> list[SessionActivity]:
        event_type = payload.get("type")

        if event_type in {"user_message", "agent_message"}:
            message = _text(payload.get("message"))
            if message is None:
                return []
            if event_type == "user_message" and message.startswith(
                _MACHINE_INJECTED_USER_MESSAGE_MARKERS
            ):
                return []
            activity_type = (
                ActivityType.USER_MESSAGE
                if event_type == "user_message"
                else ActivityType.ASSISTANT_MESSAGE
            )
            return [
                SessionActivity(
                    activity_id=str(record_index),
                    activity_type=activity_type,
                    timestamp=timestamp,
                    content=message,
                )
            ]

        if event_type == "patch_apply_end":
            # `success` is the only structured outcome signal Codex records.
            # A failed patch changed nothing, so listing its paths under Key
            # Files would be wrong.
            if payload.get("success") is not True:
                return []
            changes = _as_mapping(payload.get("changes"))
            call_id = _text(payload.get("call_id")) or str(record_index)
            activities: list[SessionActivity] = []
            # Only the keys. Each value holds a unified diff or the whole file
            # body, plus a rename's destination path in `move_path`.
            for offset, path in enumerate(changes):
                if not isinstance(path, str) or not path.strip():
                    continue
                activities.append(
                    SessionActivity(
                        activity_id=f"{call_id}:{offset}",
                        activity_type=ActivityType.FILE_CHANGE,
                        timestamp=timestamp,
                        content=path.strip(),
                    )
                )
            return activities

        return []

    def _tool_activity(
        self,
        *,
        payload: Mapping[str, Any],
        record_index: int,
        timestamp: datetime | None,
    ) -> SessionActivity | None:
        name = _text(payload.get("name"))
        call_id = _text(payload.get("call_id")) or str(record_index)

        if name == _COMMAND_TOOL:
            arguments = _tool_arguments(payload)
            command = _text(arguments.get("cmd"))
            if command is None:
                return None
            # No `exit_code`, no `tool_failed`, no `stderr_empty` — the three
            # signals `extraction/pipeline.py` reads to decide an outcome. Codex
            # records exit codes only inside free-form output text, in at least
            # three formats, and a regex over that would fail silently the day
            # Codex changes it. With none of the three set, `observed_command_failure`
            # returns None and the stderr heuristic declines, so a Codex command
            # is reported as what it was, never as passed or failed. Adding any
            # of the three here is what would break that.
            return SessionActivity(
                activity_id=call_id,
                activity_type=ActivityType.COMMAND,
                timestamp=timestamp,
                content=command,
                tool_name=name,
                tool_call_id=call_id,
            )

        # Every other tool, `exec` included, is recorded with empty content. The
        # activity still exists because Task 6's usage rides on activities, and a
        # turn made only of tool calls would otherwise vanish from the usage table.
        return SessionActivity(
            activity_id=call_id,
            activity_type=ActivityType.TOOL_CALL,
            timestamp=timestamp,
            content="",
            tool_name=name,
            tool_call_id=call_id,
        )
