from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

import iiwi.cli as cli
from iiwi.process import CommandResult

TZ = ZoneInfo("Asia/Taipei")


@dataclass
class PrivacyModeRunner:
    sanitized: bool
    export_calls: list[list[str]] = field(default_factory=list)
    run_calls: list[list[str]] = field(default_factory=list)

    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
    ) -> CommandResult:
        if args[:2] == ["opencode", "run"]:
            self.run_calls.append(args)
            if stdout_path is not None:
                stdout_path.write_text("Weekly review narrative\n", encoding="utf-8")
            return CommandResult(0, "", "")
        if args[:2] == ["opencode", "db"]:
            rows = [
                {
                    "id": "privacy-session",
                    "project_id": "privacy-project",
                    "parent_id": None,
                    "directory": "/worktrees/privacy-project",
                    "title": "Database sanitized title",
                    "time_created": int(datetime(2026, 7, 22, tzinfo=TZ).timestamp() * 1000),
                    "time_updated": int(
                        datetime(2026, 7, 22, 3, tzinfo=TZ).timestamp() * 1000
                    ),
                }
            ]
            return CommandResult(0, json.dumps(rows), "")
        if args[:2] == ["opencode", "export"]:
            self.export_calls.append(args)
            if self.sanitized:
                payload = {
                    "info": {
                        "title": "[redacted:session-title:privacy-session]",
                        "directory": "[redacted:session-directory:privacy-session]",
                    },
                    "messages": [
                        {
                            "info": {"id": "m1", "role": "user"},
                            "parts": [
                                {"type": "text", "text": "[redacted:text:p1]"}
                            ],
                        }
                    ],
                }
            else:
                payload = {
                    "info": {
                        "title": "Raw privacy title",
                        "directory": "/worktrees/privacy-project",
                    },
                    "messages": [
                        {
                            "info": {
                                "id": "m1",
                                "role": "user",
                                # A real per-message time, matching the database
                                # row's created time. Without it the message would
                                # be timestamp-less (issue #104) and the scan would
                                # exclude its activity from the requested week.
                                "time": {
                                    "created": int(
                                        datetime(
                                            2026, 7, 22, 1, 0, tzinfo=TZ
                                        ).timestamp()
                                        * 1000
                                    )
                                },
                            },
                            "parts": [
                                {"type": "text", "text": "Fix privacy defaults"}
                            ],
                        }
                    ],
                }
            return CommandResult(0, json.dumps(payload), "")
        if args[:2] == ["opencode", "stats"]:
            return CommandResult(0, "models: local 1 token\n", "")
        if len(args) >= 5 and args[:2] == ["git", "-C"]:
            command = args[3:]
            if command == ["remote", "get-url", "origin"]:
                return CommandResult(
                    0,
                    "https://github.com/example/privacy-project.git",
                    "",
                )
            if command == ["rev-parse", "--git-common-dir"]:
                return CommandResult(0, "/worktrees/privacy-project/.git", "")
            if command == ["branch", "--show-current"]:
                return CommandResult(0, "main", "")
        return CommandResult(1, "", f"unexpected command: {args}")


def _fixed_clock(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "_now_in_timezone",
        lambda timezone: datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
    )


def test_sanitized_mode_uses_flag_and_db_metadata(monkeypatch) -> None:
    runner = PrivacyModeRunner(sanitized=True)
    _fixed_clock(monkeypatch)
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "report",
            "--period",
            "last-week",
            "--sanitize",
            "--no-llm",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert runner.export_calls == [
        ["opencode", "export", "privacy-session", "--sanitize"]
    ]
    assert "Database sanitized title" in result.stdout
    assert "[redacted:" not in result.stdout


def test_narrative_uses_local_opencode_run(monkeypatch) -> None:
    runner = PrivacyModeRunner(sanitized=False)
    _fixed_clock(monkeypatch)
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: runner)

    result = CliRunner().invoke(
        cli.app,
        ["report", "--period", "last-week", "--dry-run"],
    )

    assert result.exit_code == 0, result.stdout
    assert "Weekly review narrative" in result.stdout
    assert any(call[:2] == ["opencode", "run"] for call in runner.run_calls)
    assert runner.export_calls == [["opencode", "export", "privacy-session"]]


def test_no_llm_never_invokes_opencode_run(monkeypatch) -> None:
    runner = PrivacyModeRunner(sanitized=False)
    _fixed_clock(monkeypatch)
    monkeypatch.setattr(cli, "CommandRunner", lambda timeout_seconds: runner)

    result = CliRunner().invoke(
        cli.app,
        ["report", "--period", "last-week", "--no-llm", "--dry-run"],
    )

    assert result.exit_code == 0, result.stdout
    assert "Fix privacy defaults" in result.stdout
    assert runner.run_calls == []
