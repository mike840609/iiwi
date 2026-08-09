"""Machine-readable JSON output for scripting consumers."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from iiwi.json_output import doctor_result_to_json, scan_result_to_json
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
from iiwi.services.doctor import DoctorCheck, DoctorResult
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")
PERIOD = DateRange(
    since=datetime(2026, 7, 20, 0, 0, tzinfo=TZ),
    until=datetime(2026, 7, 27, 0, 0, tzinfo=TZ),
)


def _session(session_id: str, title: str, messages: int = 2) -> AgentSession:
    activities = [
        SessionActivity(
            activity_id=f"{session_id}-{index}",
            activity_type=(
                ActivityType.USER_MESSAGE
                if index == 0
                else ActivityType.ASSISTANT_MESSAGE
            ),
            timestamp=datetime(2026, 7, 21, 8, index, tzinfo=TZ),
            content="worked",
        )
        for index in range(messages)
    ]
    return AgentSession(
        harness="opencode",
        session_id=session_id,
        title=title,
        working_directory=f"/Users/me/{session_id}",
        activities=activities,
    )


def _resolved(session: AgentSession) -> ResolvedSession:
    return ResolvedSession(
        session=session,
        repository=RepositoryIdentity(
            repository_id=f"git:github.com/mike/{session.session_id}",
            display_name=session.session_id.capitalize(),
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="stub",
        ),
    )


def _scan() -> ScanResult:
    first = _resolved(_session("dotfiles", "Tune dotfiles"))
    second = _resolved(_session("notes", "Write notes"))
    return ScanResult(
        period=PERIOD,
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=[first, second],
        sessions_by_repository={
            "git:github.com/mike/dotfiles": [first],
            "git:github.com/mike/notes": [second],
        },
        warnings=["a scan warning"],
        excluded_session_count=0,
    )


def test_scan_json_carries_period_counts_and_repositories() -> None:
    payload = json.loads(scan_result_to_json(_scan()))

    assert payload["period"] == {
        "since": "2026-07-20T00:00:00+08:00",
        "until": "2026-07-27T00:00:00+08:00",
    }
    assert payload["candidate_session_count"] == 2
    assert payload["loaded_session_count"] == 2
    assert payload["failed_session_count"] == 0
    assert payload["excluded_session_count"] == 0
    assert payload["warnings"] == ["a scan warning"]
    repositories = payload["repositories"]
    assert [repo["id"] for repo in repositories] == [
        "git:github.com/mike/dotfiles",
        "git:github.com/mike/notes",
    ]
    session = repositories[0]["sessions"][0]
    assert session["id"] == "dotfiles"
    assert session["title"] == "Tune dotfiles"
    assert session["messages"] == 2
    assert session["directory"] == "/Users/me/dotfiles"


def test_scan_json_redacts_secret_shaped_titles() -> None:
    scan = _scan()
    scan.resolved_sessions[0].session.title = "deploy sk-proj-not-a-real-secret-key"
    scan.sessions_by_repository["git:github.com/mike/dotfiles"][0].session.title = (
        "deploy sk-proj-not-a-real-secret-key"
    )

    payload = json.loads(scan_result_to_json(scan))

    assert "[REDACTED]" in payload["repositories"][0]["sessions"][0]["title"]
    assert "sk-proj-not-a-real-secret-key" not in payload["repositories"][0]["sessions"][0]["title"]


def test_doctor_json_lists_checks_and_overall_ok() -> None:
    result = DoctorResult(
        checks=[
            DoctorCheck(name="git", ok=True, detail="git version 2.47.0"),
            DoctorCheck(name="opencode version", ok=False, detail="command not found"),
        ]
    )

    payload = json.loads(doctor_result_to_json(result, harness="opencode"))

    assert payload["harness"] == "opencode"
    assert payload["ok"] is False
    assert payload["checks"] == [
        {"name": "git", "ok": True, "detail": "git version 2.47.0"},
        {"name": "opencode version", "ok": False, "detail": "command not found"},
    ]


def test_doctor_json_redacts_check_details() -> None:
    result = DoctorResult(
        checks=[DoctorCheck(name="git", ok=True, detail="token sk-proj-not-a-real-secret-key")]
    )

    payload = json.loads(doctor_result_to_json(result, harness="opencode"))

    assert "[REDACTED]" in payload["checks"][0]["detail"]
    assert "sk-proj-not-a-real-secret-key" not in payload["checks"][0]["detail"]
