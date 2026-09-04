"""Recursive, conservative secret redaction."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
    r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.DOTALL,
)

_URL_PASSWORD = re.compile(
    r"(?P<prefix>\b[a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+@",
    re.I,
)

_CURL_USER_PASSWORD = re.compile(
    r"(?P<prefix>\b(?:curl\s+)?-u\s+[^\s:]+:)[^\s]+",
    re.I,
)

_AUTHORIZATION = re.compile(
    r"(?P<prefix>\b(?:Bearer|Basic)\s+[\"']?)[^\s,;\"']+",
    re.I,
)

_GITHUB_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")

_PROVIDER_KEY = re.compile(
    r"\b(?:"
    r"sk-(?:proj-|ant-[A-Za-z0-9_-]*-)?[A-Za-z0-9_-]{16,}"
    r"|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|npm_[A-Za-z0-9]{36}"
    r")\b"
)

_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")

_AWS_SECRET_ASSIGNMENT = re.compile(
    r"(?P<prefix>[\"']?\b(?:AWS_SECRET_ACCESS_KEY|aws_secret_access_key)"
    r"\b[\"']?\s*[=:]\s*[\"']?)[^\s,;\"'}]+",
    re.I,
)

# Secret-related environment variable names can have prefixes/suffixes.
#
# Examples:
# DB_PASSWORD
# OPENAI_API_KEY
# OPENAI_API_KEY_PROD
# DATABASE_PASSWORD_BACKUP
# SLACK_BOT_TOKEN
# MY_SECRET
#
# `pwd` is handled separately by _PWD_ASSIGNMENT.
#
# Plain `token:` is intentionally not matched because it can be normal prose
# such as `the token: refresh flow`. However, quoted JSON keys such as
# `"token": "abc123"` are still treated as secret assignments.
_ASSIGNMENT = re.compile(
    r"(?P<prefix>"
    r"(?:"
    # password / passwd / secret / api-key style assignments
    r"[\"']?(?<![A-Za-z0-9])"
    r"(?:[A-Za-z0-9]+[_-]){0,8}"
    r"(?:password|passwd|secret|api[_-]?key)"
    r"(?:[_-][A-Za-z0-9]+)*"
    r"[\"']?\s*[=:]\s*[\"']?"
    r"|"
    # token assignments using `=`
    r"[\"']?"
    r"(?:[A-Za-z0-9]+[_-]){0,8}"
    r"token"
    r"(?:[_-][A-Za-z0-9]+)*"
    r"[\"']?\s*=\s*[\"']?"
    r"|"
    # quoted JSON token keys using `:`
    r"[\"']token[\"']\s*:\s*[\"']?"
    r"|"
    # YAML/config-style token keys using `:`.
    # Restrict this to the beginning of a line so prose such as
    # `the token: refresh flow` is not treated as a secret.
    r"^[ \t]*"
    r"(?:[A-Za-z0-9]+[_-]){0,8}"
    r"token"
    r"(?:[_-][A-Za-z0-9]+)*"
    r"\s*:\s*[\"']?"
    r")"
    r")"
    r"[^\s,;\"'}]+",
    re.I | re.MULTILINE,
)

# `pwd` is treated as a secret only when used with `=`.
# This avoids redacting normal text such as:
# pwd: /home/user/project
_PWD_ASSIGNMENT = re.compile(
    r"(?P<prefix>[\"']?\bpwd[\"']?\s*=\s*[\"']?)"
    r"[^\s,;\"'}]+",
    re.I,
)

# A real JWT has base64url-encoded JSON in its first two segments,
# so both segments start with `eyJ`.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\b")


def _replace_with_prefix(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{REDACTED}"


def redact_text(text: str) -> str:
    """Redact common credentials while retaining surrounding diagnostic context."""

    value = _PRIVATE_KEY.sub(REDACTED, text)

    value = _URL_PASSWORD.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}@",
        value,
    )

    value = _CURL_USER_PASSWORD.sub(
        _replace_with_prefix,
        value,
    )

    value = _AUTHORIZATION.sub(
        _replace_with_prefix,
        value,
    )

    value = _GITHUB_TOKEN.sub(
        REDACTED,
        value,
    )

    value = _PROVIDER_KEY.sub(
        REDACTED,
        value,
    )

    value = _AWS_ACCESS_KEY.sub(
        REDACTED,
        value,
    )

    value = _AWS_SECRET_ASSIGNMENT.sub(
        _replace_with_prefix,
        value,
    )

    value = _ASSIGNMENT.sub(
        _replace_with_prefix,
        value,
    )

    value = _PWD_ASSIGNMENT.sub(
        _replace_with_prefix,
        value,
    )

    return _JWT.sub(
        REDACTED,
        value,
    )


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
