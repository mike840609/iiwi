import time

import pytest

from iiwi.security.redactor import REDACTED, redact_text, redact_value


def test_recursive_metadata_redaction() -> None:
    value = {
        "headers": {"Authorization": "Bearer abc.def.ghi"},
        "command": "curl -u mike:secret https://example.com",
    }

    redacted = redact_value(value)

    assert "abc.def.ghi" not in str(redacted)
    assert "mike:secret" not in str(redacted)
    assert "[REDACTED]" in str(redacted)


def test_redacts_provider_tokens_url_passwords_and_assignments() -> None:
    text = (
        "ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "sk-proj-abcdefghijklmnopqrstuvwxyz password=hunter2 "
        "https://mike:secret@example.com/path"
    )

    redacted = redact_text(text)

    assert "ghp_" not in redacted
    assert "hunter2" not in redacted
    assert "mike:secret" not in redacted


def test_redacts_private_key_blocks() -> None:
    text = "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"

    assert "abc123" not in redact_text(text)


def test_redacts_quoted_authorization_headers() -> None:
    text = 'Authorization: Bearer "secret_token_12345"'
    redacted = redact_text(text)
    assert "secret_token_12345" not in redacted
    assert 'Bearer "[REDACTED]"' in redacted or "Bearer [REDACTED]" in redacted


def test_redaction_preserves_json_syntax() -> None:
    text = '{"password": "my_secret_password", "token": "abc12345"}'
    redacted = redact_text(text)
    assert "my_secret_password" not in redacted
    assert "abc12345" not in redacted
    assert redacted == '{"password": "[REDACTED]", "token": "[REDACTED]"}'


def test_redacts_github_fine_grained_pat() -> None:
    text = "github_pat_11AABCDEF0123456789_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    redacted = redact_text(text)
    assert "11AABCDEF0123456789" not in redacted
    assert "[REDACTED]" in redacted


REDACTED_CASES = [
    ("DB_PASSWORD=hunter2", "hunter2"),
    ("export OPENAI_API_KEY=abcdef1234567890abcdef", "abcdef1234567890abcdef"),
    ("SLACK_BOT_TOKEN=xoxb-1234567890-abcdefghij", "xoxb-"),
    ("MY_SECRET=topsecretvalue", "topsecretvalue"),
    ("GITHUB_TOKEN=abc123notaghp", "abc123notaghp"),
    ("STRIPE_SECRET_KEY=sk_live_abcdefghijklmnop1234", "sk_live_"),
    ("db-password=hunter2", "hunter2"),
    ("AIzaSyA1234567890abcdefghijklmnopqrstuv", "AIza"),
    ("npm_abcdefghijklmnopqrstuvwxyz0123456789", "npm_"),
    ("Driver=SQL Server;Pwd=hunter2;", "hunter2"),
    ("password=hunter2", "hunter2"),
    ("api_key: abcdef", "abcdef"),
    ('{"token": "abc12345"}', "abc12345"),
    ("password: hunter2", "hunter2"),
    ("Authorization: Bearer xyz123", "xyz123"),
    ("ghp_abcdefghijklmnopqrstuvwxyz123456", "ghp_"),
    ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz", "sk-ant-"),
    ("AKIAIOSFODNN7EXAMPLE", "AKIA"),
    ("https://mike:secret@example.com/path", "mike:secret"),
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG", "wJalrXUtnFEMI"),
    ("-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----", "abc123"),
    (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
        "eyJhbGciOiJIUzI1NiJ9",
    ),
]

KEPT_CASES = [
    "pydantic_settings.BaseSettings.model_config",
    "interactive.test_controller.something_else",
    "pwd: /home/user/project",
    "TOKEN_URL=https://example.com/oauth",
    "TOKEN_EXPIRY=3600",
]


@pytest.mark.parametrize(("text", "secret"), REDACTED_CASES)
def test_redacts_secret_shapes(text: str, secret: str) -> None:
    redacted = redact_text(text)

    assert secret not in redacted
    assert REDACTED in redacted


@pytest.mark.parametrize("text", KEPT_CASES)
def test_keeps_non_secret_text(text: str) -> None:
    assert redact_text(text) == text


def test_long_separator_heavy_run_stays_linear() -> None:
    """A pasted base64url blob must not stall redaction of a narrative transcript."""

    blob = "".join("abc" + "-_"[i % 2] for i in range(12_500))

    start = time.perf_counter()
    redacted = redact_text(blob)
    elapsed = time.perf_counter() - start

    assert redacted == blob
    assert elapsed < 2.0
