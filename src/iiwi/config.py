"""Application configuration models."""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from iiwi.models.report_options import ReportType

# ponytail: one `opencode run`, one payload, so the ceiling is what a single
# model call can still answer with strict JSON. Measured against a real
# OpenCode store: 20 KB (10 sessions) synthesized, 110 KB (25) returned no
# output, 1.1 MB (162) came back as prose. Batching the synthesis across
# several runs and merging the outcomes is what lifts this, not a bigger number.
DEFAULT_QUICK_REVIEW_MAX_EVIDENCE_BYTES = 40000


DEFAULT_NARRATOR_TIMEOUT_SECONDS = 600.0


class NarratorSettings(BaseModel):
    """How iiwi turns a transcript into prose.

    Every field's empty value means "unset", which is what lets the provider be
    derived from the selected harness instead of configured up front.
    """

    provider: str = ""
    executable: str = ""
    model: str = ""
    # `None` rather than the default value: the resolution order has to tell an
    # unset timeout from one a user deliberately set to the same number, and
    # `gt=0` cannot express "absent".
    timeout_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class OpenCodeCliSettings(BaseModel):
    """OpenCode executable invocation settings."""

    executable: str = "opencode"
    # A timeout must be a finite positive number: nan/inf would crash the int()
    # conversion at run time, and a zero or negative timeout would fire
    # immediately or never.
    timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    # Deprecated: superseded by narrator.timeout_seconds. Kept as a plain field
    # (not Field(deprecated=...)) because pydantic 2.13 fires a
    # DeprecationWarning on every attribute *read*, and a later task reads this
    # as a fallback on every run; cli._load_settings prints the migration note
    # on stderr instead.
    run_timeout_seconds: float = Field(default=600.0, gt=0, allow_inf_nan=False)
    # Deprecated: superseded by narrator.model. See run_timeout_seconds above.
    model: str = ""
    sanitize: bool = False


class OpenCodeSettings(BaseModel):
    """OpenCode harness settings."""

    # `false` makes `--harness opencode` fail with a configuration error.
    enabled: bool = True
    source: str = "cli"
    cli: OpenCodeCliSettings = Field(default_factory=OpenCodeCliSettings)


class ClaudeCodeSettings(BaseModel):
    """Claude Code harness settings."""

    # `false` makes `--harness claude-code` fail with a configuration error, so an
    # operator can forbid reading `~/.claude/projects` on a whole machine.
    enabled: bool = True
    projects_directory: Path = Field(
        default_factory=lambda: Path.home() / ".claude" / "projects"
    )


class CodexSettings(BaseModel):
    """Codex harness settings."""

    # `false` makes `--harness codex` fail with a configuration error, so an
    # operator can forbid reading `~/.codex` on a whole machine.
    enabled: bool = True
    # One setting, not three: the state database, `sessions/` and
    # `archived_sessions/` are all fixed positions under this directory.
    home_directory: Path = Field(default_factory=lambda: Path.home() / ".codex")


class HarnessSettings(BaseModel):
    """Configured coding-agent harnesses."""

    opencode: OpenCodeSettings = Field(default_factory=OpenCodeSettings)
    claude_code: ClaudeCodeSettings = Field(default_factory=ClaudeCodeSettings)
    codex: CodexSettings = Field(default_factory=CodexSettings)


class ReportSettings(BaseModel):
    """Report defaults."""

    timezone: str = "Asia/Taipei"
    output_directory: Path = Path("reports")
    # A comma-separated string, not `list[str]`: a list cannot be validated or
    # round-tripped by `config set`, which writes and rereads strings.
    exclude_repositories: str = ""
    quick_review_report_type: ReportType = ReportType.MANAGER
    # How much extracted evidence Quick Review may hand to one `opencode run`.
    # Sessions past the budget are not sent at all; they stay ungrouped
    # candidates rather than disappearing. The floor is one session's payload:
    # a compact session measures roughly 580 bytes, so a budget under a
    # thousand cannot carry even one of them plus the index envelope, and every
    # selection is refused as over budget — which reads as Quick Review being
    # broken rather than as this setting being wrong.
    quick_review_max_evidence_bytes: int = Field(
        default=DEFAULT_QUICK_REVIEW_MAX_EVIDENCE_BYTES, ge=1000
    )

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value

    def excluded_repository_ids(self) -> tuple[str, ...]:
        """Normalise the string setting into the repository ids it names.

        The format is this setting's own, so the parsing lives here rather
        than at the call sites that filter on the result.
        """

        return tuple(
            entry.strip()
            for entry in self.exclude_repositories.split(",")
            if entry.strip()
        )


class AppSettings(BaseSettings):
    """Top-level Iiwi settings."""

    model_config = SettingsConfigDict(
        env_prefix="IIWI_",
        env_nested_delimiter="__",
        # The settings file is swept wholesale into the model by
        # `DotEnvSettingsSource` (unlike the environment source, which only reads
        # variable names it owns), so a foreign line — another tool's own
        # variable sharing the file — must not be a hard failure.
        extra="ignore",
    )

    harnesses: HarnessSettings = Field(default_factory=HarnessSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
    narrator: NarratorSettings = Field(default_factory=NarratorSettings)
