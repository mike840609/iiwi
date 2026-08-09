"""Recursive, conservative secret redaction."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.DOTALL,
)
_URL_PASSWORD = re.compile(r"(?P<prefix>\b[a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+@", re.I)
_CURL_USER_PASSWORD = re.compile(r"(?P<prefix>\b(?:curl\s+)?-u\s+[^\s:]+:)[^\s]+", re.I)
_AUTHORIZATION = re.compile(r"(?P<prefix>\b(?:Bearer|Basic)\s+)[^\s,;\"']+", re.I)
_GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
_PROVIDER_KEY = re.compile(r"\bsk-(?:proj-|ant-[A-Za-z0-9_-]*-)?[A-Za-z0-9_-]{16,}\b")
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_AWS_SECRET_ASSIGNMENT = re.compile(
    r"(?P<prefix>\b(?:AWS_SECRET_ACCESS_KEY|aws_secret_access_key)\s*[=:]\s*)[^\s,;]+",
    re.I,
)
_ASSIGNMENT = re.compile(
    r"(?P<prefix>\b(?:password|passwd|pwd|token|secret|api[_-]?key)\s*[=:]\s*)[^\s,;]+",
    re.I,
)
_JWT = re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


def _replace_with_prefix(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{REDACTED}"


def redact_text(text: str) -> str:
    """Redact common credentials while retaining surrounding diagnostic context."""

    value = _PRIVATE_KEY.sub(REDACTED, text)
    value = _URL_PASSWORD.sub(lambda match: f"{match.group('prefix')}{REDACTED}@", value)
    value = _CURL_USER_PASSWORD.sub(_replace_with_prefix, value)
    value = _AUTHORIZATION.sub(_replace_with_prefix, value)
    value = _GITHUB_TOKEN.sub(REDACTED, value)
    value = _PROVIDER_KEY.sub(REDACTED, value)
    value = _AWS_ACCESS_KEY.sub(REDACTED, value)
    value = _AWS_SECRET_ASSIGNMENT.sub(_replace_with_prefix, value)
    value = _ASSIGNMENT.sub(_replace_with_prefix, value)
    return _JWT.sub(REDACTED, value)


def redact_value(value: Any) -> Any:
    """Recursively redact strings in JSON-like values."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value
