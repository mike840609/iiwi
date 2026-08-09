"""Report output models."""

from datetime import datetime

from pydantic import BaseModel, Field

from iiwi.models.time_range import DateRange


class SessionRef(BaseModel):
    session_id: str
    title: str | None = None


class RepositorySummary(BaseModel):
    repository_id: str
    display_name: str
    normalized_remote: str | None = None
    summary: str = ""
    completed: list[str] = Field(default_factory=list)
    problems_resolved: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    directories: list[str] = Field(default_factory=list)
    sessions: list[SessionRef] = Field(default_factory=list)
    session_count: int = 0
    child_session_count: int = 0
    branches: list[str] = Field(default_factory=list)


class WorklogReport(BaseModel):
    schema_version: str = "1"
    generated_at: datetime
    period: DateRange
    repositories: list[RepositorySummary]
    narrative_text: str | None = None
    usage_text: str | None = None
    usage_days: int | None = None
    warnings: list[str] = Field(default_factory=list)
