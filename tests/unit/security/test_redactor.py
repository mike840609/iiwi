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
