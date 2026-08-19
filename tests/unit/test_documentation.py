from pathlib import Path


def test_readme_documents_release_gate_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "pipx install iiwi" in readme
    assert "iiwi doctor" in readme
    assert "iiwi scan --period last-week" in readme
    assert "iiwi report --period last-week" in readme


def test_daily_standup_is_linked_from_every_entrypoint_document() -> None:
    paths = (
        Path("README.md"),
        Path("README.zh-TW.md"),
        Path("docs/cli-reference.md"),
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "iiwi daily" in text
        assert "daily-standup.md" in text
    assert Path("docs/daily-standup.md").is_file()


def test_readme_documents_the_harness_option() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "--harness" in readme
    assert "claude-code" in readme
    assert "Codex and Claude Code are not currently supported." not in readme


def test_limitations_documents_the_codex_limits() -> None:
    """Pin the three Codex-specific limits, not just that the word appears."""

    limitations = Path("docs/limitations.md").read_text(encoding="utf-8")

    assert "Codex report claims that a command passed or failed" in limitations
    assert "Commands run from inside Codex's `exec` tool are not recorded" in limitations
    assert "session titles are lost" in limitations


def test_privacy_documents_the_codex_limits() -> None:
    """Pin the substance of the Codex privacy boundary, not just the word "Codex"."""

    privacy = Path("docs/privacy.md").read_text(encoding="utf-8")

    assert "Codex report claims a command passed or failed" in privacy
    assert "arbitrary JavaScript program" in privacy
    assert "no `exit_code` and no `stderr_empty` for a Codex command" in privacy


def test_privacy_doc_explains_the_claude_code_sanitize_gap() -> None:
    privacy = Path("docs/privacy.md").read_text(encoding="utf-8")

    assert "claude-code" in privacy or "Claude Code" in privacy
    assert "sanitize" in privacy


def test_configuration_doc_lists_the_claude_code_settings() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY" in configuration


def test_cli_reference_documents_interactive_progress() -> None:
    """The option detail moved out of the READMEs into the CLI reference."""

    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")

    assert "transient progress status" in reference
    assert "`--quiet` hides the progress status" in reference


def test_cli_reference_documents_the_report_detail_option() -> None:
    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")

    assert "`--detail LEVEL`" in reference
    assert "`--detail brief`" in reference


def test_cli_reference_documents_the_verbose_scan_session_listing() -> None:
    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")

    assert "lists each repository's session titles and working folders" in reference


def test_readmes_document_the_config_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "iiwi config set narrator.model deepseek-r1" in text
        assert "iiwi config list" in text
        assert "iiwi config unset" in text


def test_every_config_key_in_the_docs_is_one_the_cli_accepts() -> None:
    """Run every documented `config set/unset` key through the real resolver.

    Both READMEs shipped `config set opencode.cli.model ...` for several
    releases. The accepted key is `harnesses.opencode.cli.model`, so the
    documented command exited 3 for anyone who copied it — and the test that
    was supposed to guard the section asserted the broken string verbatim,
    pinning the bug in place. Only resolving the key can catch that.
    """

    import re

    from iiwi.config_store import resolve_key

    documented: set[str] = set()
    for name in (
        "README.md",
        "README.zh-TW.md",
        "docs/configuration.md",
        "docs/cli-reference.md",
    ):
        text = Path(name).read_text(encoding="utf-8")
        documented.update(
            re.findall(r"iiwi config (?:set|unset) ([a-z0-9_]+(?:\.[a-z0-9_]+)+)", text)
        )

    assert documented, "no documented config keys found; the pattern stopped matching"
    for key in sorted(documented):
        resolve_key(key)  # raises on an unknown or misspelled setting


def test_configuration_doc_explains_the_file_and_its_precedence() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "config.env" in configuration
    assert "IIWI_CONFIG_FILE" in configuration
    assert "iiwi config path" in configuration
    # The order is the whole contract of the file.
    assert "environment variable, then the settings file, then the default" in configuration


def test_every_variable_in_the_configuration_doc_is_a_real_setting() -> None:
    """Catch a documented setting the model dropped or renamed."""

    import re

    from iiwi.config_store import setting_keys

    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"IIWI_[A-Z0-9_]+", configuration))
    known = {setting.variable for setting in setting_keys()}
    known.add("IIWI_CONFIG_FILE")

    assert documented, "no documented variables found; the pattern stopped matching"
    assert documented <= known, f"documented but not settable: {documented - known}"


def test_readmes_document_privacy_controls() -> None:
    for path in (Path("README.md"), Path("README.zh-TW.md")):
        text = path.read_text(encoding="utf-8")
        assert "--sanitize" in text
        assert "--no-llm" in text
        assert "--allow-remote-llm" not in text


def test_readmes_document_the_resolved_narration_cli() -> None:
    """The narrator is no longer hardcoded to opencode; the READMEs must say so."""

    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "narrator.provider" in text
    assert "OPENAPI" not in readme
    # The old claim was that narration always runs a local `opencode run`,
    # regardless of harness. That is what this change makes false.
    assert "the narrative still comes from your local `opencode run`" not in readme
    assert "the narrative still comes from your local `opencode run`" not in readme_zh_tw


def test_readmes_document_the_local_narration_clis() -> None:
    """Both READMEs must name every CLI that can write the narrative.

    Replaces an earlier test that asserted `opencode run` specifically; narration
    is no longer OpenCode-only. The OPENAPI guard is carried over from it — that
    typo reached the README once.
    """

    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "`opencode`" in text
        assert "`claude`" in text
        assert "`codex`" in text
        assert "OPENAPI" not in text


def test_configuration_documents_opencode_sanitize_setting() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "IIWI_HARNESSES__OPENCODE__CLI__SANITIZE" in configuration


def test_configuration_documents_narrator_settings() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "`narrator.provider`" in configuration
    assert "`narrator.executable`" in configuration
    assert "`narrator.model`" in configuration
    assert "`narrator.timeout_seconds`" in configuration
    assert "IIWI_NARRATOR__PROVIDER" in configuration


def test_configuration_still_documents_the_deprecated_opencode_run_settings() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS" in configuration
    assert "IIWI_HARNESSES__OPENCODE__CLI__MODEL" in configuration
    assert "deprecated" in configuration.casefold()


def test_configuration_documents_the_codex_desktop_cli_location() -> None:
    """The doctor message points here, so the section must exist."""

    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "Codex desktop" in configuration
    assert ".plugin-appserver" in configuration


def test_configuration_documents_quick_review_report_type_exactly() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "`report.quick_review_report_type`" in configuration
    assert "`IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE`" in configuration
    assert "iiwi config set report.quick_review_report_type manager" in configuration


def test_privacy_doc_warns_about_raw_export_and_dry_run() -> None:
    privacy = Path("docs/privacy.md").read_text(encoding="utf-8").casefold()

    assert "raw" in privacy
    assert "--dry-run" in privacy
    assert "narration cli" in privacy


def test_privacy_doc_does_not_claim_opencode_run_narrates_unconditionally() -> None:
    """Narration is provider-dependent; pin that this doc stopped overclaiming.

    Every prior mention of `opencode run` as *the* narrator was made false by
    provider resolution (opencode/claude/codex) landing underneath report
    narration. The substantive guarantees — local subprocess, no API key,
    redaction before invocation, `--no-llm` skips it — must survive; only the
    hardcoded tool name should be gone.
    """

    privacy = Path("docs/privacy.md").read_text(encoding="utf-8")

    assert "opencode run" not in privacy
    assert "narration CLI" in privacy
    assert "no API key is read" in privacy


def test_other_current_docs_do_not_claim_opencode_run_narrates() -> None:
    """Anti-rot net for the fix-round-1 sweep beyond privacy.md/configuration.md.

    A substring check, not an exact-sentence pin: these files legitimately keep
    `opencode db`, `opencode export`, `opencode stats`, and `--sanitize` for the
    OpenCode *reading* path — none of those contain the string "opencode run".
    Only the narration-specific claim that opencode run is *the* narrator is
    banned.
    """

    for name in (
        "docs/cli-reference.md",
        "docs/guides.md",
        "docs/limitations.md",
        "docs/evidence-first-quick-review.md",
        "SECURITY.md",
        "docs/assets/architecture.mmd",
    ):
        text = Path(name).read_text(encoding="utf-8")
        assert "opencode run" not in text, f"{name} still claims opencode run narrates"


def test_readmes_document_the_interactive_config_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "iiwi config init" in text


def test_cli_reference_lists_every_config_subcommand() -> None:
    """The subcommand list moved out of the READMEs into the CLI reference."""

    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")

    assert "`path`, `list`, `init`, `set`, `unset`" in reference


def test_readmes_document_the_interactive_run_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        assert "iiwi run" in text


def test_configuration_doc_explains_what_an_empty_answer_means() -> None:
    """The prompt's Enter key and `config set <key> ""` mean different things."""

    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "iiwi config init" in configuration
    assert 'an empty answer means "leave this as it is", not "erase it"' in configuration
    # Prompting in CI must fail rather than read stdin. Asserted without the
    # surrounding line break, so reflowing the paragraph does not break it.
    assert "rather than reading from stdin" in configuration


def test_readmes_document_the_interactive_menu() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    for text in (readme, readme_zh_tw):
        # Running the command bare now prompts rather than printing help, so
        # both the menu and the way to still get help must be documented.
        assert "iiwi --help" in text
        # The terminal menu stays in English in both READMEs.
        assert "Generate Report" in text


def test_readmes_document_the_run_dry_run_option() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "`--dry-run`" in readme
    assert "terminal" in readme.casefold()
    assert "without writing" in readme
    assert "`--dry-run`" in readme_zh_tw
    assert "終端機" in readme_zh_tw
    assert "不會寫入" in readme_zh_tw


def test_readmes_state_the_pronunciation() -> None:
    for path in ("README.md", "README.zh-TW.md"):
        assert "ee-wee" in Path(path).read_text(encoding="utf-8")


def test_daily_docs_describe_available_harnesses() -> None:
    """Daily scans available (enabled and readable) harnesses, not all enabled ones."""

    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")
    daily = Path("docs/daily-standup.md").read_text(encoding="utf-8")

    for text in (reference, daily):
        assert "available" in text
        assert "every enabled harness" not in text


def test_cli_reference_documents_the_verbose_performance_summary() -> None:
    """A diagnostic nobody knows about diagnoses nothing."""

    reference = Path("docs/cli-reference.md").read_text(encoding="utf-8")

    assert "Performance" in reference
    assert "stderr" in reference


def test_guides_show_what_the_verbose_performance_summary_looks_like() -> None:
    guides = Path("docs/guides.md").read_text(encoding="utf-8")

    assert "Performance" in guides
    assert "Narration" in guides
    assert "Transcript" in guides

