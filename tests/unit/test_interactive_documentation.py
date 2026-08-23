from pathlib import Path


def test_cli_reference_documents_interactive_review_controls() -> None:
    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")

    assert "Review Sessions" in reference
    assert "repository" in reference.casefold()
    assert "individual session" in reference.casefold()
    assert "p Preview" in reference
    assert "g Generate" in reference


def test_cli_reference_documents_repository_and_session_selection() -> None:
    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")

    assert "Space" in reference
    assert "repository" in reference.casefold()
    assert "individual session" in reference.casefold()
    assert "Direct subcommands remain unchanged" in reference
    assert "Review Activity" in reference
    assert "Browse Sessions" not in reference


def test_quick_review_docs_distinguish_preview_from_generation() -> None:
    for path in (
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


def test_quick_review_guide_names_daily_as_the_persistent_exception() -> None:
    guide = Path("docs/evidence-first-quick-review.md").read_text(encoding="utf-8")
    normalized = guide.casefold()

    assert "in-memory only" in normalized
    assert "daily standup" in normalized
    assert "same-day" in normalized
    assert "persistent exception" in normalized


def test_docs_distinguish_transcript_reading_from_quick_review_synthesis() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")
    normalized_configuration = " ".join(configuration.split())

    assert "Claude Code / Codex (no CLI" not in readme
    assert "Claude Code" in readme
    assert "Codex" in readme
    assert "never launches a Claude Code process" in normalized_configuration
    assert "never launches a Codex process" in normalized_configuration
    assert "Which CLI writes the prose review" in normalized_configuration
