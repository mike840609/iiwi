from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

import iiwi.cli as cli

TZ = ZoneInfo("Asia/Taipei")


def _invoke(
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
    output: Path,
    *extra_args: str,
    narrative: bool = False,
):
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: git_only_runner)
    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY",
        str(claude_code_projects),
    )
    args = ["report", "--harness", "claude-code", "--period", "last-week"]
    if not narrative:
        args.append("--no-llm")
    args += ["--output", str(output), *extra_args]
    return CliRunner().invoke(cli.app, args)


def test_claude_code_report_groups_by_repository_and_reports_usage(
    tmp_path: Path,
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, claude_code_projects, git_only_runner, output)

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/iiwi" in content
    assert "github.com/mike/assets-tracker" in content
    assert "Retry for the price fetcher" in content
    assert "## Usage" in content
    # Pin the four aggregated usage numbers (input, output, cache read, cache write) to
    # the fixture's message.usage blocks, not just the model name appearing somewhere.
    # The totals include the trailing thinking-only record, which emits no activity of
    # its own: 10+5 input, 200+100 output, 1,000+500 cache read, 50+25 cache write.
    assert "claude-opus-5     15     300       1,500           75" in content
    assert "Total             15     300       1,500           75" in content
    assert "Window: the last" not in content  # exact period, no widened-window caveat
    assert "ACCEPTANCE_SECRET_MARKER" not in content
    # No exit code exists, so the run is reported without claiming an outcome, and
    # it lands under In Progress rather than disappearing from the report.
    assert "Verification passed" not in content
    # Scope to the Iiwi repository's own section: repos sort case-insensitively by
    # display name, and "Iiwi" now sorts after "Assets Tracker", so a bare first-match
    # split on "#### In Progress" would grab the wrong repository's section.
    iiwi_section = content.split("### Iiwi")[1]
    in_progress = iiwi_section.split("#### In Progress")[1]
    assert "- Ran verification command: pytest -q" in in_progress


def test_root_only_excludes_the_subagent_repository(
    tmp_path: Path,
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(
        monkeypatch,
        claude_code_projects,
        git_only_runner,
        output,
        "--root-only",
    )

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/iiwi" in content
    assert "github.com/mike/assets-tracker" not in content


def test_scan_reports_the_claude_code_sessions(
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: git_only_runner)
    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY",
        str(claude_code_projects),
    )

    result = CliRunner().invoke(
        cli.app,
        ["scan", "--harness", "claude-code", "--period", "last-week"],
    )

    assert result.exit_code == 0, result.stdout


def test_claude_code_report_narrative_uses_local_opencode_run(
    tmp_path: Path,
    monkeypatch,
    claude_code_projects: Path,
    git_only_runner,
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(
        monkeypatch, claude_code_projects, git_only_runner, output, narrative=True
    )

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "# Engineering Worklog" in content
    assert "NARRATIVE_ACCEPTANCE_MARKER" in content
    assert git_only_runner.run_calls, "opencode run was never invoked"
    transcript = git_only_runner.run_transcripts[0]
    assert "## Project:" in transcript
    assert "Add retry to the price fetcher" in transcript
