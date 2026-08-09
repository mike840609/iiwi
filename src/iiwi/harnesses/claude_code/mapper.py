"""Map Claude Code JSONL records into canonical session models."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from iiwi.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
    TokenUsage,
    UsageSemantics,
)

_TOOL_INPUT_MAX_LENGTH = 200
_TOOL_CONTENT_KEYS = ("command", "file_path", "path", "notebook_path")

# Canonical name -> Claude Code `message.usage` key.
_USAGE_FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_read_tokens": "cache_read_input_tokens",
    "cache_write_tokens": "cache_creation_input_tokens",
}


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _int_value(value: object) -> int | None:
    # bool is an int subclass; a JSON true would otherwise add 1 to a token total.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _human_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            block.get("text")
            for block in content
            if isinstance(block, Mapping) and block.get("type") == "text"
        ]
        return "\n".join(text for text in texts if isinstance(text, str) and text)
    return ""


def _is_human_prompt(record: Mapping[str, Any]) -> bool:
    """Accept only real human input.

    Claude Code also writes tool results, hook injections, and system reminders
    as `type: "user"` records. Treating those as user intent would put hook
    output and skill instructions into the report's goals.
    """

    if record.get("isMeta"):
        return False
    return _as_mapping(record.get("origin")).get("kind") == "human"


def _tool_content(tool_input: object) -> str:
    mapping = _as_mapping(tool_input)
    for key in _TOOL_CONTENT_KEYS:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if tool_input is None:
        return ""
    try:
        serialized = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    except TypeError:
        serialized = str(tool_input)
    return serialized[:_TOOL_INPUT_MAX_LENGTH]


def _record_usage(message: Mapping[str, Any]) -> tuple[str, dict[str, int]] | None:
    """Return one assistant record's model and token counts, or None if it has none."""

    usage = _as_mapping(message.get("usage"))
    model = message.get("model")
    if not usage or not isinstance(model, str) or not model:
        return None

    per_record: dict[str, int] = {}
    for canonical, source_key in _USAGE_FIELDS.items():
        value = _int_value(usage.get(source_key))
        if value is not None:
            per_record[canonical] = value
    return (model, per_record) if per_record else None


def _accumulate(target: dict[str, int], source: Mapping[str, int]) -> dict[str, int]:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value
    return target


def _last_git_branch(records: Iterable[Mapping[str, Any]]) -> str | None:
    """Return the last non-empty `gitBranch` seen, or None if the key never appears.

    `gitBranch` rides on most line types (hook attachments, user turns, assistant
    turns), not only the `user`/`assistant` records the rest of the mapper reads,
    so this scans every record rather than piggybacking on the main loop.
    """

    branch: str | None = None
    for record in records:
        value = record.get("gitBranch")
        if isinstance(value, str) and value:
            branch = value
    return branch


def _tool_result_flags(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, object]]:
    """Index derived booleans by `tool_use_id`.

    Only booleans cross this boundary. `stdout` and `stderr` hold whole file
    contents, environment dumps, and hook output, and Claude Code has no
    `--sanitize` upstream, so they never enter AgentSession.

    `tool_failed` comes from the block's own `is_error`, not from the sibling
    `toolUseResult`, and is `None` when the record carries no such field.
    Claude Code reports no exit code, which is why nothing here is called one,
    but this flag is still an outcome it observed rather than one we inferred.

    A *failed* call records `toolUseResult` as a plain error string rather than
    an object, so the stderr flags simply do not exist for it. That must not
    gate `tool_failed`: requiring a mapping first is what silently dropped every
    observed failure on this harness.
    """

    flags: dict[str, dict[str, object]] = {}
    for record in records:
        content = _as_mapping(record.get("message")).get("content")
        if not isinstance(content, list):
            continue
        result = _as_mapping(record.get("toolUseResult"))
        stderr = result.get("stderr")
        derived = {
            # No structured result means stderr was never observed, and absent
            # must not read as empty — that is what the heuristic treats as clean.
            "stderr_empty": bool(result)
            and not (stderr.strip() if isinstance(stderr, str) else ""),
            "interrupted": result.get("interrupted") is True,
        }
        for block in content:
            if not isinstance(block, Mapping) or block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id")
            if isinstance(tool_use_id, str) and tool_use_id:
                is_error = block.get("is_error")
                flags[tool_use_id] = {
                    **derived,
                    "tool_failed": is_error if isinstance(is_error, bool) else None,
                }
    return flags


class ClaudeCodeJsonlMapper:
    """Convert Claude Code JSONL records to an AgentSession, dropping raw output."""

    def map(
        self,
        records: list[Mapping[str, Any]],
        descriptor: SessionDescriptor,
    ) -> AgentSession:
        result_flags = _tool_result_flags(records)

        activities: list[SessionActivity] = []
        totals: dict[str, int] = {}
        # Usage must ride on an activity: `filter_session_to_period` narrows the
        # activity list, and the usage table must cover only the report period. A
        # thinking-only record emits no activity, so its usage is held here and
        # merged into the next activity from the same model — 1,171 of 4,227
        # assistant records are shaped that way, carrying 25% of all output tokens.
        pending_usage: dict[str, dict[str, int]] = {}
        attached_usage: dict[str, dict[str, int]] = {}
        title: str | None = None
        working_directory: str | None = None
        first_timestamp: datetime | None = None
        last_timestamp: datetime | None = None

        for record_index, record in enumerate(records):
            record_type = record.get("type")
            if record_type == "ai-title":
                ai_title = record.get("aiTitle")
                if isinstance(ai_title, str) and ai_title:
                    title = ai_title
                continue
            if record_type not in {"user", "assistant"}:
                continue

            timestamp = _parse_timestamp(record.get("timestamp"))
            if timestamp is not None:
                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp
            cwd = record.get("cwd")
            if isinstance(cwd, str) and cwd:
                working_directory = cwd

            uuid = record.get("uuid")
            record_id = (
                uuid
                if isinstance(uuid, str) and uuid
                else f"{descriptor.session_id}:record:{record_index}"
            )
            message = _as_mapping(record.get("message"))

            if record_type == "user":
                if not _is_human_prompt(record):
                    continue
                text = _human_text(message.get("content"))
                if not text:
                    continue
                activities.append(
                    SessionActivity(
                        activity_id=f"{record_id}:0",
                        activity_type=ActivityType.USER_MESSAGE,
                        timestamp=timestamp,
                        content=text,
                    )
                )
                continue

            emitted = self._assistant_activities(
                message=message,
                record_id=record_id,
                timestamp=timestamp,
                result_flags=result_flags,
            )
            activities.extend(emitted)

            record_usage = _record_usage(message)
            if record_usage is None:
                continue
            model, per_record = record_usage
            _accumulate(totals, per_record)
            if emitted:
                # One activity per record carries the usage, so a multi-block
                # record is not counted twice.
                usage = _accumulate(pending_usage.pop(model, {}), per_record)
                emitted[0].metadata["model"] = model
                emitted[0].metadata["usage"] = usage
                attached_usage[model] = usage
            else:
                _accumulate(pending_usage.setdefault(model, {}), per_record)

        # Usage still held when the transcript ends — a session whose last records
        # are thinking-only — joins the last activity that carried the same model.
        # A model that emitted no activity anywhere in the session still counts in
        # `token_usage`; it cannot reach the per-model table, which reads activities.
        for model, leftover in pending_usage.items():
            attached = attached_usage.get(model)
            if attached is not None:
                _accumulate(attached, leftover)

        return AgentSession(
            harness="claude-code",
            session_id=descriptor.session_id,
            parent_session_id=descriptor.parent_session_id,
            title=title or descriptor.title,
            created_at=first_timestamp or descriptor.created_at,
            updated_at=last_timestamp or descriptor.updated_at,
            working_directory=working_directory or descriptor.working_directory_hint,
            branch=_last_git_branch(records),
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

    def _assistant_activities(
        self,
        *,
        message: Mapping[str, Any],
        record_id: str,
        timestamp: datetime | None,
        result_flags: dict[str, dict[str, object]],
    ) -> list[SessionActivity]:
        content = message.get("content")
        if not isinstance(content, list):
            return []

        activities: list[SessionActivity] = []
        for index, raw_block in enumerate(content):
            if not isinstance(raw_block, Mapping):
                continue
            block_type = raw_block.get("type")
            activity_id = f"{record_id}:{index}"

            if block_type == "text":
                text = raw_block.get("text")
                if not isinstance(text, str) or not text:
                    continue
                activities.append(
                    SessionActivity(
                        activity_id=activity_id,
                        activity_type=ActivityType.ASSISTANT_MESSAGE,
                        timestamp=timestamp,
                        content=text,
                    )
                )
            elif block_type == "tool_use":
                tool_name = raw_block.get("name")
                tool_call_id = raw_block.get("id")
                metadata: dict[str, object] = {}
                if isinstance(tool_call_id, str):
                    metadata.update(result_flags.get(tool_call_id, {}))
                activities.append(
                    SessionActivity(
                        activity_id=activity_id,
                        activity_type=ActivityType.TOOL_CALL,
                        timestamp=timestamp,
                        content=_tool_content(raw_block.get("input")),
                        tool_name=tool_name if isinstance(tool_name, str) else None,
                        tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
                        metadata=metadata,
                    )
                )
            # `thinking` blocks are dropped: internal reasoning is not work evidence.
            # Their tokens are not: the record's usage is still accounted for in
            # `map`, which is why thinking-only records emit nothing but count.
        return activities
