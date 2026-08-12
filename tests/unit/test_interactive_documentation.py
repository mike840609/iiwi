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


def test_quick_review_docs_distinguish_preview_from_generation() -> None:
    for path in (
        Path("README.md"),
        Path("docs/cli-reference.md"),
        Path("docs/evidence-first-quick-review.md"),
    ):
        text = path.read_text(encoding="utf-8")
        assert "p Preview" in text
        assert "g Generate" in text


def test_quick_review_guide_documents_every_shipped_review_action() -> None:
    guide = Path("docs/evidence-first-quick-review.md").read_text(encoding="utf-8")

    for key in ("Space", "e Edit", "J/K", "v Evidence", "s Split", "a Add"):
        assert key in guide
    assert "More candidates" in guide
    assert "Ungrouped candidates" in guide
    assert "User-added" in guide
    assert "Blockers" in guide
    assert "Next week" in guide
    assert "Retry" in guide
    assert "session-based report" in guide


def test_quick_review_guide_states_scope_and_version_one_exclusions() -> None:
    guide = Path("docs/evidence-first-quick-review.md").read_text(encoding="utf-8")

    assert "30–60 seconds" in guide
    assert "Manager" in guide and "Engineering" in guide
    assert "Brief" in guide and "Full" in guide
    assert "No persistent drafts" in guide
    assert "No manual merge" in guide


def test_readme_distinguishes_transcript_reading_from_quick_review_synthesis() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "Claude Code / Codex (no CLI" not in readme
    assert "Quick Review outcome synthesis still uses your local `opencode run`" in readme
