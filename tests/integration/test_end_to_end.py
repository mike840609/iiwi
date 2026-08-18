from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

import iiwi.cli as cli

TZ = ZoneInfo("Asia/Taipei")


def test_end_to_end_weekly_worklog(
    tmp_path: Path,
    monkeypatch,
    mocked_opencode,
) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(
        cli,
        "CommandRunner",
        lambda timeout_seconds: mocked_opencode,
    )
    output = tmp_path / "worklog.md"

    result = CliRunner().invoke(
        cli.app,
        [
            "report",
            "--period",
            "last-week",
            "--no-llm",
            "--output",
            str(output),
            "--harness",
            "opencode",
        ],
    )

    assert result.exit_code == 0, result.stdout
    content = output.read_text(encoding="utf-8")
    assert "github.com/mike/iiwi" in content
    assert "github.com/mike/assets-tracker" in content
    assert "github.com/team-a/api" in content
    assert "github.com/team-b/api" in content
    assert "super-secret-token" not in content
    assert content.count("### Iiwi") == 1
    assert "#### Sessions" in content
    assert "root-agent" in content
    assert "#### Directories" in content
    assert "/worktrees/agent-main" in content
    assert "Session failed-export export failed" in content
    assert mocked_opencode.export_calls
    assert all("--sanitize" not in call for call in mocked_opencode.export_calls)
    assert "[redacted:" not in content
    assert "## Usage" in content
    assert "gpt-5-mini 1234 tokens" in content


def test_end_to_end_narrative_report_uses_local_opencode_run(
    tmp_path: Path,
    monkeypatch,
    mocked_opencode,
) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(
        cli,
        "CommandRunner",
        lambda timeout_seconds: mocked_opencode,
    )

    result = CliRunner().invoke(
        cli.app,
        ["report", "--period", "last-week", "--dry-run", "--harness", "opencode"],
    )

    assert result.exit_code == 0, result.stdout
    assert "NARRATIVE_ACCEPTANCE_MARKER" in result.stdout
    assert "# Engineering Worklog" in result.stdout
    assert any(call[:2] == ["opencode", "run"] for call in mocked_opencode.run_calls)
    assert all("--sanitize" not in call for call in mocked_opencode.export_calls)
    assert "[redacted:" not in result.stdout


def test_end_to_end_no_llm_never_runs_opencode(
    tmp_path: Path,
    monkeypatch,
    mocked_opencode,
) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )
    monkeypatch.setattr(
        cli,
        "CommandRunner",
        lambda timeout_seconds: mocked_opencode,
    )

    result = CliRunner().invoke(
        cli.app,
        ["report", "--period", "last-week", "--no-llm", "--dry-run"],
    )

    assert result.exit_code == 0, result.stdout
    assert mocked_opencode.run_calls == []
    assert "NARRATIVE_ACCEPTANCE_MARKER" not in result.stdout
    assert "## Repositories" in result.stdout
