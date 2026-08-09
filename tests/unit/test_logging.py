from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi.logging import ConsoleReporter, RichProgressReporter
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import AgentSession
from iiwi.models.time_range import DateRange
from iiwi.progress import NullProgressReporter, ProgressStage
from iiwi.services.scan import ScanResult


def forced_console(stream: StringIO, *, width: int = 100) -> Console:
    return Console(
        file=stream,
        force_terminal=True,
        color_system=None,
        width=width,
    )


def test_progress_renders_one_transient_stage_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    output_stream = StringIO()
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        console=forced_console(output_stream),
        progress_console=forced_console(progress_stream),
    )

    with reporter.progress() as progress:
        progress.start(ProgressStage.EXPORTING_SESSIONS, total=3)
        progress.advance(2)
    reporter.message("done")

    progress_output = progress_stream.getvalue()
    assert "Exporting sessions" in progress_output
    assert "2/3" in progress_output
    assert progress_output.count("\n") == 1
    assert progress_output.endswith("\x1b[2K")
    assert "done" in output_stream.getvalue()
    assert "Exporting sessions" not in output_stream.getvalue()


def test_progress_ellipsizes_to_one_row_in_a_narrow_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        progress_console=forced_console(progress_stream, width=40),
    )

    with reporter.progress() as progress:
        progress.start(ProgressStage.PREPARING_EVIDENCE, total=12345)
        progress.advance(12345)

    progress_output = progress_stream.getvalue()
    assert "…" in progress_output
    assert progress_output.count("\n") == 1


def test_progress_is_silent_when_the_terminal_cannot_render_transient_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERM", "dumb")
    progress_stream = StringIO()
    reporter = ConsoleReporter(progress_console=forced_console(progress_stream))

    with reporter.progress() as progress:
        progress.start(ProgressStage.EXPORTING_SESSIONS, total=3)
        progress.advance(2)

    assert progress_stream.getvalue() == ""


def test_quiet_progress_is_a_no_op() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        quiet=True,
        progress_console=forced_console(progress_stream),
    )

    with reporter.progress() as progress:
        assert isinstance(progress, NullProgressReporter)
        progress.start(ProgressStage.DISCOVERING_SESSIONS)

    assert progress_stream.getvalue() == ""


def test_progress_context_finishes_after_an_exception() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        progress_console=forced_console(progress_stream),
    )
    active: RichProgressReporter | None = None

    with pytest.raises(RuntimeError, match="boom"), reporter.progress() as progress:
        assert isinstance(progress, RichProgressReporter)
        active = progress
        progress.start(ProgressStage.RENDERING_REPORT)
        raise RuntimeError("boom")

    assert active is not None
    assert active._status is None


def test_progress_context_finishes_after_keyboard_interrupt() -> None:
    progress_stream = StringIO()
    reporter = ConsoleReporter(
        progress_console=forced_console(progress_stream),
    )
    active: RichProgressReporter | None = None

    with pytest.raises(KeyboardInterrupt), reporter.progress() as progress:
        assert isinstance(progress, RichProgressReporter)
        active = progress
        progress.start(ProgressStage.RENDERING_REPORT)
        raise KeyboardInterrupt

    assert active is not None
    assert active._status is None


SCAN_TZ = ZoneInfo("Asia/Taipei")


def scan_result_with(sessions: list[AgentSession]) -> ScanResult:
    identity = RepositoryIdentity(
        repository_id="git:github.com/mike/agent-worklog",
        display_name="Iiwi",
        identity_type=RepositoryIdentityType.GIT_REMOTE,
        normalized_remote="github.com/mike/agent-worklog",
        resolution_method="test",
    )
    resolved = [
        ResolvedSession(session=session, repository=identity) for session in sessions
    ]
    return ScanResult(
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=SCAN_TZ),
            until=datetime(2026, 7, 27, tzinfo=SCAN_TZ),
        ),
        candidate_session_count=len(sessions),
        loaded_session_count=len(sessions),
        failed_session_count=0,
        resolved_sessions=resolved,
        sessions_by_repository={"git:github.com/mike/agent-worklog": resolved},
        warnings=["One session could not be exported."],
    )


def test_verbose_scan_lists_session_titles_and_directories() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                    working_directory="/repos/agent-worklog",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "Fix the exporter" in output
    assert "/repos/agent-worklog" in output
    assert "One session could not be exported." in output


def test_a_session_without_a_title_falls_back_to_its_id() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [AgentSession(harness="opencode", session_id="ses_def")]
        )
    )

    assert "ses_def" in output_stream.getvalue()


def test_non_verbose_scan_does_not_list_sessions() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(console=forced_console(output_stream, width=200))

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                    working_directory="/repos/agent-worklog",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "Iiwi" in output
    assert "Fix the exporter" not in output


def test_quiet_scan_still_prints_only_the_count() -> None:
    output_stream = StringIO()
    reporter = ConsoleReporter(
        quiet=True,
        verbose=False,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_abc",
                    title="Fix the exporter",
                )
            ]
        )
    )

    assert output_stream.getvalue().strip() == "1"


def scan_result_with_display_name(display_name: str) -> ScanResult:
    """A repository whose display name itself carries the content under test.

    `scan_result_with` always uses the fixed name "Iiwi"; these two
    call sites are about the name itself, so they need one they control.
    """

    identity = RepositoryIdentity(
        repository_id="git:github.com/mike/agent-worklog",
        display_name=display_name,
        identity_type=RepositoryIdentityType.GIT_REMOTE,
        normalized_remote="github.com/mike/agent-worklog",
        resolution_method="test",
    )
    session = AgentSession(harness="opencode", session_id="ses_abc")
    resolved = [ResolvedSession(session=session, repository=identity)]
    return ScanResult(
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=SCAN_TZ),
            until=datetime(2026, 7, 27, tzinfo=SCAN_TZ),
        ),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=resolved,
        sessions_by_repository={"git:github.com/mike/agent-worklog": resolved},
    )


def test_scan_table_redacts_a_secret_in_the_repository_name() -> None:
    """The table is the only place in `scan_result` that skips redaction.

    A path-fallback identity embeds the working directory in `display_name`,
    so a secret-bearing path reaches the table unredacted today.
    """

    output_stream = StringIO()
    reporter = ConsoleReporter(console=forced_console(output_stream, width=200))

    reporter.scan_result(
        scan_result_with_display_name("token=tablesecretvalue999")
    )

    output = output_stream.getvalue()
    assert "tablesecretvalue999" not in output
    assert "[REDACTED]" in output


def test_scan_table_does_not_interpret_a_repository_name_as_rich_markup() -> None:
    """The verbose listing already disables markup; the table must match it.

    A `[bold]...[/bold]` name prints correctly in the listing and is silently
    eaten by the table today — the same repository's name disagreeing with
    itself between two views of the same `scan` run.
    """

    output_stream = StringIO()
    reporter = ConsoleReporter(console=forced_console(output_stream, width=200))

    reporter.scan_result(
        scan_result_with_display_name("[bold]not markup[/bold]")
    )

    assert "[bold]not markup[/bold]" in output_stream.getvalue()


def test_verbose_scan_redacts_a_secret_in_the_repository_heading() -> None:
    """The verbose listing's repository heading is the one string in that
    block that skips `redact_text` today, unlike `label` and `location`.
    """

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with_display_name("token=headingsecretvalue999")
    )

    output = output_stream.getvalue()
    assert "headingsecretvalue999" not in output
    assert "[REDACTED]" in output


def test_verbose_scan_redacts_secrets_in_session_titles() -> None:
    """Claude Code transcripts have no upstream sanitize step.

    ConsoleReporter's contract is that callers hand it redacted strings, and a
    scanned title and working directory are both raw harness data, so the
    listing must redact each independently. The two secrets below are
    distinct values so that dropping either redaction call is caught by its
    own assertion, rather than one field's redaction masking the other's.
    """

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="claude-code",
                    session_id="ses_ghi",
                    title="debug with token=hunter2secretvalue",
                    working_directory="/repos/token=dirsecretvalue999",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "hunter2secretvalue" not in output
    assert "dirsecretvalue999" not in output
    assert "[REDACTED]" in output


def test_verbose_scan_collapses_a_multi_line_title_to_one_list_item() -> None:
    """The report path solved this in `_normalized_title`; the console path must too."""

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_multiline",
                    title="Line one\nLine two  with   spaces",
                )
            ]
        )
    )

    output = output_stream.getvalue()
    assert "Line one Line two with spaces" in output
    assert "Line one\nLine two" not in output
    lines = [line for line in output.splitlines() if "Line one" in line]
    assert len(lines) == 1


def test_verbose_scan_ellipsizes_a_long_session_line_rather_than_wrapping() -> None:
    """A soft-wrapped continuation starts in column 0, where repository names are.

    Collapsing whitespace keeps a title on one *logical* line; only `no_wrap`
    keeps it on one *rendered* line, so a long path cannot read as a heading.
    """

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=40),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_long",
                    title="A session title far too long for this terminal",
                    working_directory="/repos/some/deeply/nested/checkout",
                )
            ]
        )
    )

    lines = output_stream.getvalue().splitlines()
    heading = lines.index("Iiwi")
    listing = [line for line in lines[heading + 1 :] if line.strip()]

    # One session must render as exactly one line: a second entry here is a
    # wrapped continuation sitting in column 0, indistinguishable from the
    # repository heading above it.
    assert len(listing) == 1
    assert listing[0].startswith("  • ")
    assert listing[0].endswith("…")


def test_verbose_scan_does_not_interpret_a_title_as_rich_markup() -> None:
    """A title is user content; Rich would otherwise eat anything in brackets."""

    output_stream = StringIO()
    reporter = ConsoleReporter(
        verbose=True,
        console=forced_console(output_stream, width=200),
    )

    reporter.scan_result(
        scan_result_with(
            [
                AgentSession(
                    harness="opencode",
                    session_id="ses_jkl",
                    title="[bold]not markup[/bold]",
                )
            ]
        )
    )

    assert "[bold]not markup[/bold]" in output_stream.getvalue()


def test_settings_table_shows_values_sources_and_defaults() -> None:
    from pathlib import Path

    from iiwi.config_store import SettingRow

    output_stream = StringIO()
    reporter = ConsoleReporter(console=forced_console(output_stream, width=120))

    reporter.settings_table(
        [
            SettingRow(
                key="report.timezone",
                # Deliberately shares no substring with the default below: an
                # earlier version of this test used "gpt-5" here against a
                # default of "gpt-5-mini", so blanking the Value column
                # entirely still passed (the default cell contains "gpt-5" as
                # a substring). "America/New_York" cannot pass that way.
                value="America/New_York",
                source="file",
                default="Asia/Taipei",
            ),
            SettingRow(
                key="harnesses.opencode.cli.timeout_seconds",
                value="30.0",
                source="default",
                default="30.0",
            ),
        ],
        path=Path("/home/dev/.config/agent-worklog/config.env"),
    )
    output = output_stream.getvalue()

    assert "/home/dev/.config/agent-worklog/config.env" in output
    # The point of the footer: nothing here is required.
    assert "Every setting is optional" in output

    # Scoped to the row itself: `settings_table` unconditionally prints
    # "Settings file: ..." on its own line, and that line contains the
    # substring "file" regardless of what the source column renders. A
    # whole-output `assert "file" in output` would pass even with the source
    # column left blank, so the source must be pinned to its own row.
    timezone_row = next(
        line for line in output.splitlines() if "report.timezone" in line
    )
    assert "America/New_York" in timezone_row
    assert "file" in timezone_row
    assert "Asia/Taipei" in timezone_row

    timeout_row = next(
        line for line in output.splitlines() if "harnesses.opencode.cli.timeout_seconds" in line
    )
    assert "default" in timeout_row


def test_settings_table_fully_renders_a_long_key_at_80_columns() -> None:
    """`config list`'s job is teaching key names; it must work at the default width.

    At COLUMNS=80, Rich's default truncation ellipsizes most keys down to an
    identical "harnesses.opencode.…" prefix. Folding wraps a key across lines
    inside the table borders instead, so the assertion strips borders and
    whitespace before checking that the full key text — not just a prefix —
    is present in the output.
    """
    from pathlib import Path

    from iiwi.config_store import SettingRow

    output_stream = StringIO()
    reporter = ConsoleReporter(console=forced_console(output_stream, width=80))

    reporter.settings_table(
        [
            SettingRow(
                key="harnesses.opencode.cli.timeout_seconds",
                value="30.0",
                source="default",
                default="30.0",
            ),
        ],
        path=Path("/home/dev/.config/agent-worklog/config.env"),
    )
    output = output_stream.getvalue()

    border_chars = "│┃┏┓┗┛┡┩┢┪┣┫┳┻╇╈╆╅╄╃╂┄─"
    collapsed = "".join(char for char in output if char not in border_chars and not char.isspace())

    assert "harnesses.opencode.cli.timeout_seconds" in collapsed
    assert "…" not in output
