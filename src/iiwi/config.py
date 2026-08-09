"""Application configuration models."""

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenCodeCliSettings(BaseModel):
    """OpenCode executable invocation settings."""

    executable: str = "opencode"
    timeout_seconds: float = 30.0
    run_timeout_seconds: float = 600.0
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
    """Top-level Agent Worklog settings."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_WORKLOG_",
        env_nested_delimiter="__",
        # The settings file is swept wholesale into the model by
        # `DotEnvSettingsSource` (unlike the environment source, which only reads
        # variable names it owns), so a foreign line — another tool's own
        # variable sharing the file — must not be a hard failure.
        extra="ignore",
    )

    harnesses: HarnessSettings = Field(default_factory=HarnessSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
