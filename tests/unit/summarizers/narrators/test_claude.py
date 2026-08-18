from pathlib import Path

import pytest

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
