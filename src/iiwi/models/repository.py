"""Canonical repository identity models."""

from enum import StrEnum

from pydantic import BaseModel

from iiwi.models.session import AgentSession


class RepositoryIdentityType(StrEnum):
    GIT_REMOTE = "git_remote"
    GIT_COMMON_DIR = "git_common_dir"
    HARNESS_PROJECT = "harness_project"
    PATH_FALLBACK = "path_fallback"
    UNKNOWN = "unknown"


class RepositoryIdentity(BaseModel):
    repository_id: str
    display_name: str
    identity_type: RepositoryIdentityType
    normalized_remote: str | None = None
    branch: str | None = None
    working_directory: str | None = None
    resolution_method: str


class ResolvedSession(BaseModel):
    session: AgentSession
    repository: RepositoryIdentity
