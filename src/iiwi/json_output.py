"""Machine-readable JSON output for scripting consumers.

Every value leaves this module already redacted: a piped command's stdout is
captured, logged, and shared, so it must not carry what the interactive and
file paths refuse to print.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from iiwi.interactive.density import message_volume
from iiwi.security.redactor import redact_text
from iiwi.services.doctor import DoctorResult
from iiwi.services.scan import ScanResult


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def scan_result_to_dict(scan: ScanResult) -> dict[str, Any]:
    """A redacted, JSON-serialisable view of a scan."""
    repositories = []
    for repository_id, sessions in scan.sessions_by_repository.items():
        name = sessions[0].repository.display_name if sessions else repository_id
        repositories.append(
            {
                "id": redact_text(repository_id),
                "name": redact_text(name),
                "sessions": [
                    {
                        "id": item.session.session_id,
                        "title": redact_text(item.session.title or ""),
                        "messages": message_volume(item.session),
                        "directory": (
                            redact_text(item.session.working_directory)
                            if item.session.working_directory
                            else None
                        ),
                    }
                    for item in sessions
                ],
            }
        )
    return {
        "period": {
            "since": _iso(scan.period.since),
            "until": _iso(scan.period.until),
        },
        "candidate_session_count": scan.candidate_session_count,
        "loaded_session_count": scan.loaded_session_count,
        "failed_session_count": scan.failed_session_count,
        "excluded_session_count": scan.excluded_session_count,
        "repositories": repositories,
        "warnings": [redact_text(warning) for warning in scan.warnings],
    }


def scan_result_to_json(scan: ScanResult) -> str:
    return json.dumps(scan_result_to_dict(scan), indent=2, ensure_ascii=False)


def doctor_result_to_dict(result: DoctorResult, harness: str) -> dict[str, Any]:
    """A redacted, JSON-serialisable view of a doctor run."""
    return {
        "harness": harness,
        "ok": result.ok,
        "checks": [
            {
                "name": check.name,
                "ok": check.ok,
                "detail": redact_text(check.detail),
            }
            for check in result.checks
        ],
    }


def doctor_result_to_json(result: DoctorResult, harness: str) -> str:
    return json.dumps(doctor_result_to_dict(result, harness), indent=2, ensure_ascii=False)
