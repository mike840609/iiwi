"""Canonical harness session models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ActivityType(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    ERROR = "error"
    SYSTEM = "system"


class UsageSemantics(StrEnum):
    INCREMENTAL = "incremental"
    CUMULATIVE = "cumulative"
    UNKNOWN = "unknown"


class TokenUsage(BaseModel):
    semantics: UsageSemantics = UsageSemantics.UNKNOWN
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


class SessionDescriptor(BaseModel):
    harness: str
    session_id: str
    source_location: str | None = None
    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    working_directory_hint: str | None = None
    project_id_hint: str | None = None
    parent_session_id: str | None = None


class SessionActivity(BaseModel):
    activity_id: str
    activity_type: ActivityType
    timestamp: datetime | None = None
    content: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AgentSession(BaseModel):
    harness: str
    session_id: str
    parent_session_id: str | None = None
    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    working_directory: str | None = None
    branch: str | None = None
    project_id_hint: str | None = None
    activities: list[SessionActivity] = Field(default_factory=list)
    token_usage: TokenUsage | None = None
