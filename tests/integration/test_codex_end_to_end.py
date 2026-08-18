from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

import iiwi.cli as cli

TZ = ZoneInfo("Asia/Taipei")


def _invoke(
    monkeypatch,
    codex_home: Path,
    git_only_runner,
    output: Path | None = None,
    *extra: str,
    subcommand: str = "report",
    narrative: bool = False,
):
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: git_only_runner)
    monkeypatch.setenv(
        "IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(codex_home)
    )
    args = [subcommand, "--harness", "codex", "--period", "last-week"]
    if subcommand == "report":
        assert output is not None
        if not narrative:
            args.append("--no-llm")
        args += ["--output", str(output)]
    args.extend(extra)
    return CliRunner().invoke(cli.app, args)


def test_codex_report_groups_by_repository_and_reports_usage(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, codex_home, git_only_runner, output)

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/iiwi" in content
    assert "github.com/mike/assets-tracker" in content
    assert "Retry for the price fetcher" in content
    assert "Add retry to the price fetcher" in content
    assert "## Usage" in content
    # Pin the four aggregated numbers to the fixture's running totals. The second
    # token_count is a reasoning-only turn that emits no activity of its own, so
    # the row is the final running total: 1,515 / 400 / 1,500 / 75.
    assert "gpt-5.6-sol  1,515     400       1,500           75" in content
    assert "Total        1,515     400       1,500           75" in content
    assert "Window: the last" not in content


def test_codex_report_claims_no_verification_outcome(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, codex_home, git_only_runner, output)
    content = output.read_text(encoding="utf-8")

    assert result.exit_code == 0, result.stdout
    # Positive: the report was actually generated and carries the session's
    # goal, so the absence check below is not passing against an empty report.
    assert "Add retry to the price fetcher" in content
    # Codex records exit codes only inside free-form output text (see
    # CodexRolloutMapper's docstring and the unit test
    # test_no_outcome_signal_is_ever_recorded), so the pipeline never infers a
    # verification outcome for a Codex command -- `pytest -q` reaches only
    # evidence.commands, which no renderer surfaces, and must never be
    # reported as a claimed "Verification passed" outcome.
    assert "Verification passed" not in content


def test_codex_report_leaks_neither_patch_bodies_nor_javascript(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    _invoke(monkeypatch, codex_home, git_only_runner, output)
    content = output.read_text(encoding="utf-8")

    assert "CODEX_FILE_BODY_MARKER" not in content
    assert "CODEX_JS_MARKER" not in content
    assert "/worktrees/agent-main/src/fetch.py" in content


def test_root_only_excludes_the_subagent_repository(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    output = tmp_path / "worklog.md"

    result = _invoke(
        monkeypatch, codex_home, git_only_runner, output, "--root-only"
    )

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/iiwi" in content
    assert "github.com/mike/assets-tracker" not in content


def test_report_works_without_the_state_database(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    (codex_home / "state_5.sqlite").unlink()
    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, codex_home, git_only_runner, output)

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/iiwi" in content
    assert "github.com/mike/assets-tracker" in content


def test_scan_reports_the_codex_sessions(
    monkeypatch, codex_home: Path, git_only_runner
) -> None:
    result = _invoke(monkeypatch, codex_home, git_only_runner, subcommand="scan")

    assert result.exit_code == 0, result.stdout


def test_codex_report_narrative_uses_the_codex_provider(
    tmp_path: Path, monkeypatch, codex_home: Path, git_only_runner
) -> None:
    """The Codex harness resolves to the `codex` narration provider by default
    (no `narrator.provider` override), not `opencode run`."""

    output = tmp_path / "worklog.md"

    result = _invoke(monkeypatch, codex_home, git_only_runner, output, narrative=True)

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    # The narrative body came from `codex exec`, wrapped under the report header.
    assert "# Engineering Worklog" in content
    assert "NARRATIVE_ACCEPTANCE_MARKER" in content
    # `codex exec` was actually invoked (not the structured fallback).
    assert git_only_runner.run_calls, "codex exec was never invoked"
    assert git_only_runner.run_calls[0][:2] == ["codex", "exec"]
    # must-fix 1: `codex exec` must not inherit iiwi's own cwd, or it would get
    # write access to whatever repository iiwi's own process happens to be in.
    launch_cwd = git_only_runner.run_subprocess_cwds[0]
    assert launch_cwd is not None
    assert launch_cwd != Path.cwd()
    # Full session context reached `codex exec` via the grouped transcript.
    transcript = git_only_runner.run_transcripts[0]
    assert "## Project:" in transcript
    assert "Add retry to the price fetcher" in transcript
    assert "I implemented the retry." in transcript
