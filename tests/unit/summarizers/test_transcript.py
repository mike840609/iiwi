from datetime import datetime
from zoneinfo import ZoneInfo

from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
)
from iiwi.models.time_range import DateRange
from iiwi.summarizers.transcript import build_grouped_transcript

TZ = ZoneInfo("Asia/Taipei")


def _resolved(
    session_id: str,
    title: str,
    activities: list[SessionActivity],
    *,
    repository_id: str = "git:github.com/mike/agent-worklog",
    display_name: str = "Agent Worklog",
    working_directory: str | None = "/worktrees/agent-main",
    branch: str | None = "main",
) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=title,
            activities=activities,
        ),
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=display_name,
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            normalized_remote="github.com/mike/agent-worklog",
            branch=branch,
            working_directory=working_directory,
            resolution_method="remote",
        ),
    )


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )


def test_header_records_period_and_flags() -> None:
    sessions = {
        "repo": [
            _resolved(
                "s1",
                "Add retry",
                [
                    SessionActivity(
                        activity_id="a1",
                        activity_type=ActivityType.USER_MESSAGE,
                        timestamp=datetime(2026, 7, 21, 12, tzinfo=TZ),
                        content="Add retry",
                    )
                ],
            )
        ]
    }

    out = build_grouped_transcript(
        sessions_by_repository=sessions,
        period=_period(),
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        include_subagents=False,
        sanitized=True,
    )

    assert out.startswith("# Agent Worklog sessions grouped by repository\n")
    assert "- Period: 2026-07-20 to 2026-07-27" in out
    assert "Projects: 1" in out
    assert "Sessions: 1" in out
    assert "- Subagent sessions included: no" in out
    assert "- Sanitized exports: yes" in out


def test_groups_by_repository_with_display_name_heading() -> None:
    sessions = {
        "git:github.com/mike/agent-worklog": [
            _resolved(
                "s1",
                "Add retry",
                [
                    SessionActivity(
                        activity_id="a1",
                        activity_type=ActivityType.USER_MESSAGE,
                        timestamp=datetime(2026, 7, 21, 12, tzinfo=TZ),
                        content="Add retry",
                    )
                ],
            )
        ]
    }

    out = build_grouped_transcript(
        sessions_by_repository=sessions,
        period=_period(),
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        include_subagents=False,
        sanitized=False,
    )

    assert "## Project: Agent Worklog" in out
    assert "- Repository identity: `git:github.com/mike/agent-worklog`" in out
    assert "- Directory: `/worktrees/agent-main`" in out


def test_repositories_are_sorted_by_display_name() -> None:
    sessions = {
        "b": [
            _resolved(
                "s2",
                "Beta",
                [],
                repository_id="b/repo",
                display_name="Beta Repo",
            )
        ],
        "a": [
            _resolved(
                "s1",
                "Alpha",
                [],
                repository_id="a/repo",
                display_name="Alpha Repo",
            )
        ],
    }

    out = build_grouped_transcript(
        sessions_by_repository=sessions,
        period=_period(),
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        include_subagents=False,
        sanitized=False,
    )

    assert out.index("## Project: Alpha Repo") < out.index("## Project: Beta Repo")


def test_mentions_only_user_and_assistant_message_activities() -> None:
    sessions = {
        "repo": [
            _resolved(
                "s1",
                "Add retry",
                [
                    SessionActivity(
                        activity_id="u",
                        activity_type=ActivityType.USER_MESSAGE,
                        timestamp=datetime(2026, 7, 21, 12, tzinfo=TZ),
                        content="Add retry",
                    ),
                    SessionActivity(
                        activity_id="cmd",
                        activity_type=ActivityType.COMMAND,
                        timestamp=datetime(2026, 7, 21, 12, 1, tzinfo=TZ),
                        content="pytest -q",
                        metadata={"exit_code": 0},
                    ),
                    SessionActivity(
                        activity_id="ca",
                        activity_type=ActivityType.ASSISTANT_MESSAGE,
                        timestamp=datetime(2026, 7, 21, 12, 2, tzinfo=TZ),
                        content="Implemented.",
                    ),
                ],
            )
        ]
    }

    out = build_grouped_transcript(
        sessions_by_repository=sessions,
        period=_period(),
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        include_subagents=False,
        sanitized=False,
    )

    assert "**user:**" in out
    assert "Add retry" in out
    assert "**assistant:**" in out
    assert "Implemented." in out
    assert "pytest -q" not in out


def test_secrets_in_activities_are_redacted() -> None:
    sessions = {
        "repo": [
            _resolved(
                "s1",
                "Add retry",
                [
                    SessionActivity(
                        activity_id="u",
                        activity_type=ActivityType.USER_MESSAGE,
                        timestamp=datetime(2026, 7, 21, 12, tzinfo=TZ),
                        content="token=abc123def456ghi",
                    )
                ],
            )
        ]
    }

    out = build_grouped_transcript(
        sessions_by_repository=sessions,
        period=_period(),
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        include_subagents=False,
        sanitized=False,
    )

    assert "abc123def456ghi" not in out
    assert "[REDACTED]" in out


def test_both_flag_states_render() -> None:
    sessions = {
        "repo": [_resolved("s1", "Alpha", [], display_name="Alpha Repo")]
    }

    yes = build_grouped_transcript(
        sessions_by_repository=sessions,
        period=_period(),
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        include_subagents=True,
        sanitized=True,
    )

    assert "- Subagent sessions included: yes" in yes
    assert "- Sanitized exports: yes" in yes