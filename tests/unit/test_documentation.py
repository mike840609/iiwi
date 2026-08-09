from pathlib import Path


def test_readme_documents_release_gate_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "pipx install iiwi" in readme
    assert "iiwi doctor" in readme
    assert "iiwi scan --period last-week" in readme
    assert "iiwi report --period last-week" in readme


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
        assert "iiwi config set harnesses.opencode.cli.model deepseek-r1" in text
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

    assert documented <= known, f"documented but not settable: {documented - known}"


def test_readmes_document_privacy_controls() -> None:
    for path in (Path("README.md"), Path("README.zh-TW.md")):
        text = path.read_text(encoding="utf-8")
        assert "--sanitize" in text
        assert "--no-llm" in text
        assert "--allow-remote-llm" not in text


def test_readmes_document_the_local_opencode_narrative() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "opencode run" in readme
    assert "OPENAPI" not in readme
    assert "opencode run" in readme_zh_tw


def test_configuration_documents_opencode_sanitize_setting() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "IIWI_HARNESSES__OPENCODE__CLI__SANITIZE" in configuration


def test_configuration_documents_opencode_run_settings() -> None:
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")

    assert "IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS" in configuration
    assert "IIWI_HARNESSES__OPENCODE__CLI__MODEL" in configuration


def test_privacy_doc_warns_about_raw_export_and_dry_run() -> None:
    privacy = Path("docs/privacy.md").read_text(encoding="utf-8").casefold()

    assert "raw" in privacy
    assert "--dry-run" in privacy
    assert "opencode run" in privacy


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
        assert "`run`" in text


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
        # Asserted in English for both READMEs, because the zh-TW one keeps the
        # terminal block untranslated — that is what the terminal really prints.
        # An `or "產生報告" in text` alternative was dropped: that phrase already
        # appears in an unrelated zh-TW privacy bullet, so the moment anyone
        # translated the block the assertion would pass off that line and stop
        # guarding the zh-TW README at all.
        assert "Generate a report" in text


def test_readmes_document_the_run_dry_run_option() -> None:
    """`--dry-run` predates this work on `report`, so assert on `run`'s own line.

    A bare `"--dry-run" in text` passes on the pre-change docs and guards nothing.
    """

    readme = Path("README.md").read_text(encoding="utf-8")
    readme_zh_tw = Path("README.zh-TW.md").read_text(encoding="utf-8")

    assert "Pass `--dry-run` to print the report to the terminal" in readme
    assert "加上 `--dry-run` 會把報告印到終端機" in readme_zh_tw

def test_readme_introduces_the_iiwi_brand() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "# Iiwi" in readme
    assert "*(ee-EE-wee)*" in readme
    assert "Agent Session Intelligence for engineering work" in readme
    assert "Probe coding-agent sessions. Surface the work that matters." in readme
