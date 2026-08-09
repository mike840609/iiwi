import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from iiwi.process import CommandResult
from tests.codex_state_db import seconds, write_database


@pytest.fixture(autouse=True)
def _isolate_settings_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate the settings file to avoid reading a developer's or CI's real config.

    _load_settings() resolves to a machine-global path when IIWI_CONFIG_FILE
    is unset. This fixture ensures every test gets a guaranteed-nonexistent path
    in tmp_path, preventing nondeterministic failures when config set creates a
    real file.

    Per-test monkeypatch.setenv calls take precedence and will override this default.
    """

    monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("IIWI_STATE_FILE", str(tmp_path / "state.json"))


@dataclass
class FakeCommandRunner:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    calls: list[list[str]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    results: dict[str, CommandResult] = field(default_factory=dict)

    def set_output(self, command_suffix: str, output: str) -> None:
        self.outputs[command_suffix] = output

    def set_result(self, command_suffix: str, result: CommandResult) -> None:
        self.results[command_suffix] = result

    def run(self, args: list[str], *, stdout_path: Path | None = None) -> CommandResult:
        self.calls.append(args)
        joined = " ".join(args)
        explicit = next(
            (value for suffix, value in self.results.items() if joined.endswith(suffix)),
            None,
        )
        if explicit is not None:
            return explicit
        stdout = next(
            (value for suffix, value in self.outputs.items() if joined.endswith(suffix)),
            self.stdout,
        )
        return CommandResult(self.returncode, stdout, self.stderr)


@pytest.fixture
def fake_runner() -> FakeCommandRunner:
    return FakeCommandRunner()


@pytest.fixture
def fake_git_runner() -> FakeCommandRunner:
    return FakeCommandRunner()

_ACCEPTANCE_FIXTURES = Path(__file__).parent / "fixtures" / "opencode"
_ACCEPTANCE_TZ = ZoneInfo("Asia/Taipei")


def _millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


@dataclass
class AcceptanceCommandRunner:
    export_calls: list[list[str]] = field(default_factory=list)
    run_calls: list[list[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rows = [
            {
                "id": "root-agent",
                "project_id": "project-agent",
                "parent_id": None,
                "directory": "/worktrees/agent-main",
                "title": "Agent root",
                "time_created": _millis(datetime(2026, 7, 10, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 28, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "agent-feature",
                "project_id": "project-agent",
                "parent_id": "root-agent",
                "directory": "/worktrees/agent-feature",
                "title": "Agent feature",
                "time_created": _millis(datetime(2026, 7, 21, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 21, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "cross-repo-child",
                "project_id": "project-assets",
                "parent_id": "root-agent",
                "directory": "/worktrees/assets",
                "title": "Assets child",
                "time_created": _millis(datetime(2026, 7, 22, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 22, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "secret-session",
                "project_id": "project-assets",
                "parent_id": None,
                "directory": "/worktrees/assets-secret",
                "title": "Secret session",
                "time_created": _millis(datetime(2026, 7, 23, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 23, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "api-a",
                "project_id": "project-api-a",
                "parent_id": None,
                "directory": "/worktrees/team-a-api",
                "title": "API A",
                "time_created": _millis(datetime(2026, 7, 24, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 24, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "api-b",
                "project_id": "project-api-b",
                "parent_id": None,
                "directory": "/worktrees/team-b-api",
                "title": "API B",
                "time_created": _millis(datetime(2026, 7, 25, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 25, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
            {
                "id": "failed-export",
                "project_id": "project-failed",
                "parent_id": None,
                "directory": "/worktrees/failed",
                "title": "Failed export",
                "time_created": _millis(datetime(2026, 7, 25, tzinfo=_ACCEPTANCE_TZ)),
                "time_updated": _millis(datetime(2026, 7, 25, 3, tzinfo=_ACCEPTANCE_TZ)),
            },
        ]
        self.exports = {
            "root-agent": "export-cross-repo-child.json",
            "agent-feature": "export-agent-feature.json",
            "cross-repo-child": "export-assets-child.json",
            "secret-session": "export-secret.json",
            "api-a": "export-api-a.json",
            "api-b": "export-api-b.json",
        }
        self.remotes = {
            "/worktrees/agent-main": "git@github.com:mike/agent-worklog.git",
            "/worktrees/agent-feature": "https://github.com/mike/agent-worklog.git",
            "/worktrees/assets": "git@github.com:mike/assets-tracker.git",
            "/worktrees/assets-secret": "https://github.com/mike/assets-tracker.git",
            "/worktrees/team-a-api": "git@github.com:team-a/api.git",
            "/worktrees/team-b-api": "git@github.com:team-b/api.git",
        }

    def run(self, args: list[str], *, stdout_path: Path | None = None) -> CommandResult:
        if args[:2] == ["opencode", "run"]:
            self.run_calls.append(args)
            if stdout_path is not None:
                stdout_path.write_text(
                    "# Weekly Engineering Review\n\nNARRATIVE_ACCEPTANCE_MARKER\n",
                    encoding="utf-8",
                )
            return CommandResult(0, "", "")
        if args[:2] == ["opencode", "db"]:
            return CommandResult(0, json.dumps(self.rows), "")
        if args[:2] == ["opencode", "stats"]:
            return CommandResult(
                0,
                "models: gpt-5-mini 1234 tokens\ntools: bash 12 calls\n",
                "",
            )
        if args[:2] == ["opencode", "export"]:
            self.export_calls.append(args)
            session_id = args[2]
            if session_id == "failed-export":
                return CommandResult(1, "", "fixture export failure")
            fixture = _ACCEPTANCE_FIXTURES / self.exports[session_id]
            return CommandResult(0, fixture.read_text(encoding="utf-8"), "")
        if len(args) >= 5 and args[:2] == ["git", "-C"]:
            cwd = args[2]
            command = args[3:]
            if command == ["remote", "get-url", "origin"]:
                remote = self.remotes.get(cwd)
                if remote:
                    return CommandResult(0, remote, "")
                return CommandResult(2, "", "no remote")
            if command == ["rev-parse", "--git-common-dir"]:
                return CommandResult(0, f"{cwd}/.git", "")
            if command == ["branch", "--show-current"]:
                return CommandResult(0, "main", "")
        return CommandResult(1, "", f"unexpected command: {args}")


@pytest.fixture
def mocked_opencode() -> AcceptanceCommandRunner:
    return AcceptanceCommandRunner()


@dataclass
class GitOnlyCommandRunner:
    """Answer git queries for the Claude Code and Codex acceptance runs, and fake
    `opencode run` so the narrative path can be exercised without OpenCode installed.
    """

    remotes: dict[str, str] = field(default_factory=dict)
    narrative_marker: str = "NARRATIVE_ACCEPTANCE_MARKER"
    run_calls: list[list[str]] = field(default_factory=list)
    run_transcripts: list[str] = field(default_factory=list)

    def run(self, args: list[str], *, stdout_path: Path | None = None) -> CommandResult:
        if args[:2] == ["opencode", "run"]:
            self.run_calls.append(args)
            transcript_path = Path(args[args.index("--file") + 1])
            self.run_transcripts.append(transcript_path.read_text(encoding="utf-8"))
            if stdout_path is not None:
                stdout_path.write_text(
                    f"# Weekly Engineering Review\n\n{self.narrative_marker}\n",
                    encoding="utf-8",
                )
            return CommandResult(0, "", "")
        if len(args) >= 5 and args[:2] == ["git", "-C"]:
            cwd = args[2]
            command = args[3:]
            if command == ["remote", "get-url", "origin"]:
                remote = self.remotes.get(cwd)
                if remote:
                    return CommandResult(0, remote, "")
                return CommandResult(2, "", "no remote")
            if command == ["rev-parse", "--git-common-dir"]:
                return CommandResult(0, f"{cwd}/.git", "")
            if command == ["branch", "--show-current"]:
                return CommandResult(0, "main", "")
        if args[:1] == ["git"]:
            return CommandResult(0, "git version 2.45.0", "")
        return CommandResult(1, "", f"unexpected command: {args}")


@pytest.fixture
def claude_code_projects(tmp_path: Path) -> Path:
    """A projects directory with one root session and one subagent session."""

    root = tmp_path / "claude-projects"
    session_dir = root / "-repo-agent-worklog"
    session_dir.mkdir(parents=True)

    def record(payload: dict) -> str:
        return json.dumps(payload)

    root_lines = [
        record(
            {
                "type": "user",
                "origin": {"kind": "human"},
                "message": {
                    "role": "user",
                    "content": "Add retry to the price fetcher",
                },
                "uuid": "u-1",
                "timestamp": "2026-07-21T01:00:00.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record(
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I implemented the retry."},
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "Bash",
                            "input": {"command": "pytest -q"},
                        },
                    ],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 200,
                        "cache_read_input_tokens": 1000,
                        "cache_creation_input_tokens": 50,
                    },
                },
                "uuid": "a-1",
                "timestamp": "2026-07-21T01:00:01.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu-1", "content": "ok"}
                    ],
                },
                "toolUseResult": {
                    "stdout": "ACCEPTANCE_SECRET_MARKER 42 passed",
                    "stderr": "",
                    "interrupted": False,
                    "isImage": False,
                },
                "uuid": "u-2",
                "timestamp": "2026-07-21T01:00:02.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        # Thinking-only, so it emits no activity, and last, so its usage has no
        # later activity to ride on. Its tokens must still reach the usage table.
        record(
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "ACCEPTANCE_SECRET_MARKER plan"}
                    ],
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 100,
                        "cache_read_input_tokens": 500,
                        "cache_creation_input_tokens": 25,
                    },
                },
                "uuid": "a-2",
                "timestamp": "2026-07-21T01:00:03.000Z",
                "cwd": "/worktrees/agent-main",
                "gitBranch": "main",
            }
        ),
        record({"type": "ai-title", "aiTitle": "Retry for the price fetcher"}),
    ]
    (session_dir / "root-session.jsonl").write_text(
        "\n".join(root_lines) + "\n", encoding="utf-8"
    )

    subagent_dir = session_dir / "root-session" / "subagents"
    subagent_dir.mkdir(parents=True)
    (subagent_dir / "agent-abc.jsonl").write_text(
        record(
            {
                "type": "user",
                "origin": {"kind": "human"},
                "message": {"role": "user", "content": "Review the retry helper"},
                "uuid": "u-3",
                "timestamp": "2026-07-22T01:00:00.000Z",
                "cwd": "/worktrees/assets",
                "gitBranch": "main",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (subagent_dir / "agent-abc.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": "Review the helper"}),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def git_only_runner() -> GitOnlyCommandRunner:
    return GitOnlyCommandRunner(
        remotes={
            "/worktrees/agent-main": "git@github.com:mike/agent-worklog.git",
            "/worktrees/assets": "git@github.com:mike/assets-tracker.git",
        }
    )


def _codex_record(timestamp: str, record_type: str, payload: dict) -> str:
    return json.dumps({"timestamp": timestamp, "type": record_type, "payload": payload})


@pytest.fixture
def codex_home(tmp_path: Path) -> Path:
    """A Codex home with a state database, one root session and one subagent."""

    home = tmp_path / "codex"
    rollouts = home / "sessions" / "2026" / "07" / "21"
    rollouts.mkdir(parents=True)

    root_path = rollouts / "rollout-root.jsonl"
    root_path.write_text(
        "\n".join(
            [
                _codex_record(
                    "2026-07-21T01:00:00.000Z",
                    "session_meta",
                    {
                        "session_id": "thread-root",
                        "timestamp": "2026-07-21T01:00:00.000Z",
                        "cwd": "/worktrees/agent-main",
                        "thread_source": "user",
                    },
                ),
                _codex_record(
                    "2026-07-21T01:00:01.000Z",
                    "turn_context",
                    {"turn_id": "t-1", "cwd": "/worktrees/agent-main",
                     "model": "gpt-5.6-sol"},
                ),
                _codex_record(
                    "2026-07-21T01:00:02.000Z",
                    "event_msg",
                    {"type": "user_message",
                     "message": "Add retry to the price fetcher"},
                ),
                _codex_record(
                    "2026-07-21T01:00:03.000Z",
                    "event_msg",
                    {"type": "agent_message", "message": "I implemented the retry."},
                ),
                _codex_record(
                    "2026-07-21T01:00:04.000Z",
                    "response_item",
                    {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-1",
                        "arguments": json.dumps(
                            {"cmd": "pytest -q", "workdir": "/worktrees/agent-main"}
                        ),
                    },
                ),
                _codex_record(
                    "2026-07-21T01:00:05.000Z",
                    "response_item",
                    {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "call_id": "call-2",
                        "input": 'const r = await tools.exec_command('
                                 '{"cmd":"CODEX_JS_MARKER"}); text(r);',
                    },
                ),
                _codex_record(
                    "2026-07-21T01:00:06.000Z",
                    "event_msg",
                    {
                        "type": "patch_apply_end",
                        "call_id": "call-3",
                        "success": True,
                        "changes": {
                            "/worktrees/agent-main/src/fetch.py": {
                                "type": "update",
                                "content": "CODEX_FILE_BODY_MARKER",
                            }
                        },
                    },
                ),
                _codex_record(
                    "2026-07-21T01:00:07.000Z",
                    "event_msg",
                    {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 1500,
                                "output_tokens": 300,
                                "cached_input_tokens": 1000,
                                "cache_write_input_tokens": 75,
                                "reasoning_output_tokens": 90,
                            }
                        },
                    },
                ),
                # A trailing reasoning-only turn: no activity, tokens still count.
                _codex_record(
                    "2026-07-21T01:00:08.000Z",
                    "event_msg",
                    {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 1515,
                                "output_tokens": 400,
                                "cached_input_tokens": 1500,
                                "cache_write_input_tokens": 75,
                            }
                        },
                    },
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    sub_path = rollouts / "rollout-sub.jsonl"
    sub_path.write_text(
        "\n".join(
            [
                _codex_record(
                    "2026-07-22T01:00:00.000Z",
                    "session_meta",
                    {
                        "session_id": "thread-sub",
                        "timestamp": "2026-07-22T01:00:00.000Z",
                        "cwd": "/worktrees/assets",
                        "thread_source": "subagent",
                        "parent_thread_id": "thread-root",
                    },
                ),
                _codex_record(
                    "2026-07-22T01:00:01.000Z",
                    "event_msg",
                    {"type": "user_message", "message": "Review the retry helper"},
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    write_database(
        home / "state_5.sqlite",
        rows=[
            (
                "thread-root",
                str(root_path),
                seconds(datetime(2026, 7, 21, tzinfo=_ACCEPTANCE_TZ)),
                seconds(datetime(2026, 7, 21, 2, tzinfo=_ACCEPTANCE_TZ)),
                "/worktrees/agent-main",
                "Retry for the price fetcher",
                None,
                "user",
                0,
            ),
            (
                "thread-sub",
                str(sub_path),
                seconds(datetime(2026, 7, 22, tzinfo=_ACCEPTANCE_TZ)),
                seconds(datetime(2026, 7, 22, 1, tzinfo=_ACCEPTANCE_TZ)),
                "/worktrees/assets",
                "",
                "Ampere",
                "subagent",
                0,
            ),
        ],
        edges=[("thread-root", "thread-sub", "completed")],
    )
    return home
