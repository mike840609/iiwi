from iiwi.security.redactor import redact_text, redact_value


def test_does_not_redact_pwd_colon_or_prose_token() -> None:
    text = "pwd: /home/user/project; the token: refresh flow"

    redacted = redact_text(text)

    assert redacted == text


def test_redacts_secret_assignments_with_suffix_segments() -> None:
    cases = [
        ("OPENAI_API_KEY_PROD=production-secret", "production-secret"),
        ("DATABASE_PASSWORD_BACKUP=backup-secret", "backup-secret"),
        ("MY_TOKEN_VALUE=token-secret", "token-secret"),
    ]

    for text, secret in cases:
        redacted = redact_text(text)

        assert secret not in redacted
        assert "[REDACTED]" in redacted


def test_pwd_equals_is_still_redacted() -> None:
    redacted = redact_text("pwd=my-password")

    assert "my-password" not in redacted
    assert "pwd=[REDACTED]" in redacted


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

def test_redacts_prefixed_env_style_secrets_and_provider_tokens() -> None:
    cases = [
        ("DB_PASSWORD=hunter2", "hunter2"),
        ("export OPENAI_API_KEY=abcdef1234567890abcdef", "abcdef1234567890abcdef"),
        ("SLACK_BOT_TOKEN=xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij"),
        ("MY_SECRET=topsecretvalue", "topsecretvalue"),
        ("GITHUB_TOKEN=abc123notaghp", "abc123notaghp"),
        ("STRIPE_SECRET_KEY=sk_live_abcdefghijklmnop1234", "sk_live_abcdefghijklmnop1234"),
        ("AIzaSyA1234567890abcdefghijklmnopqrstuv", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
        ("npm_abcdefghijklmnopqrstuvwxyz0123456789", "npm_abcdefghijklmnopqrstuvwxyz0123456789"),
    ]

    for text, secret in cases:
        redacted = redact_text(text)

        assert secret not in redacted
        assert "[REDACTED]" in redacted