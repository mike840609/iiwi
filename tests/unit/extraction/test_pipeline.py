from datetime import UTC, datetime

from iiwi.extraction.pipeline import EVIDENCE_TEXT_MAX_LENGTH, extract_evidence
from iiwi.models.evidence import EvidenceConfidence, EvidenceStatus
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity


def resolved(*activities: SessionActivity) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="s1",
            activities=list(activities),
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            normalized_remote="github.com/mike/agent-worklog",
            resolution_method="git_origin_remote",
        ),
    )


def test_user_request_becomes_goal_with_provenance() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="message-1:part-0",
                activity_type=ActivityType.USER_MESSAGE,
                content="Add weekly report generation",
            )
        )
    )

    goal = evidence.goals[0]
    assert goal.text == "Add weekly report generation"
    assert goal.source_activity_ids == ["message-1:part-0"]
    assert goal.extraction_method == "user_message"


def test_successful_test_command_becomes_completed_outcome() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="tool-1",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="bash",
                content="pytest -q",
                metadata={"exit_code": 0},
            )
        )
    )

    assert evidence.outcomes[0].status == "completed"
    assert evidence.outcomes[0].confidence == "high"
    assert evidence.outcomes[0].source_activity_ids == ["tool-1"]


def test_nonzero_command_becomes_error_not_completed_outcome() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="tool-1",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="bash",
                content="pytest -q",
                metadata={"exit_code": 1},
            )
        )
    )

    assert evidence.errors[0].text == "pytest -q"
    assert evidence.outcomes == []


def test_assistant_completion_claim_is_low_confidence_unknown() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="message-2:part-0",
                activity_type=ActivityType.ASSISTANT_MESSAGE,
                content="Implemented the feature successfully.",
            )
        )
    )

    assert evidence.outcomes[0].status == "unknown"
    assert evidence.outcomes[0].confidence == "low"


def test_long_command_text_is_capped_and_marked_as_cut() -> None:
    """A heredoc body in `input.command` must not reach the report or an LLM."""

    heredoc = (
        "cat > report.md <<'EOF' "
        + "AUTH_BYPASS_WRITEUP secret finding paragraph. " * 60
        + "EOF"
    )
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="tool-1",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="bash",
                content=heredoc,
            )
        )
    )

    command = evidence.commands[0]
    assert len(heredoc) > 1000
    assert len(command.text) == EVIDENCE_TEXT_MAX_LENGTH
    assert command.text.endswith("…")
    assert command.text.startswith("cat > report.md <<'EOF'")


def test_short_command_text_is_left_exactly_as_recorded() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="tool-1",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="bash",
                content="pytest -q",
            )
        )
    )

    assert evidence.commands[0].text == "pytest -q"


def test_file_tool_without_a_path_key_reports_no_key_file() -> None:
    """A `Write`-shaped call missing `file_path` must not render its content as a path."""

    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="tool-1",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="write",
                content='{"content": "SECRET_FILE_BODY def main(): ...", "mode": "w"}',
            )
        )
    )

    assert evidence.files_changed == []


def test_file_tool_content_fallback_still_accepts_a_bare_path() -> None:
    evidence = extract_evidence(
        resolved(
            SessionActivity(
                activity_id="tool-1",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="write",
                content="src/iiwi/cli.py",
            )
        )
    )

    assert [item.text for item in evidence.files_changed] == [
        "src/iiwi/cli.py"
    ]


def test_extraction_carries_session_title_and_directory() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="s1",
            title="Fix the exporter",
            working_directory="/repos/agent-worklog",
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.title == "Fix the exporter"
    assert evidence.working_directory == "/repos/agent-worklog"


def command(content: str, **metadata: object) -> SessionActivity:
    return SessionActivity(
        activity_id="a-1",
        activity_type=ActivityType.TOOL_CALL,
        timestamp=datetime(2026, 7, 21, tzinfo=UTC),
        content=content,
        tool_name="Bash",
        metadata=metadata,
    )


def test_an_observed_tool_success_completes_a_verification_command() -> None:
    """Claude Code records no exit code, but it does record whether a tool failed.

    That flag is observed, not inferred, so it carries the same weight as
    OpenCode's exit code and yields the same COMPLETED outcome.
    """

    evidence = extract_evidence(
        resolved(command("pytest -q", tool_failed=False, stderr_empty=True))
    )

    assert len(evidence.outcomes) == 1
    outcome = evidence.outcomes[0]
    assert outcome.text == "Verification passed: pytest -q"
    assert outcome.confidence is EvidenceConfidence.HIGH
    assert outcome.status is EvidenceStatus.COMPLETED
    assert evidence.errors == []


def test_an_observed_tool_failure_is_recorded_as_blocked() -> None:
    evidence = extract_evidence(
        resolved(command("pytest -q", tool_failed=True, stderr_empty=False))
    )

    assert len(evidence.errors) == 1
    assert evidence.errors[0].status is EvidenceStatus.BLOCKED
    assert evidence.errors[0].confidence is EvidenceConfidence.HIGH
    # A failure is never also an outcome.
    assert evidence.outcomes == []


def test_an_observed_success_on_a_non_verification_command_claims_nothing() -> None:
    """`git status` succeeding says nothing about whether the work is done."""

    evidence = extract_evidence(
        resolved(command("git status", tool_failed=False, stderr_empty=True))
    )

    assert evidence.outcomes == []
    assert evidence.errors == []


def test_an_exit_code_still_wins_over_the_tool_error_flag() -> None:
    """OpenCode reports a real exit code; it is the more precise signal."""

    evidence = extract_evidence(
        resolved(command("pytest -q", exit_code=1, tool_failed=False))
    )

    assert len(evidence.errors) == 1
    assert evidence.errors[0].status is EvidenceStatus.BLOCKED
    assert evidence.outcomes == []


def test_a_heredoc_body_mentioning_a_test_command_is_not_a_verification() -> None:
    """`gh pr create --body "$(cat <<EOF ... pytest ... EOF)"` runs no tests.

    Matching the whole command string let prose inside a heredoc masquerade as a
    verification run. Harmless while such items were only recorded as having
    run; once an observed success promotes them to Completed, it becomes a
    false claim in a manager-facing report. Measured at 26 of 378 real items.
    """

    evidence = extract_evidence(
        resolved(
            command(
                "gh pr create --title x --body \"$(cat <<'EOF' "
                "Ran pytest and ruff to check this. EOF )\"",
                tool_failed=False,
            )
        )
    )

    assert evidence.outcomes == []


def test_a_real_command_before_a_heredoc_still_verifies() -> None:
    """Only the heredoc body is discounted, not the command that opened it."""

    evidence = extract_evidence(
        resolved(
            command(
                "uv run pytest -q && cat > notes.md <<'EOF' anything EOF",
                tool_failed=False,
            )
        )
    )

    assert len(evidence.outcomes) == 1
    assert evidence.outcomes[0].status is EvidenceStatus.COMPLETED


def test_clean_stderr_records_the_run_without_claiming_success() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": False},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert len(evidence.outcomes) == 1
    outcome = evidence.outcomes[0]
    assert outcome.text == "Ran verification command: pytest -q"
    assert "Verification passed" not in outcome.text
    assert outcome.confidence is EvidenceConfidence.MEDIUM
    assert outcome.extraction_method == "stderr_heuristic"
    assert outcome.status is EvidenceStatus.UNKNOWN


def test_stderr_redirecting_command_yields_no_outcome() -> None:
    """`2>&1` makes stderr empty by construction, so it supports no inference."""

    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q 2>&1 | tail -5",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": False},
                ),
                SessionActivity(
                    activity_id="a-2",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="ruff check . 2>/dev/null",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": False},
                ),
                SessionActivity(
                    activity_id="a-3",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pyright 2>errors.log",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": False},
                ),
                SessionActivity(
                    activity_id="a-4",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q &> out.log",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": False},
                ),
                SessionActivity(
                    activity_id="a-5",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q |& tee out.log",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": False},
                ),
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.outcomes == []
    assert evidence.errors == []
    assert len(evidence.commands) == 5  # the commands themselves are still evidence


def test_stderr_redirecting_command_yields_no_error_either() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="ruff check . 2>&1",
                    tool_name="Bash",
                    metadata={"stderr_empty": False, "interrupted": False},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.errors == []
    assert evidence.outcomes == []


def test_nonempty_stderr_is_not_treated_as_failure() -> None:
    """`git` writes to stderr on success, so stderr alone cannot mean failure."""
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="git stash",
                    tool_name="Bash",
                    metadata={"stderr_empty": False, "interrupted": False},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.errors == []
    assert evidence.outcomes == []
    assert [item.text for item in evidence.commands] == ["git stash"]


def test_interrupted_command_yields_no_verification_outcome() -> None:
    resolved = ResolvedSession(
        session=AgentSession(
            harness="claude-code",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="Bash",
                    metadata={"stderr_empty": True, "interrupted": True},
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.outcomes == []
    assert evidence.commands  # the command itself is still evidence


def test_missing_stderr_metadata_leaves_opencode_behavior_untouched() -> None:
    """OpenCode tool calls have no stderr flags; nothing new should appear."""

    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="sess-1",
            working_directory="/repo/main",
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 21, tzinfo=UTC),
                    content="pytest -q",
                    tool_name="bash",
                )
            ],
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/mike/agent-worklog",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="git_origin_remote",
        ),
    )

    evidence = extract_evidence(resolved)

    assert evidence.outcomes == []
    assert evidence.errors == []


def test_session_title_is_capped_at_the_evidence_text_length() -> None:
    """A harness-recorded title has no length bound of its own.

    Codex's `threads.title` is the verbatim first user message, and one measured
    on a real machine ran to 1,478 characters. The cap belongs here rather than
    in the summarizer: `SessionEvidence` is what the LLM request serializes
    whole, so a cap applied later would protect the rendered report only.
    """

    session = resolved()
    session.session.title = "word " * 100

    evidence = extract_evidence(session)

    assert evidence.title is not None
    assert len(evidence.title) == EVIDENCE_TEXT_MAX_LENGTH
    assert evidence.title.endswith("…")


def test_a_short_session_title_is_left_alone() -> None:
    session = resolved()
    session.session.title = "Add retry to the price fetcher"

    evidence = extract_evidence(session)

    assert evidence.title == "Add retry to the price fetcher"
