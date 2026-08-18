from iiwi.models.report_options import DetailLevel
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
from iiwi.summarizers.narrator import (
    NarrativeRunError,
    build_summary_prompt,
    failure_detail,
    marked_prompt,
)


def test_marked_prompt_puts_the_marker_on_the_first_line() -> None:
    result = marked_prompt("Write a report.", "narrative 2026-08-01 to 2026-08-08")

    first_line = result.splitlines()[0]
    assert first_line == f"{IIWI_SESSION_TITLE_PREFIX}narrative 2026-08-01 to 2026-08-08"
    assert result.endswith("Write a report.")


def test_marked_prompt_separates_the_marker_from_the_prompt() -> None:
    result = marked_prompt("Body.", "title")

    assert result.splitlines()[1] == ""


def test_marked_prompt_does_not_double_prefix_an_already_marked_title() -> None:
    already_marked = f"{IIWI_SESSION_TITLE_PREFIX}outcome synthesis"

    result = marked_prompt("Body.", already_marked)

    first_line = result.splitlines()[0]
    assert first_line == already_marked
    assert first_line.count(IIWI_SESSION_TITLE_PREFIX) == 1


def test_summary_prompt_does_not_name_a_harness() -> None:
    full = build_summary_prompt(7)
    brief = build_summary_prompt(7, detail=DetailLevel.BRIEF)

    assert "OpenCode" not in full
    assert "OpenCode" not in brief
    assert "session transcript" in full
    assert "session transcript" in brief


def test_summary_prompt_still_substitutes_days_and_keeps_structure() -> None:
    prompt = build_summary_prompt(14)

    assert "__DAYS__" not in prompt
    assert "last 14 days" in prompt
    assert "## Executive Summary" in prompt


def test_summary_prompt_forbids_inventing_content() -> None:
    prompt = build_summary_prompt(7)

    assert "attached transcript" in prompt


def test_summary_prompt_changes_evidence_instructions_for_brief_detail() -> None:
    brief = build_summary_prompt(7, detail=DetailLevel.BRIEF)
    full = build_summary_prompt(7, detail=DetailLevel.FULL)

    assert "concise outcomes and impact" in brief
    assert "Do not include session IDs, file lists, command lists, or Usage." in brief
    assert "#### Related Sessions" not in brief
    assert "#### Related Sessions" in full


def test_narrative_run_error_is_an_exception() -> None:
    assert issubclass(NarrativeRunError, Exception)


def test_failure_detail_prefers_stderr_when_present() -> None:
    result = failure_detail(
        "opencode: failed to connect\n",
        "Not logged in - please run /login\n",
        fallback="opencode run failed",
    )

    assert result == "opencode: failed to connect"


def test_failure_detail_falls_back_to_the_first_line_of_stdout() -> None:
    result = failure_detail(
        "",
        "Not logged in - please run /login\nSee https://example.com for details.\n",
        fallback="opencode run failed",
    )

    assert result == "Not logged in - please run /login"


def test_failure_detail_uses_the_fallback_when_both_are_empty() -> None:
    result = failure_detail("", "", fallback="opencode run failed")

    assert result == "opencode run failed"
