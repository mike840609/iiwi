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
_AUTHORIZATION = re.compile(
    r"(?P<prefix>\b(?:Bearer|Basic)\s+[\"']?)[^\s,;\"']+",
    re.I,
)
_GITHUB_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_PROVIDER_KEY = re.compile(r"\bsk-(?:proj-|ant-[A-Za-z0-9_-]*-)?[A-Za-z0-9_-]{16,}\b")
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_AWS_SECRET_ASSIGNMENT = re.compile(
    r"(?P<prefix>[\"']?\b(?:AWS_SECRET_ACCESS_KEY|aws_secret_access_key)\b[\"']?\s*[=:]\s*[\"']?)[^\s,;\"'}]+",
    re.I,
)
_SLACK_TOKEN = re.compile(r"\bxox[abeoprs]-[A-Za-z0-9-]{10,}\b")
_STRIPE_KEY = re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b")
_GOOGLE_API_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")
_NPM_TOKEN = re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")
# Keyword may carry env-style prefix or suffix segments (DB_PASSWORD, OPENAI_API_KEY);
# the segment bound keeps a long base64url run linear instead of quadratic.
_ASSIGNMENT = re.compile(
    r"(?P<prefix>[\"']?(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-]){0,8}"
    r"(?:password|passwd|token|secret|api[_-]?key)(?:[_-]?key)?[\"']?\s*[=:]\s*[\"']?)"
    r"[^\s,;\"'}]+",
    re.I,
)
# `pwd` only with `=` (SQL Server DSNs); `pwd: <path>` is shell output, not a secret.
_PWD_ASSIGNMENT = re.compile(r"(?P<prefix>[\"']?\bpwd[\"']?\s*=\s*[\"']?)[^\s,;\"'}]+", re.I)
# Both JWT segments are base64url-encoded JSON, so they always start with `eyJ`.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\b")


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
    value = _SLACK_TOKEN.sub(REDACTED, value)
    value = _STRIPE_KEY.sub(REDACTED, value)
    value = _GOOGLE_API_KEY.sub(REDACTED, value)
    value = _NPM_TOKEN.sub(REDACTED, value)
    value = _ASSIGNMENT.sub(_replace_with_prefix, value)
    value = _PWD_ASSIGNMENT.sub(_replace_with_prefix, value)
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
