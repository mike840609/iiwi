from pathlib import Path

import pytest

from iiwi.process import CommandResult
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
from iiwi.summarizers.narrator import NarrativeRunError
from iiwi.summarizers.narrators.claude import ClaudeNarrator


def test_run_sends_the_prompt_as_an_argument(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="# Weekly Review\n")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    narrative = narrator.run(
        transcript="## Project: Alpha\n",
        prompt="Write a report.",
        title="narrative 2026-08-01",
    )

    assert narrative == "# Weekly Review"
    args = runner.calls[0]
    assert args[0] == "claude"
    assert "-p" in args
    assert "--strict-mcp-config" in args
    prompt_arg = args[args.index("-p") + 1]
    assert prompt_arg.startswith(f"{IIWI_SESSION_TITLE_PREFIX}narrative 2026-08-01")
    assert prompt_arg.endswith("Write a report.")


def test_run_sends_the_transcript_on_stdin(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="ok\n")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="## Project: Alpha\n", prompt="p", title="t")

    assert runner.stdin_texts == ["## Project: Alpha\n"]


def test_run_omits_the_model_flag_when_no_model_is_configured(
    tmp_path: Path, runner_factory
) -> None:
    runner = runner_factory(output="ok\n")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    assert "--model" not in runner.calls[0]


def test_run_appends_the_model_flag_when_configured(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="ok\n")
    narrator = ClaudeNarrator(runner=runner, model="opus", workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    args = runner.calls[0]
    assert args[args.index("--model") + 1] == "opus"


def test_run_honours_a_custom_executable_path(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="ok\n")
    narrator = ClaudeNarrator(
        runner=runner,
        executable="/Users/someone/.claude/local/claude",
        workdir=tmp_path,
    )

    narrator.run(transcript="t", prompt="p", title="t")

    assert runner.calls[0][0] == "/Users/someone/.claude/local/claude"


def test_run_reports_a_login_failure_from_stdout(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(returncode=1, output="Not logged in - please run /login\n")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="Not logged in"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_raises_when_the_output_is_empty(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="no output"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_launches_claude_in_the_given_workdir_not_iiwis_cwd(
    tmp_path: Path, runner_factory
) -> None:
    """must-fix 1: without an explicit cwd, `claude -p` would inherit iiwi's
    own cwd and load the user's project CLAUDE.md, .claude/settings*.json,
    and run project hooks as a side effect of generating a report."""

    runner = runner_factory(output="ok\n")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    assert runner.cwds == [tmp_path]


def test_run_failure_names_the_provider_and_the_settings_that_fix_it(
    tmp_path: Path, runner_factory
) -> None:
    runner = runner_factory(returncode=1, stderr="boom")
    narrator = ClaudeNarrator(
        runner=runner, workdir=tmp_path, executable_configured=True
    )

    with pytest.raises(NarrativeRunError) as error:
        narrator.run(transcript="t", prompt="p", title="t")

    message = str(error.value)
    assert "claude narration failed (boom)" in message
    assert "narrator.provider" in message
    assert "narrator.executable" in message


def test_run_failure_advises_install_when_executable_is_a_default(
    tmp_path: Path, runner_factory
) -> None:
    """When the user never set narrator.executable, the failure should point at
    installing the CLI, not at a setting they never touched."""
    runner = runner_factory(returncode=1, stderr="boom")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError) as error:
        narrator.run(transcript="t", prompt="p", title="t")

    message = str(error.value)
    assert "install the claude CLI" in message
    assert "(currently" not in message


def test_run_pins_the_exact_empty_output_message(tmp_path: Path, runner_factory) -> None:
    """Characterization lock: the empty-output message is exact and stable."""
    runner = runner_factory(output="")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="claude -p produced no output"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_pins_the_failure_message_content(tmp_path: Path, runner_factory) -> None:
    """Characterization lock: a non-zero exit surfaces the narrator failure detail."""
    runner = runner_factory(returncode=1, stderr="boom")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError) as error:
        narrator.run(transcript="t", prompt="p", title="t")

    assert "claude narration failed (boom)" in str(error.value)


def test_run_wraps_output_read_oserror(tmp_path: Path, runner_factory) -> None:
    """Characterization lock: an OSError reading the output file is a NarrativeRunError."""

    class DirRunner(runner_factory):
        def run(self, args, *, stdout_path=None, stdin_text=None, cwd=None):
            del args, stdin_text, cwd
            stdout_path.mkdir()  # exists() is True, read_text raises IsADirectoryError
            return CommandResult(0, "", "")

    narrator = ClaudeNarrator(runner=DirRunner(), workdir=tmp_path)

    with pytest.raises(NarrativeRunError):
        narrator.run(transcript="t", prompt="p", title="t")
