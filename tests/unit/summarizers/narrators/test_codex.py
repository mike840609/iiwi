from pathlib import Path

import pytest

from iiwi.process import CommandResult
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
from iiwi.summarizers.narrator import NarrativeRunError
from iiwi.summarizers.narrators.codex import CodexNarrator


def test_run_uses_the_exec_subcommand_with_a_marked_prompt(
    tmp_path: Path, runner_factory
) -> None:
    runner = runner_factory(output="# Weekly Review\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrative = narrator.run(transcript="t", prompt="Write a report.", title="narrative")

    assert narrative == "# Weekly Review"
    args = runner.calls[0]
    assert args[0:2] == ["codex", "exec"]
    assert args[2].startswith(f"{IIWI_SESSION_TITLE_PREFIX}narrative")
    assert args[2].endswith("Write a report.")


def test_run_skips_the_git_repo_check(tmp_path: Path, runner_factory) -> None:
    """must-fix: `codex exec` refuses to run outside a Git repository, and the
    narrator's workdir is a disposable temp dir, not a repo. Without this flag
    every real codex narration fails at startup with
    "Not inside a trusted directory and --skip-git-repo-check was not
    specified." while a fake-runner test like this one stays green."""

    runner = runner_factory(output="ok\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    assert "--skip-git-repo-check" in runner.calls[0]


def test_run_passes_an_explicit_read_only_sandbox(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="ok\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    args = runner.calls[0]
    assert "--sandbox" in args
    assert args[args.index("--sandbox") + 1] == "read-only"


def test_run_sends_the_transcript_on_stdin(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="ok\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="## Project: Alpha\n", prompt="p", title="t")

    assert runner.stdin_texts == ["## Project: Alpha\n"]


def test_run_omits_the_model_flag_when_no_model_is_configured(
    tmp_path: Path, runner_factory
) -> None:
    runner = runner_factory(output="ok\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    assert "-m" not in runner.calls[0]


def test_run_appends_the_short_model_flag_when_configured(
    tmp_path: Path, runner_factory
) -> None:
    runner = runner_factory(output="ok\n")
    narrator = CodexNarrator(runner=runner, model="gpt-5.3", workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    args = runner.calls[0]
    assert args[args.index("-m") + 1] == "gpt-5.3"


def test_run_honours_a_custom_executable_path(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="ok\n")
    narrator = CodexNarrator(
        runner=runner,
        executable="/Users/someone/.codex/plugins/.plugin-appserver/codex",
        workdir=tmp_path,
    )

    narrator.run(transcript="t", prompt="p", title="t")

    assert runner.calls[0][0] == "/Users/someone/.codex/plugins/.plugin-appserver/codex"


def test_run_reports_a_failure_reason_from_stdout(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(returncode=1, output="not authenticated\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="not authenticated"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_raises_when_the_output_is_empty(tmp_path: Path, runner_factory) -> None:
    runner = runner_factory(output="")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="no output"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_launches_codex_exec_in_the_given_workdir_not_iiwis_cwd(
    tmp_path: Path, runner_factory
) -> None:
    """must-fix 1: without an explicit cwd, `codex exec` would inherit iiwi's
    own cwd and get write access to whatever repository iiwi is running in."""

    runner = runner_factory(output="ok\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    assert runner.cwds == [tmp_path]


def test_run_failure_names_the_provider_and_the_settings_that_fix_it(
    tmp_path: Path, runner_factory
) -> None:
    runner = runner_factory(returncode=1, stderr="boom")
    narrator = CodexNarrator(
        runner=runner, workdir=tmp_path, executable_configured=True
    )

    with pytest.raises(NarrativeRunError) as error:
        narrator.run(transcript="t", prompt="p", title="t")

    message = str(error.value)
    assert "codex narration failed (boom)" in message
    assert "narrator.provider" in message
    assert "narrator.executable" in message


def test_run_failure_advises_install_when_executable_is_a_default(
    tmp_path: Path, runner_factory
) -> None:
    """When the user never set narrator.executable, the failure should point at
    installing the CLI, not at a setting they never touched."""
    runner = runner_factory(returncode=1, stderr="boom")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError) as error:
        narrator.run(transcript="t", prompt="p", title="t")

    message = str(error.value)
    assert "install the codex CLI" in message
    assert "(currently" not in message


def test_run_pins_the_exact_empty_output_message(tmp_path: Path, runner_factory) -> None:
    """Characterization lock: the empty-output message is exact and stable."""
    runner = runner_factory(output="")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="codex exec produced no output"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_pins_the_failure_message_content(tmp_path: Path, runner_factory) -> None:
    """Characterization lock: a non-zero exit surfaces the narrator failure detail."""
    runner = runner_factory(returncode=1, stderr="boom")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError) as error:
        narrator.run(transcript="t", prompt="p", title="t")

    assert "codex narration failed (boom)" in str(error.value)


def test_run_wraps_output_read_oserror(tmp_path: Path, runner_factory) -> None:
    """Characterization lock: an OSError reading the output file is a NarrativeRunError."""

    class DirRunner(runner_factory):
        def run(self, args, *, stdout_path=None, stdin_text=None, cwd=None):
            del args, stdin_text, cwd
            stdout_path.mkdir()  # exists() is True, read_text raises IsADirectoryError
            return CommandResult(0, "", "")

    narrator = CodexNarrator(runner=DirRunner(), workdir=tmp_path)

    with pytest.raises(NarrativeRunError):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_failure_points_at_the_codex_desktop_docs_when_the_binary_is_missing(
    tmp_path: Path, runner_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "iiwi.summarizers.narrator.shutil.which", lambda executable: None
    )
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    runner = runner_factory(returncode=127, stderr="[Errno 2] No such file or directory: 'codex'")
    narrator = CodexNarrator(runner=runner, workdir=workdir, codex_home=codex_home)

    with pytest.raises(NarrativeRunError, match="docs/configuration.md"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_failure_omits_the_desktop_docs_when_codex_home_is_absent(
    tmp_path: Path, runner_factory
) -> None:
    runner = runner_factory(returncode=127, stderr="[Errno 2] No such file or directory: 'codex'")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path, codex_home=None)

    with pytest.raises(NarrativeRunError) as error:
        narrator.run(transcript="t", prompt="p", title="t")

    assert "docs/configuration.md" not in str(error.value)
