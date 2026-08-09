"""Evidence models with provenance."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class EvidenceConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceStatus(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    text: str
    source_activity_ids: list[str]
    confidence: EvidenceConfidence
    extraction_method: str
    status: EvidenceStatus = EvidenceStatus.UNKNOWN

    @field_validator("source_activity_ids")
    @classmethod
    def require_source_activity_ids(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("evidence must reference at least one source activity")
        return value


class SessionEvidence(BaseModel):
    session_id: str
    repository_id: str
    title: str | None = None
    working_directory: str | None = None
    goals: list[EvidenceItem] = Field(default_factory=list)
    commands: list[EvidenceItem] = Field(default_factory=list)
    files_changed: list[EvidenceItem] = Field(default_factory=list)
    errors: list[EvidenceItem] = Field(default_factory=list)
    outcomes: list[EvidenceItem] = Field(default_factory=list)


class RepositoryEvidence(BaseModel):
    repository_id: str
    display_name: str
    normalized_remote: str | None = None
    branches: list[str] = Field(default_factory=list)
    sessions: list[SessionEvidence] = Field(default_factory=list)
    child_session_count: int = 0
