from iiwi.security.redactor import redact_text, redact_value


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

