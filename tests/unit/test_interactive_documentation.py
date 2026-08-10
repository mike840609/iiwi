from pathlib import Path


def test_readmes_show_key_driven_bare_command_menu() -> None:
    for path in (Path("README.md"), Path("README.zh-TW.md")):
        text = path.read_text(encoding="utf-8")
        assert "↑↓ jk │ Enter Select" in text
        assert "▶ Review Activity" in text
        assert "Generate Report" in text
        assert "═" in text
        assert "████" in text
        assert "Review Sessions" in text
        assert "Space Toggle" in text


def test_cli_reference_documents_repository_and_session_selection() -> None:
    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")

    assert "Space" in reference
    assert "repository" in reference.casefold()
    assert "individual session" in reference.casefold()
    assert "Direct subcommands remain unchanged" in reference
