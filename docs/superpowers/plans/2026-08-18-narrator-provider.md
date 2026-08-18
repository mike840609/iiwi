# Narrator Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let iiwi produce report prose with `claude` or `codex` instead of requiring the `opencode` executable, and pick a harness that is actually installed rather than one that is merely enabled.

**Architecture:** A `NarrativeRunner` protocol with three CLI adapters replaces the hardcoded `OpenCodeRunner` dependency. The provider is derived from the selected harness unless `narrator.provider` says otherwise. A single `is_available` predicate per harness, defined beside its source, drives all six places that pick or offer a harness.

**Tech Stack:** Python 3.14, pydantic / pydantic-settings, typer, pytest, `uv` for running tasks.

**Spec:** `docs/2026-08-18-narrator-provider-design.md`

## Global Constraints

- No new runtime dependency. Every provider is a CLI the user already installed; no API keys, no network clients.
- Never break existing configuration. `harnesses.opencode.cli.model` and `.run_timeout_seconds` keep working as deprecated fallbacks; a settings file that only names them must resolve exactly as it does today.
- `src/iiwi/harnesses/` must not import `src/iiwi/summarizers/`. Task 12 pins this.
- Fallbacks to `harnesses.opencode.cli.*` apply only when the resolved provider is `opencode`.
- `Harness` declaration order is `OPENCODE`, `CLAUDE_CODE`, `CODEX` (`src/iiwi/cli.py:63-66`). "First" always means first in this order.
- Run tests with `uv run pytest`. Run lint with `uv run ruff check` and types with `uv run mypy src` if those are configured; do not add new tooling.
- Comments only where intent is non-obvious, matching the density of surrounding code.

---

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `src/iiwi/summarizers/narrator.py` | `NarrativeRunner` protocol, `NarrativeRunError`, the runner protocol adapters accept, the `iiwi-internal:` marker helper, and the weekly prompt templates |
| `src/iiwi/summarizers/narrators/__init__.py` | Package marker |
| `src/iiwi/summarizers/narrators/claude.py` | `ClaudeNarrator` |
| `src/iiwi/summarizers/narrators/codex.py` | `CodexNarrator` |
| `tests/unit/summarizers/test_narrator.py` | Contract, marker helper, prompt templates |
| `tests/unit/summarizers/narrators/test_claude.py` | Claude adapter argv/stdin |
| `tests/unit/summarizers/narrators/test_codex.py` | Codex adapter argv/stdin |
| `tests/unit/test_layering.py` | Import-direction invariant |

**Modified:**

| File | Change |
| --- | --- |
| `src/iiwi/process.py` | `CommandRunner.run` accepts `stdin_text` |
| `src/iiwi/summarizers/opencode_run.py` | Keeps only the OpenCode adapter; marker prepend; failure message falls back to stdout |
| `src/iiwi/config.py` | `NarratorSettings`; deprecate two OpenCode CLI fields |
| `src/iiwi/harnesses/opencode/source.py` | `is_available` |
| `src/iiwi/harnesses/claude_code/source.py` | `is_available` |
| `src/iiwi/harnesses/codex/source.py` | `is_available` |
| `src/iiwi/cli.py` | `_available_harnesses`, `_default_harness`, `_build_narrator`, optional `--harness`, deprecation notice |
| `src/iiwi/interactive/cli_actions.py` | Harness defaults, cycle list, Daily scanner set, narrator construction |
| `src/iiwi/services/report.py` | `NarrativeRunner` type, provider-neutral messages |
| `src/iiwi/services/outcomes.py` | `NarrativeRunner` type |
| `src/iiwi/services/doctor.py` | Unconditional narrator row |
| `src/iiwi/sessions/filtering.py` | Second self-authored signal |
| `src/iiwi/interactive/render.py` | Settings descriptions |
| `docs/configuration.md` | `narrator.*`, deprecations, Codex desktop section |
| `tests/unit/test_documentation.py` | Assert new and deprecated keys |

---

### Task 1: Give CommandRunner an stdin channel

The Claude and Codex adapters pass the transcript on stdin. `CommandRunner.run` currently exposes only `args` and `stdout_path`, so nothing else in this plan can work until it accepts input. This gap was found while planning; it is not named in the spec.

**Files:**
- Modify: `src/iiwi/process.py:22-98`
- Test: `tests/unit/test_process.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CommandRunner.run(args: list[str], *, stdout_path: Path | None = None, stdin_text: str | None = None) -> CommandResult`. When `stdin_text` is `None` the child inherits no input, exactly as today.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_process.py`:

```python
def test_run_feeds_stdin_text_to_the_child() -> None:
    runner = CommandRunner(timeout_seconds=10.0)

    result = runner.run(
        ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"],
        stdin_text="hello",
    )

    assert result.returncode == 0
    assert result.stdout == "HELLO"


def test_run_feeds_stdin_text_when_redirecting_stdout(tmp_path: Path) -> None:
    runner = CommandRunner(timeout_seconds=10.0)
    destination = tmp_path / "out.txt"

    result = runner.run(
        ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        stdout_path=destination,
        stdin_text="piped body",
    )

    assert result.returncode == 0
    assert destination.read_text(encoding="utf-8") == "piped body"
    assert result.stdout == "piped body"


def test_run_without_stdin_text_is_unchanged() -> None:
    runner = CommandRunner(timeout_seconds=10.0)

    result = runner.run(["python3", "-c", "print('no stdin needed')"])

    assert result.returncode == 0
    assert result.stdout.strip() == "no stdin needed"
```

If `tests/unit/test_process.py` does not exist, create it with these imports at the top:

```python
from pathlib import Path

from iiwi.process import CommandRunner
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_process.py -v`
Expected: FAIL with `TypeError: run() got an unexpected keyword argument 'stdin_text'` for the first two tests.

- [ ] **Step 3: Add the parameter**

In `src/iiwi/process.py`, change the signature and both `subprocess.run` calls:

```python
    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult:
```

In the `stdout_path is None` branch, add `input=stdin_text` to the `subprocess.run` call. In the `else` branch, which runs in bytes mode, add:

```python
                bytes_completed = subprocess.run(
                    args,
                    check=False,
                    input=None if stdin_text is None else stdin_text.encode("utf-8"),
                    stdout=out_file,
                    stderr=subprocess.PIPE,
                    timeout=self._timeout_seconds,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
```

Extend the docstring with one sentence: `stdin_text` is written to the child's stdin and closed, so a provider that reads its transcript from a pipe sees EOF.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_process.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite to confirm nothing regressed**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/process.py tests/unit/test_process.py
git commit -m "feat: let CommandRunner write text to a child's stdin"
```

---

### Task 2: Establish the narration contract

Create the module every adapter implements, and move the prompt templates out of the OpenCode-specific module. The templates currently tell the model it is reading an "OpenCode session transcript" even when the sessions came from Codex; that wording is removed here.

**Files:**
- Create: `src/iiwi/summarizers/narrator.py`
- Modify: `src/iiwi/summarizers/opencode_run.py:1-158`
- Create: `tests/unit/summarizers/test_narrator.py`
- Modify: `tests/unit/summarizers/test_opencode_run.py:1-58`

**Interfaces:**
- Consumes: `CommandResult` from Task 1's module (unchanged import).
- Produces:
  - `class NarrativeRunner(Protocol)` with `run(self, *, transcript: str, prompt: str, title: str) -> str`
  - `class NarrativeRunError(Exception)`
  - `class CommandRunnerLike(Protocol)` with `run(self, args: list[str], *, stdout_path: Path | None = ..., stdin_text: str | None = ...) -> CommandResult`
  - `def marked_prompt(prompt: str, title: str) -> str`
  - `def build_summary_prompt(days: int, detail: DetailLevel = DetailLevel.FULL) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/summarizers/test_narrator.py`:

```python
from iiwi.models.report_options import DetailLevel
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
from iiwi.summarizers.narrator import (
    NarrativeRunError,
    build_summary_prompt,
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


def test_summary_prompt_does_not_name_a_harness() -> None:
    full = build_summary_prompt(7)
    brief = build_summary_prompt(7, detail=DetailLevel.BRIEF)

    assert "OpenCode" not in full
    assert "OpenCode" not in brief
    assert "attached session transcript" in full
    assert "attached session transcript" in brief


def test_summary_prompt_still_substitutes_days_and_keeps_structure() -> None:
    prompt = build_summary_prompt(14)

    assert "__DAYS__" not in prompt
    assert "last 14 days" in prompt
    assert "## Executive Summary" in prompt


def test_narrative_run_error_is_an_exception() -> None:
    assert issubclass(NarrativeRunError, Exception)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/summarizers/test_narrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'iiwi.summarizers.narrator'`

- [ ] **Step 3: Create the module**

Create `src/iiwi/summarizers/narrator.py`. Move `_TEMPLATE`, `_BRIEF_TEMPLATE` and `build_summary_prompt` verbatim from `src/iiwi/summarizers/opencode_run.py:18-157`, then change only the two brand-naming lines:

- Line 18-19 of the original becomes: `"""Create a concise software engineering weekly report from the attached\nsession transcript and usage statistics.`
- Line 105-106 of the original becomes: `_BRIEF_TEMPLATE = """Create a concise weekly work update from the attached\nsession transcript.`

The module header and the new declarations:

```python
"""The narration contract shared by every provider adapter.

The weekly narrative is produced by a coding-agent CLI the user already has
installed, so no API key, network endpoint, or extra dependency is required. A
prompt and a grouped transcript go to a subprocess; the prose comes back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from iiwi.models.report_options import DetailLevel
from iiwi.process import CommandResult
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX


class NarrativeRunError(Exception):
    """A provider CLI could not produce a narrative."""


class NarrativeRunner(Protocol):
    def run(self, *, transcript: str, prompt: str, title: str) -> str: ...


class CommandRunnerLike(Protocol):
    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = ...,
        stdin_text: str | None = ...,
    ) -> CommandResult: ...


def marked_prompt(prompt: str, title: str) -> str:
    """Prefix the prompt with the marker that keeps iiwi's runs out of reports.

    Only `opencode run` accepts `--title`; Claude Code and Codex title sessions
    from model output. Putting the marker in the prompt is the one signal every
    harness records verbatim, so `is_iiwi_authored` can see it everywhere.
    """

    return f"{IIWI_SESSION_TITLE_PREFIX}{title}\n\n{prompt}"
```

- [ ] **Step 4: Point the OpenCode module at the new home**

In `src/iiwi/summarizers/opencode_run.py`, delete `_TEMPLATE`, `_BRIEF_TEMPLATE` and `build_summary_prompt`, replace the `OpenCodeRunError` class and the local `_Runner` protocol, and re-export for the existing callers:

```python
"""Local `opencode run` driver for the narrative report engine."""

from __future__ import annotations

from pathlib import Path

from iiwi.security.secure_files import secure_temporary_directory
from iiwi.summarizers.narrator import (
    CommandRunnerLike,
    NarrativeRunError,
    build_summary_prompt,
    marked_prompt,
)

OpenCodeRunError = NarrativeRunError

__all__ = [
    "OpenCodeRunError",
    "OpenCodeRunner",
    "build_summary_prompt",
]
```

Change `OpenCodeRunner.__init__`'s `runner: _Runner` annotation to `runner: CommandRunnerLike`.

- [ ] **Step 5: Update the existing OpenCode test imports**

In `tests/unit/summarizers/test_opencode_run.py`, change the import block at lines 9-13 to keep working through the re-export (no other change needed), and update `RecordingRunner.run` to accept the new keyword so it still matches the protocol:

```python
    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult:
        self.calls.append(args)
        self.stdin_texts.append(stdin_text)
        if stdout_path is not None and self.returncode == 0:
            stdout_path.write_text(self.output, encoding="utf-8")
        return CommandResult(self.returncode, "", self.stderr)
```

Add the new field to the dataclass:

```python
    stdin_texts: list[str | None] = field(default_factory=list)
```

Then relax the two brand assertions that now live in the narrator tests. In `test_build_summary_prompt_substitutes_days` and its siblings, delete the three `build_summary_prompt` tests from this file — they moved to `tests/unit/summarizers/test_narrator.py` in Step 1.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/summarizers/ -v`
Expected: PASS

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/iiwi/summarizers/narrator.py src/iiwi/summarizers/opencode_run.py tests/unit/summarizers/
git commit -m "refactor: extract the narration contract from the opencode driver"
```

---

### Task 3: Teach the OpenCode adapter the marker and a usable failure message

An unauthenticated `claude -p` exits 1 and writes its reason to stdout, leaving stderr empty. The current message construction discards that. Fix it in the shared shape now, on the adapter that already has tests.

**Files:**
- Modify: `src/iiwi/summarizers/opencode_run.py` (the `_run_in_workdir` body)
- Test: `tests/unit/summarizers/test_opencode_run.py`

**Interfaces:**
- Consumes: `marked_prompt`, `NarrativeRunError` from Task 2.
- Produces: `OpenCodeRunner` unchanged in signature; its argv now carries the marked prompt.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/summarizers/test_opencode_run.py`:

```python
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX


def test_run_marks_the_prompt_so_the_session_is_excluded_later(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    driver = OpenCodeRunner(runner=runner, workdir=tmp_path)

    driver.run(transcript="t", prompt="Write a report.", title="narrative 2026-08-01")

    sent_prompt = runner.calls[0][2]
    assert sent_prompt.startswith(f"{IIWI_SESSION_TITLE_PREFIX}narrative 2026-08-01")
    assert sent_prompt.endswith("Write a report.")


def test_run_reports_the_reason_when_it_arrives_on_stdout(tmp_path: Path) -> None:
    runner = RecordingRunner(returncode=1, output="Not logged in - please run /login\n")
    driver = OpenCodeRunner(runner=runner, workdir=tmp_path)

    with pytest.raises(OpenCodeRunError, match="Not logged in"):
        driver.run(transcript="t", prompt="p", title="title")
```

Note: `RecordingRunner` only writes its `output` when `returncode == 0`, so update it to always write when a `stdout_path` is given:

```python
        if stdout_path is not None:
            stdout_path.write_text(self.output, encoding="utf-8")
```

This keeps `test_run_raises_when_stdout_file_is_never_written` honest because that test uses the default empty `output` with no write... it now writes an empty file. Change that test to construct `RecordingRunner(output="")` and assert on "no output", which is already what `test_run_raises_when_output_is_empty` does — delete the now-duplicate `test_run_raises_when_stdout_file_is_never_written`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/summarizers/test_opencode_run.py -v`
Expected: FAIL — the marker assertion fails because the raw prompt is sent, and the stdout-reason test fails with `opencode run failed`.

- [ ] **Step 3: Apply both changes**

In `_run_in_workdir`, use the marked prompt in argv:

```python
            args = [
                self._executable,
                "run",
                marked_prompt(prompt, title),
                "--title",
                f"{IIWI_SESSION_TITLE_PREFIX}{title}",
                "--file",
                str(transcript_path),
                "--print-logs",
            ]
```

Import `IIWI_SESSION_TITLE_PREFIX` from `iiwi.sessions.filtering` at the top of the module.

Replace the failure branch so stdout is the fallback:

```python
            result = self._runner.run(args, stdout_path=output_path)
            narrative = ""
            if output_path.exists():
                narrative = output_path.read_text(encoding="utf-8").strip()
            if result.returncode != 0:
                raise NarrativeRunError(_failure_detail(result.stderr, narrative))
            if not narrative:
                raise NarrativeRunError("opencode run produced no output")
```

Add the shared helper to `src/iiwi/summarizers/narrator.py` so the other two adapters reuse it:

```python
def failure_detail(stderr: str, stdout: str, *, fallback: str) -> str:
    """Report why a provider failed, wherever it chose to say so.

    An unauthenticated `claude -p` exits non-zero with an empty stderr and the
    reason on stdout, so preferring stderr alone turns "please log in" into a
    generic failure.
    """

    detail = stderr.strip()
    if detail:
        return detail
    first_line = stdout.strip().splitlines()[0].strip() if stdout.strip() else ""
    return first_line or fallback
```

Then in `opencode_run.py` call it as `failure_detail(result.stderr, narrative, fallback="opencode run failed")`, importing it alongside `marked_prompt`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/summarizers/ -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. `tests/unit/sessions/test_filtering.py` still passes because the OpenCode `--title` still carries the prefix.

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/summarizers/
git commit -m "fix: keep a provider's failure reason when it lands on stdout"
```

---

### Task 4: Claude adapter

**Files:**
- Create: `src/iiwi/summarizers/narrators/__init__.py`
- Create: `src/iiwi/summarizers/narrators/claude.py`
- Create: `tests/unit/summarizers/narrators/__init__.py` (empty, only if the test tree uses packages; check whether `tests/unit/summarizers/` has one and mirror it)
- Create: `tests/unit/summarizers/narrators/test_claude.py`

**Interfaces:**
- Consumes: `CommandRunnerLike`, `NarrativeRunError`, `marked_prompt`, `failure_detail` from Task 2 and 3.
- Produces: `ClaudeNarrator(*, runner: CommandRunnerLike, executable: str = "claude", model: str = "", workdir: Path | None = None)` implementing `NarrativeRunner`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/summarizers/narrators/test_claude.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from iiwi.process import CommandResult
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
from iiwi.summarizers.narrator import NarrativeRunError
from iiwi.summarizers.narrators.claude import ClaudeNarrator


@dataclass
class RecordingRunner:
    returncode: int = 0
    stderr: str = ""
    output: str = ""
    calls: list[list[str]] = field(default_factory=list)
    stdin_texts: list[str | None] = field(default_factory=list)

    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult:
        self.calls.append(args)
        self.stdin_texts.append(stdin_text)
        if stdout_path is not None:
            stdout_path.write_text(self.output, encoding="utf-8")
        return CommandResult(self.returncode, "", self.stderr)


def test_run_sends_the_prompt_as_an_argument(tmp_path: Path) -> None:
    runner = RecordingRunner(output="# Weekly Review\n")
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


def test_run_sends_the_transcript_on_stdin(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="## Project: Alpha\n", prompt="p", title="t")

    assert runner.stdin_texts == ["## Project: Alpha\n"]


def test_run_omits_the_model_flag_when_no_model_is_configured(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    assert "--model" not in runner.calls[0]


def test_run_appends_the_model_flag_when_configured(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    narrator = ClaudeNarrator(runner=runner, model="opus", workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    args = runner.calls[0]
    assert args[args.index("--model") + 1] == "opus"


def test_run_reports_a_login_failure_from_stdout(tmp_path: Path) -> None:
    runner = RecordingRunner(returncode=1, output="Not logged in - please run /login\n")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="Not logged in"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_raises_when_the_output_is_empty(tmp_path: Path) -> None:
    runner = RecordingRunner(output="")
    narrator = ClaudeNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="no output"):
        narrator.run(transcript="t", prompt="p", title="t")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/summarizers/narrators/test_claude.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'iiwi.summarizers.narrators'`

- [ ] **Step 3: Write the adapter**

Create `src/iiwi/summarizers/narrators/__init__.py` as an empty file. Create `src/iiwi/summarizers/narrators/claude.py`:

```python
"""Claude Code narration through `claude -p`."""

from __future__ import annotations

from pathlib import Path

from iiwi.security.secure_files import secure_temporary_directory
from iiwi.summarizers.narrator import (
    CommandRunnerLike,
    NarrativeRunError,
    failure_detail,
    marked_prompt,
)


class ClaudeNarrator:
    """Run `claude -p` against a grouped transcript and return its prose."""

    def __init__(
        self,
        *,
        runner: CommandRunnerLike,
        executable: str = "claude",
        model: str = "",
        workdir: Path | None = None,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._model = model
        self._workdir = workdir

    def run(self, *, transcript: str, prompt: str, title: str) -> str:
        if self._workdir is not None:
            return self._run_in_workdir(
                self._workdir, transcript=transcript, prompt=prompt, title=title
            )
        try:
            with secure_temporary_directory() as workdir:
                return self._run_in_workdir(
                    workdir, transcript=transcript, prompt=prompt, title=title
                )
        except OSError as exc:
            raise NarrativeRunError(str(exc)) from exc

    def _run_in_workdir(
        self,
        workdir: Path,
        *,
        transcript: str,
        prompt: str,
        title: str,
    ) -> str:
        try:
            output_path = workdir / "summary.md"
            # No --mcp-config alongside it, so this disables MCP servers for the
            # run. --bare would also isolate the run but disables OAuth, which
            # is the credential path iiwi relies on.
            args = [
                self._executable,
                "-p",
                marked_prompt(prompt, title),
                "--strict-mcp-config",
            ]
            if self._model:
                args += ["--model", self._model]
            result = self._runner.run(
                args, stdout_path=output_path, stdin_text=transcript
            )
            narrative = ""
            if output_path.exists():
                narrative = output_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise NarrativeRunError(str(exc)) from exc
        if result.returncode != 0:
            raise NarrativeRunError(
                failure_detail(result.stderr, narrative, fallback="claude -p failed")
            )
        if not narrative:
            raise NarrativeRunError("claude -p produced no output")
        return narrative
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/summarizers/narrators/test_claude.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/summarizers/narrators/ tests/unit/summarizers/narrators/
git commit -m "feat: narrate weekly reports with claude -p"
```

---

### Task 5: Codex adapter

`codex exec` takes the prompt as an argument and appends piped stdin as a `<stdin>` block, so it is structurally identical to the Claude adapter apart from the subcommand and the short model flag.

**Files:**
- Create: `src/iiwi/summarizers/narrators/codex.py`
- Create: `tests/unit/summarizers/narrators/test_codex.py`

**Interfaces:**
- Consumes: same as Task 4.
- Produces: `CodexNarrator(*, runner: CommandRunnerLike, executable: str = "codex", model: str = "", workdir: Path | None = None)` implementing `NarrativeRunner`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/summarizers/narrators/test_codex.py` with the same `RecordingRunner` dataclass as Task 4 Step 1 (repeated in full, since these files are read independently):

```python
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from iiwi.process import CommandResult
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
from iiwi.summarizers.narrator import NarrativeRunError
from iiwi.summarizers.narrators.codex import CodexNarrator


@dataclass
class RecordingRunner:
    returncode: int = 0
    stderr: str = ""
    output: str = ""
    calls: list[list[str]] = field(default_factory=list)
    stdin_texts: list[str | None] = field(default_factory=list)

    def run(
        self,
        args: list[str],
        *,
        stdout_path: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult:
        self.calls.append(args)
        self.stdin_texts.append(stdin_text)
        if stdout_path is not None:
            stdout_path.write_text(self.output, encoding="utf-8")
        return CommandResult(self.returncode, "", self.stderr)


def test_run_uses_the_exec_subcommand_with_a_marked_prompt(tmp_path: Path) -> None:
    runner = RecordingRunner(output="# Weekly Review\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrative = narrator.run(transcript="t", prompt="Write a report.", title="narrative")

    assert narrative == "# Weekly Review"
    args = runner.calls[0]
    assert args[0:2] == ["codex", "exec"]
    assert args[2].startswith(f"{IIWI_SESSION_TITLE_PREFIX}narrative")
    assert args[2].endswith("Write a report.")


def test_run_sends_the_transcript_on_stdin(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="## Project: Alpha\n", prompt="p", title="t")

    assert runner.stdin_texts == ["## Project: Alpha\n"]


def test_run_omits_the_model_flag_when_no_model_is_configured(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    assert "-m" not in runner.calls[0]


def test_run_appends_the_short_model_flag_when_configured(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    narrator = CodexNarrator(runner=runner, model="gpt-5.3", workdir=tmp_path)

    narrator.run(transcript="t", prompt="p", title="t")

    args = runner.calls[0]
    assert args[args.index("-m") + 1] == "gpt-5.3"


def test_run_honours_a_custom_executable_path(tmp_path: Path) -> None:
    runner = RecordingRunner(output="ok\n")
    narrator = CodexNarrator(
        runner=runner,
        executable="/Users/someone/.codex/plugins/.plugin-appserver/codex",
        workdir=tmp_path,
    )

    narrator.run(transcript="t", prompt="p", title="t")

    assert runner.calls[0][0] == "/Users/someone/.codex/plugins/.plugin-appserver/codex"


def test_run_reports_a_failure_reason_from_stdout(tmp_path: Path) -> None:
    runner = RecordingRunner(returncode=1, output="not authenticated\n")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="not authenticated"):
        narrator.run(transcript="t", prompt="p", title="t")


def test_run_raises_when_the_output_is_empty(tmp_path: Path) -> None:
    runner = RecordingRunner(output="")
    narrator = CodexNarrator(runner=runner, workdir=tmp_path)

    with pytest.raises(NarrativeRunError, match="no output"):
        narrator.run(transcript="t", prompt="p", title="t")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/summarizers/narrators/test_codex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'iiwi.summarizers.narrators.codex'`

- [ ] **Step 3: Write the adapter**

Create `src/iiwi/summarizers/narrators/codex.py`:

```python
"""Codex narration through `codex exec`."""

from __future__ import annotations

from pathlib import Path

from iiwi.security.secure_files import secure_temporary_directory
from iiwi.summarizers.narrator import (
    CommandRunnerLike,
    NarrativeRunError,
    failure_detail,
    marked_prompt,
)


class CodexNarrator:
    """Run `codex exec` against a grouped transcript and return its prose."""

    def __init__(
        self,
        *,
        runner: CommandRunnerLike,
        executable: str = "codex",
        model: str = "",
        workdir: Path | None = None,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._model = model
        self._workdir = workdir

    def run(self, *, transcript: str, prompt: str, title: str) -> str:
        if self._workdir is not None:
            return self._run_in_workdir(
                self._workdir, transcript=transcript, prompt=prompt, title=title
            )
        try:
            with secure_temporary_directory() as workdir:
                return self._run_in_workdir(
                    workdir, transcript=transcript, prompt=prompt, title=title
                )
        except OSError as exc:
            raise NarrativeRunError(str(exc)) from exc

    def _run_in_workdir(
        self,
        workdir: Path,
        *,
        transcript: str,
        prompt: str,
        title: str,
    ) -> str:
        try:
            output_path = workdir / "summary.md"
            # `codex exec` appends piped stdin to the prompt as a <stdin> block,
            # which is exactly the prompt-plus-transcript shape iiwi needs.
            args = [self._executable, "exec", marked_prompt(prompt, title)]
            if self._model:
                args += ["-m", self._model]
            result = self._runner.run(
                args, stdout_path=output_path, stdin_text=transcript
            )
            narrative = ""
            if output_path.exists():
                narrative = output_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise NarrativeRunError(str(exc)) from exc
        if result.returncode != 0:
            raise NarrativeRunError(
                failure_detail(result.stderr, narrative, fallback="codex exec failed")
            )
        if not narrative:
            raise NarrativeRunError("codex exec produced no output")
        return narrative
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/summarizers/narrators/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/summarizers/narrators/codex.py tests/unit/summarizers/narrators/test_codex.py
git commit -m "feat: narrate weekly reports with codex exec"
```

---

### Task 6: Narrator settings and the deprecation of two OpenCode fields

**Files:**
- Modify: `src/iiwi/config.py:11-30`, `:114-129`
- Modify: `src/iiwi/cli.py:95` (`_load_settings`)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class NarratorSettings(BaseModel)` with `provider: str`, `executable: str`, `model: str`, `timeout_seconds: float | None`
  - `AppSettings.narrator: NarratorSettings`
  - `DEFAULT_NARRATOR_TIMEOUT_SECONDS: float`
  - `cli._load_settings()` unchanged in signature; now writes one stderr notice when a deprecated key holds a value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config.py`:

```python
from iiwi.config import AppSettings, NarratorSettings


def test_narrator_defaults_are_all_unset() -> None:
    settings = NarratorSettings()

    assert settings.provider == ""
    assert settings.executable == ""
    assert settings.model == ""
    assert settings.timeout_seconds is None


def test_narrator_timeout_rejects_non_positive_values() -> None:
    with pytest.raises(ValidationError):
        NarratorSettings(timeout_seconds=0)


def test_narrator_timeout_accepts_a_real_value() -> None:
    assert NarratorSettings(timeout_seconds=42.0).timeout_seconds == 42.0


def test_narrator_settings_hang_off_the_app_settings(monkeypatch) -> None:
    monkeypatch.setenv("IIWI_NARRATOR__PROVIDER", "claude")
    monkeypatch.setenv("IIWI_NARRATOR__MODEL", "opus")

    settings = AppSettings()

    assert settings.narrator.provider == "claude"
    assert settings.narrator.model == "opus"


def test_narrator_keys_are_settable_through_the_config_store() -> None:
    from iiwi.config_store import setting_keys

    keys = {setting.key for setting in setting_keys()}

    assert "narrator.provider" in keys
    assert "narrator.executable" in keys
    assert "narrator.model" in keys
    assert "narrator.timeout_seconds" in keys
```

Ensure `pytest` and `ValidationError` are imported at the top of the file if they are not already:

```python
import pytest
from pydantic import ValidationError
```

Create `tests/unit/test_cli_deprecation.py`:

```python
import pytest

from iiwi import cli


def test_load_settings_warns_once_about_a_deprecated_model_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "deepseek-r1")

    cli._load_settings()

    captured = capsys.readouterr()
    assert "harnesses.opencode.cli.model" in captured.err
    assert "narrator.model" in captured.err


def test_load_settings_is_silent_when_no_deprecated_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", raising=False)
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS", raising=False)

    cli._load_settings()

    assert capsys.readouterr().err == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py tests/unit/test_cli_deprecation.py -v`
Expected: FAIL with `ImportError: cannot import name 'NarratorSettings'`

- [ ] **Step 3: Add the settings model**

In `src/iiwi/config.py`, add the constant next to the existing one and the new model above `HarnessSettings`:

```python
DEFAULT_NARRATOR_TIMEOUT_SECONDS = 600.0


class NarratorSettings(BaseModel):
    """How iiwi turns a transcript into prose.

    Every field's empty value means "unset", which is what lets the provider be
    derived from the selected harness instead of configured up front.
    """

    provider: str = ""
    executable: str = ""
    model: str = ""
    # `None` rather than the default value: the resolution order has to tell an
    # unset timeout from one a user deliberately set to the same number, and
    # `gt=0` cannot express "absent".
    timeout_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
```

Mark the two moved fields on `OpenCodeCliSettings`:

```python
    run_timeout_seconds: float = Field(
        default=600.0,
        gt=0,
        allow_inf_nan=False,
        deprecated="use narrator.timeout_seconds",
    )
    model: str = Field(default="", deprecated="use narrator.model")
```

Add the section to `AppSettings`:

```python
    narrator: NarratorSettings = Field(default_factory=NarratorSettings)
```

- [ ] **Step 4: Emit the deprecation notice**

In `src/iiwi/cli.py`, extend `_load_settings`:

```python
_DEPRECATED_KEYS = {
    "harnesses.opencode.cli.model": "narrator.model",
    "harnesses.opencode.cli.run_timeout_seconds": "narrator.timeout_seconds",
}


def _warn_about_deprecated_keys(settings: AppSettings) -> None:
    """Say which key replaced a deprecated one, once, on stderr.

    Not through the report's warnings: a configuration migration printed inside
    the report body would outlive the migration in every file it was written to.
    """

    cli_settings = settings.harnesses.opencode.cli
    in_use = []
    if cli_settings.model:
        in_use.append("harnesses.opencode.cli.model")
    if "run_timeout_seconds" in cli_settings.model_fields_set:
        in_use.append("harnesses.opencode.cli.run_timeout_seconds")
    for key in in_use:
        typer.echo(
            f"Note: {key} is deprecated; use {_DEPRECATED_KEYS[key]}.",
            err=True,
        )
```

Call it at the end of `_load_settings` before returning the settings.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py tests/unit/test_cli_deprecation.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. If `tests/unit/test_documentation.py` fails on the deprecated keys, leave it failing and fix it in Task 13; note the failure in the commit message.

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/config.py src/iiwi/cli.py tests/unit/test_config.py tests/unit/test_cli_deprecation.py
git commit -m "feat: add narrator settings and deprecate the opencode narration keys"
```

---

### Task 7: One availability predicate per harness

**Files:**
- Modify: `src/iiwi/harnesses/opencode/source.py`
- Modify: `src/iiwi/harnesses/claude_code/source.py`
- Modify: `src/iiwi/harnesses/codex/source.py`
- Modify: `src/iiwi/cli.py` (near `_enabled_harnesses:945`)
- Test: `tests/unit/harnesses/test_availability.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `NarratorSettings` from Task 6 (for nothing yet; only `AppSettings` shape).
- Produces:
  - `iiwi.harnesses.opencode.source.is_available(executable: str) -> bool`
  - `iiwi.harnesses.claude_code.source.is_available(projects_directory: Path) -> bool`
  - `iiwi.harnesses.codex.source.is_available(home_directory: Path) -> bool`
  - `cli._available_harnesses(settings: AppSettings) -> list[Harness]`
  - `cli._default_harness(settings: AppSettings) -> Harness`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/harnesses/test_availability.py`:

```python
import shutil
from pathlib import Path

import pytest

from iiwi.harnesses.claude_code.source import is_available as claude_code_is_available
from iiwi.harnesses.codex.source import is_available as codex_is_available
from iiwi.harnesses.opencode.source import is_available as opencode_is_available


def test_opencode_is_available_when_the_executable_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/opencode")

    assert opencode_is_available("opencode") is True


def test_opencode_is_unavailable_when_the_executable_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    assert opencode_is_available("opencode") is False


def test_claude_code_is_available_when_the_projects_directory_exists(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()

    assert claude_code_is_available(projects) is True
    assert claude_code_is_available(tmp_path / "absent") is False


def test_codex_is_available_when_the_home_directory_exists(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    home.mkdir()

    assert codex_is_available(home) is True
    assert codex_is_available(tmp_path / "absent") is False
```

Append to `tests/unit/test_cli.py`:

```python
def test_available_harnesses_drops_the_ones_that_cannot_be_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    settings = cli.AppSettings()
    settings.harnesses.claude_code.projects_directory = projects
    settings.harnesses.codex.home_directory = tmp_path / "absent"

    assert cli._available_harnesses(settings) == [cli.Harness.CLAUDE_CODE]


def test_default_harness_prefers_opencode_when_it_is_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/opencode")
    settings = cli.AppSettings()
    settings.harnesses.claude_code.projects_directory = projects

    assert cli._default_harness(settings) == cli.Harness.OPENCODE


def test_default_harness_falls_back_to_the_first_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    settings = cli.AppSettings()
    settings.harnesses.claude_code.projects_directory = projects
    settings.harnesses.codex.home_directory = tmp_path / "absent"

    assert cli._default_harness(settings) == cli.Harness.CLAUDE_CODE


def test_default_harness_reports_what_it_checked_when_nothing_is_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    settings = cli.AppSettings()
    settings.harnesses.claude_code.projects_directory = tmp_path / "absent-projects"
    settings.harnesses.codex.home_directory = tmp_path / "absent-codex"

    with pytest.raises(ConfigurationError) as error:
        cli._default_harness(settings)

    message = str(error.value)
    assert "opencode" in message
    assert "absent-projects" in message
    assert "absent-codex" in message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/harnesses/test_availability.py tests/unit/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'is_available'`

- [ ] **Step 3: Add the three predicates**

In `src/iiwi/harnesses/opencode/source.py`, add `import shutil` and:

```python
def is_available(executable: str) -> bool:
    """Whether this harness's sessions can be read on this machine.

    OpenCode's source is the CLI itself, so the binary resolving is the same
    question as the session store existing.
    """

    return shutil.which(executable) is not None
```

In `src/iiwi/harnesses/claude_code/source.py`:

```python
def is_available(projects_directory: Path) -> bool:
    """Whether this harness's sessions can be read on this machine."""

    return projects_directory.is_dir()
```

In `src/iiwi/harnesses/codex/source.py`:

```python
def is_available(home_directory: Path) -> bool:
    """Whether this harness's sessions can be read on this machine."""

    return home_directory.is_dir()
```

- [ ] **Step 4: Add the two cli helpers**

In `src/iiwi/cli.py`, add `import shutil` at the top and, next to `_enabled_harnesses`:

```python
def _harness_is_available(settings: AppSettings, harness: Harness) -> bool:
    if harness is Harness.CLAUDE_CODE:
        return claude_code_is_available(settings.harnesses.claude_code.projects_directory)
    if harness is Harness.CODEX:
        return codex_is_available(settings.harnesses.codex.home_directory)
    return opencode_is_available(settings.harnesses.opencode.cli.executable)


def _harness_availability_detail(settings: AppSettings, harness: Harness) -> str:
    if harness is Harness.CLAUDE_CODE:
        return str(settings.harnesses.claude_code.projects_directory)
    if harness is Harness.CODEX:
        return str(settings.harnesses.codex.home_directory)
    return settings.harnesses.opencode.cli.executable


def _available_harnesses(settings: AppSettings) -> list[Harness]:
    """The enabled harnesses whose sessions this machine can actually read."""

    return [
        harness
        for harness in _enabled_harnesses(settings)
        if _harness_is_available(settings, harness)
    ]


def _default_harness(settings: AppSettings) -> Harness:
    """Pick a harness that works, preferring OpenCode so existing setups do not move."""

    available = _available_harnesses(settings)
    if Harness.OPENCODE in available:
        return Harness.OPENCODE
    if available:
        return available[0]
    checked = ", ".join(
        f"{harness.value} ({_harness_availability_detail(settings, harness)})"
        for harness in _enabled_harnesses(settings)
    )
    raise ConfigurationError(f"no harness is available; checked {checked}")
```

Import the three predicates with distinct names at the top of `cli.py`:

```python
from iiwi.harnesses.claude_code.source import is_available as claude_code_is_available
from iiwi.harnesses.codex.source import is_available as codex_is_available
from iiwi.harnesses.opencode.source import is_available as opencode_is_available
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/harnesses/test_availability.py tests/unit/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/harnesses/ src/iiwi/cli.py tests/unit/harnesses/test_availability.py tests/unit/test_cli.py
git commit -m "feat: decide harness availability from one predicate per harness"
```

---

### Task 8: Route every harness-selection site through availability

Six sites pick or offer a harness. All six move to the Task 7 helpers, and the duplicated "prefer OpenCode, else the first" expression collapses into `_default_harness`.

**Files:**
- Modify: `src/iiwi/cli.py:72-76` (`_HARNESS_OPTION`), `:954-968` (`_ask_harness`), and the three command bodies at `:429`, `:467`, `:558`
- Modify: `src/iiwi/interactive/cli_actions.py:61-95` (`_new_draft`, `_choose_harness`), `:484-497` (Daily scanners)
- Test: `tests/unit/test_cli.py`, `tests/unit/interactive/test_cli_actions.py`

**Interfaces:**
- Consumes: `cli._available_harnesses`, `cli._default_harness` from Task 7.
- Produces: `--harness` becomes `Harness | None`; every command body resolves `harness = harness or _default_harness(settings)` after loading settings.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
def test_report_without_a_harness_flag_uses_the_available_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv("IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(projects))
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    seen: list[cli.Harness] = []

    def fake_build(settings, period, output_path, no_llm, root_only=False, **kwargs):
        seen.append(kwargs["harness"])
        raise cli.NoSessionsError("stop here")

    monkeypatch.setattr(cli, "_build_report_service", fake_build)

    runner = CliRunner()
    runner.invoke(cli.app, ["report", "--days", "7"])

    assert seen == [cli.Harness.CLAUDE_CODE]
```

Append to `tests/unit/interactive/test_cli_actions.py`:

```python
def test_new_draft_starts_on_an_available_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv("IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(projects))
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent"))
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    draft = cli_actions._new_draft()

    assert draft.harness == "claude-code"


def test_choose_harness_cycles_only_available_harnesses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv("IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(projects))
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent"))
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    assert cli_actions._choose_harness("claude-code") == "claude-code"


def test_daily_builds_scanners_only_for_available_harnesses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv("IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(projects))
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent"))
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    built: list[str] = []

    def fake_scan_service(settings, period, root_only, *, harness, sanitize, progress):
        built.append(harness.value)
        return object()

    monkeypatch.setattr(cli, "_build_scan_service", fake_scan_service)

    settings = cli._load_settings()
    harnesses = [harness.value for harness in cli._available_harnesses(settings)]

    assert harnesses == ["claude-code"]
```

Add `from iiwi import cli` and `from iiwi.interactive import cli_actions` to the test file's imports if they are not already there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/interactive/test_cli_actions.py -v`
Expected: FAIL — `report` still defaults to OpenCode, `_new_draft` still returns `"opencode"`.

- [ ] **Step 3: Make `--harness` optional**

In `src/iiwi/cli.py`, change the shared option:

```python
_HARNESS_OPTION = typer.Option(
    None,
    "--harness",
    help="Coding-agent harness to read sessions from; defaults to the first available harness.",
)
```

Change the three command signatures from `harness: Harness = _HARNESS_OPTION` to `harness: Harness | None = _HARNESS_OPTION`.

In each of `doctor`, `scan` and `report`, resolve the harness immediately after `settings = _load_settings()` and move any `_validate_privacy_options` call to after that line, because it needs a concrete harness:

```python
        settings = _load_settings()
        harness = harness or _default_harness(settings)
        _validate_privacy_options(harness=harness, sanitize=sanitize)
```

`doctor` has no `_validate_privacy_options` call; it only needs the resolution line.

- [ ] **Step 4: Replace `_ask_harness`'s duplicated default**

In `src/iiwi/cli.py`, change `_ask_harness` to offer available harnesses and reuse the helper:

```python
def _ask_harness(settings: AppSettings) -> Harness:
    """Offer only the harnesses that work here; Enter keeps the default."""

    available = _available_harnesses(settings)
    default = _default_harness(settings)
    names = [harness.value for harness in available]
    typer.echo(f"Available harnesses: {', '.join(names)}")
    while True:
        answer = _prompt(f"Harness [{default.value}]")
        if not answer:
            return default
        for harness in available:
            if harness == answer:
                return harness
        typer.echo(f"  choose from: {', '.join(names)}")
```

- [ ] **Step 5: Route the interactive sites**

In `src/iiwi/interactive/cli_actions.py`, replace the duplicated expression in `_new_draft`:

```python
def _new_draft() -> ReportDraft:
    from iiwi import cli

    settings = cli._load_settings()
    now = cli._now_in_timezone(settings.report.timezone)
    harness = cli._default_harness(settings)
    label, period = _named_periods(now)[0]
    return ReportDraft(
        harness=harness.value,
        period=period,
        period_label=label,
        report_type=settings.report.quick_review_report_type,
    )
```

Change `_choose_harness` to cycle available harnesses:

```python
    settings = cli._load_settings()
    available = [harness.value for harness in cli._available_harnesses(settings)]
    if not available:
        return current
    try:
        index = available.index(current)
    except ValueError:
        return available[0]
```

Keep the remainder of the function as it is, renaming `enabled` to `available` throughout.

In `_start_daily`, change the scanner comprehension's source:

```python
                for harness in cli._available_harnesses(settings)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/interactive/test_cli_actions.py -v`
Expected: PASS

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. Integration tests that invoke `report` without `--harness` on a machine with no OpenCode now resolve differently; if any fail, they were relying on the hardcoded default and should pass `--harness opencode` explicitly.

- [ ] **Step 8: Commit**

```bash
git add src/iiwi/cli.py src/iiwi/interactive/cli_actions.py tests/
git commit -m "feat: pick a harness that is installed, not merely enabled"
```

---

### Task 9: Resolve and build the narrator

**Files:**
- Modify: `src/iiwi/cli.py` (new resolution helpers; `_build_report_service:299-304`)
- Modify: `src/iiwi/interactive/cli_actions.py:200-230`, `:439-476`
- Modify: `src/iiwi/services/report.py:29-31`, `:85`, `:186-189`, `:246-249`
- Modify: `src/iiwi/services/outcomes.py:34`, `:293`
- Test: `tests/unit/test_narrator_resolution.py`

**Interfaces:**
- Consumes: the three adapters (Tasks 3-5), `NarratorSettings` (Task 6), `_available_harnesses` and `_enabled_harnesses` (Task 7).
- Produces:
  - `cli._resolve_provider(settings: AppSettings, harness: Harness) -> str`
  - `cli._resolve_executable(settings: AppSettings, provider: str) -> str`
  - `cli._resolve_model(settings: AppSettings, provider: str) -> str`
  - `cli._resolve_timeout(settings: AppSettings, provider: str) -> float`
  - `cli._build_narrator(settings: AppSettings, harness: Harness) -> NarrativeRunner`
  - `cli._build_daily_narrator(settings: AppSettings) -> NarrativeRunner`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_narrator_resolution.py`:

```python
import shutil
from pathlib import Path

import pytest

from iiwi import cli
from iiwi.config import AppSettings
from iiwi.errors import ConfigurationError


def _settings(**narrator: object) -> AppSettings:
    settings = AppSettings()
    for name, value in narrator.items():
        setattr(settings.narrator, name, value)
    return settings


def test_provider_follows_the_harness_when_unset() -> None:
    settings = _settings()

    assert cli._resolve_provider(settings, cli.Harness.CLAUDE_CODE) == "claude"
    assert cli._resolve_provider(settings, cli.Harness.CODEX) == "codex"
    assert cli._resolve_provider(settings, cli.Harness.OPENCODE) == "opencode"


def test_configured_provider_overrides_the_harness() -> None:
    settings = _settings(provider="claude")

    assert cli._resolve_provider(settings, cli.Harness.CODEX) == "claude"


def test_unknown_provider_is_a_configuration_error() -> None:
    settings = _settings(provider="gemini")

    with pytest.raises(ConfigurationError, match="gemini"):
        cli._resolve_provider(settings, cli.Harness.CODEX)


def test_executable_defaults_to_the_provider_name() -> None:
    settings = _settings()

    assert cli._resolve_executable(settings, "claude") == "claude"
    assert cli._resolve_executable(settings, "codex") == "codex"


def test_executable_for_opencode_comes_from_the_harness_setting() -> None:
    settings = _settings()
    settings.harnesses.opencode.cli.executable = "/opt/bin/opencode"

    assert cli._resolve_executable(settings, "opencode") == "/opt/bin/opencode"


def test_configured_executable_wins_for_every_provider() -> None:
    settings = _settings(executable="/Users/x/.codex/plugins/.plugin-appserver/codex")

    assert cli._resolve_executable(settings, "codex").endswith("codex")
    assert cli._resolve_executable(settings, "opencode").endswith("codex")


def test_model_falls_back_only_for_opencode() -> None:
    settings = _settings()
    settings.harnesses.opencode.cli.model = "deepseek-r1"

    assert cli._resolve_model(settings, "opencode") == "deepseek-r1"
    assert cli._resolve_model(settings, "claude") == ""


def test_configured_model_wins() -> None:
    settings = _settings(model="opus")
    settings.harnesses.opencode.cli.model = "deepseek-r1"

    assert cli._resolve_model(settings, "opencode") == "opus"
    assert cli._resolve_model(settings, "claude") == "opus"


def test_timeout_falls_back_only_for_opencode() -> None:
    settings = _settings()
    settings.harnesses.opencode.cli.run_timeout_seconds = 45.0

    assert cli._resolve_timeout(settings, "opencode") == 45.0
    assert cli._resolve_timeout(settings, "claude") == 600.0


def test_configured_timeout_wins() -> None:
    settings = _settings(timeout_seconds=30.0)
    settings.harnesses.opencode.cli.run_timeout_seconds = 45.0

    assert cli._resolve_timeout(settings, "opencode") == 30.0


def test_build_narrator_returns_the_adapter_for_the_harness() -> None:
    from iiwi.summarizers.narrators.claude import ClaudeNarrator
    from iiwi.summarizers.narrators.codex import CodexNarrator
    from iiwi.summarizers.opencode_run import OpenCodeRunner

    settings = _settings()

    assert isinstance(cli._build_narrator(settings, cli.Harness.CLAUDE_CODE), ClaudeNarrator)
    assert isinstance(cli._build_narrator(settings, cli.Harness.CODEX), CodexNarrator)
    assert isinstance(cli._build_narrator(settings, cli.Harness.OPENCODE), OpenCodeRunner)


def test_daily_narrator_prefers_opencode_among_installed_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iiwi.summarizers.opencode_run import OpenCodeRunner

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/" + Path(name).name)

    assert isinstance(cli._build_daily_narrator(_settings()), OpenCodeRunner)


def test_daily_narrator_skips_providers_that_are_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iiwi.summarizers.narrators.claude import ClaudeNarrator

    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/local/bin/claude" if name == "claude" else None
    )

    assert isinstance(cli._build_daily_narrator(_settings()), ClaudeNarrator)


def test_daily_narrator_raises_when_no_provider_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iiwi.summarizers.narrator import NarrativeRunError

    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(NarrativeRunError, match="opencode"):
        cli._build_daily_narrator(_settings())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_narrator_resolution.py -v`
Expected: FAIL with `AttributeError: module 'iiwi.cli' has no attribute '_resolve_provider'`

- [ ] **Step 3: Add the resolution helpers**

In `src/iiwi/cli.py`:

```python
_PROVIDER_BY_HARNESS = {
    Harness.OPENCODE: "opencode",
    Harness.CLAUDE_CODE: "claude",
    Harness.CODEX: "codex",
}
_PROVIDERS = frozenset(_PROVIDER_BY_HARNESS.values())


def _resolve_provider(settings: AppSettings, harness: Harness) -> str:
    """Which CLI writes the prose. Configuration always beats the harness."""

    configured = settings.narrator.provider.strip()
    if not configured:
        return _PROVIDER_BY_HARNESS[harness]
    if configured not in _PROVIDERS:
        allowed = ", ".join(sorted(_PROVIDERS))
        raise ConfigurationError(
            f"unknown narrator.provider: {configured}; choose from {allowed}"
        )
    return configured


def _resolve_executable(settings: AppSettings, provider: str) -> str:
    # The OpenCode fallbacks below apply only to the OpenCode provider: a model
    # name left over from an OpenCode setup would be rejected by `claude --model`.
    configured = settings.narrator.executable.strip()
    if configured:
        return configured
    if provider == "opencode":
        return settings.harnesses.opencode.cli.executable
    return provider


def _resolve_model(settings: AppSettings, provider: str) -> str:
    if settings.narrator.model:
        return settings.narrator.model
    if provider == "opencode":
        return settings.harnesses.opencode.cli.model
    return ""


def _resolve_timeout(settings: AppSettings, provider: str) -> float:
    if settings.narrator.timeout_seconds is not None:
        return settings.narrator.timeout_seconds
    if provider == "opencode":
        return settings.harnesses.opencode.cli.run_timeout_seconds
    return DEFAULT_NARRATOR_TIMEOUT_SECONDS


def _narrator_for_provider(settings: AppSettings, provider: str) -> NarrativeRunner:
    executable = _resolve_executable(settings, provider)
    model = _resolve_model(settings, provider)
    runner = CommandRunner(timeout_seconds=_resolve_timeout(settings, provider))
    if provider == "claude":
        return ClaudeNarrator(runner=runner, executable=executable, model=model)
    if provider == "codex":
        return CodexNarrator(runner=runner, executable=executable, model=model)
    return OpenCodeRunner(runner=runner, executable=executable, model=model)


def _build_narrator(settings: AppSettings, harness: Harness) -> NarrativeRunner:
    return _narrator_for_provider(settings, _resolve_provider(settings, harness))


def _build_daily_narrator(settings: AppSettings) -> NarrativeRunner:
    """Daily scans every harness, so no single one names the provider.

    Configuration wins; otherwise take an installed provider, preferring
    OpenCode so an existing setup keeps the CLI it already used.
    """

    configured = settings.narrator.provider.strip()
    if configured:
        return _narrator_for_provider(settings, _resolve_provider(settings, Harness.OPENCODE))
    candidates = [
        _PROVIDER_BY_HARNESS[harness]
        for harness in _enabled_harnesses(settings)
        if shutil.which(_resolve_executable(settings, _PROVIDER_BY_HARNESS[harness]))
    ]
    if "opencode" in candidates:
        return _narrator_for_provider(settings, "opencode")
    if candidates:
        return _narrator_for_provider(settings, candidates[0])
    looked_for = ", ".join(
        _resolve_executable(settings, _PROVIDER_BY_HARNESS[harness])
        for harness in _enabled_harnesses(settings)
    )
    raise NarrativeRunError(
        f"no narration provider is installed; looked for {looked_for}. "
        "Set narrator.provider or narrator.executable."
    )
```

Add the imports:

```python
from iiwi.config import DEFAULT_NARRATOR_TIMEOUT_SECONDS
from iiwi.summarizers.narrator import NarrativeRunError, NarrativeRunner
from iiwi.summarizers.narrators.claude import ClaudeNarrator
from iiwi.summarizers.narrators.codex import CodexNarrator
```

- [ ] **Step 4: Wire the three construction sites**

In `_build_report_service`, replace the hardcoded construction at lines 299-304:

```python
    narrator = _build_narrator(settings, harness)
```

and pass `opencode_runner=narrator` — rename that keyword to `narrator` in `ReportService.__init__` and at its one other call site, updating the attribute to `self._narrator`.

In `src/iiwi/services/report.py`, change the import block and the type:

```python
from iiwi.summarizers.narrator import NarrativeRunError, NarrativeRunner
```

Change the parameter to `narrator: NarrativeRunner | None = None`, the attribute to `self._narrator`, and the two messages:

```python
        if self._narrator is None:
            raise NarrativeRunError("no narration provider configured for narrative mode")
```

```python
            except NarrativeRunError as exc:
                warnings.append(f"narration unavailable; used structured fallback ({exc})")
```

In `src/iiwi/services/outcomes.py`, change the import to `from iiwi.summarizers.narrator import NarrativeRunner` and the constructor parameter annotation at line 293 to `runner: NarrativeRunner`.

In `src/iiwi/interactive/cli_actions.py`, replace the runner construction at lines 207-212 with `runner = cli._build_narrator(settings, harness)` and, in `_start_daily`, replace lines 469-476 with:

```python
    runner = _DailyNarrator(cli._build_daily_narrator(settings))
```

Rename `_DailyOpenCodeRunner` to `_DailyNarrator`, drop its `OpenCodeRunner` base class (it never called `super().__init__`, so the base was decorative), and change its `except` clause to `except (NarrativeRunError, OSError)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_narrator_resolution.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. Tests that monkeypatch `cli_actions.OpenCodeRunner` now need to patch `cli._build_narrator` instead; update them where they fail.

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/cli.py src/iiwi/services/ src/iiwi/interactive/cli_actions.py tests/
git commit -m "feat: resolve the narration provider from settings and harness"
```

---

### Task 10: Recognise iiwi's own sessions on every harness

**Files:**
- Modify: `src/iiwi/sessions/filtering.py:59-71`
- Test: `tests/unit/sessions/test_filtering.py`

**Interfaces:**
- Consumes: the marker written by Task 3-5 adapters.
- Produces: `is_iiwi_authored` unchanged in signature; now also matches on the first user message.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/sessions/test_filtering.py`:

```python
def _with_first_user_message(harness: str, content: str) -> AgentSession:
    return AgentSession(
        harness=harness,
        session_id="s1",
        title="Refactoring the parser",
        activities=[
            SessionActivity(
                activity_id="a1",
                activity_type=ActivityType.USER_MESSAGE,
                content=content,
            )
        ],
    )


@pytest.mark.parametrize("harness", ["opencode", "claude-code", "codex"])
def test_marked_prompt_marks_the_session_as_iiwi_authored(harness: str) -> None:
    session = _with_first_user_message(
        harness, f"{IIWI_SESSION_TITLE_PREFIX}narrative 2026-08-01\n\nWrite a report."
    )

    assert is_iiwi_authored(session) is True


@pytest.mark.parametrize("harness", ["opencode", "claude-code", "codex"])
def test_an_ordinary_first_message_is_not_iiwi_authored(harness: str) -> None:
    session = _with_first_user_message(harness, "Please refactor the parser.")

    assert is_iiwi_authored(session) is False


def test_a_tool_call_before_the_user_message_does_not_hide_the_marker() -> None:
    session = AgentSession(
        harness="claude-code",
        session_id="s1",
        activities=[
            SessionActivity(
                activity_id="a0",
                activity_type=ActivityType.SYSTEM,
                content="session start",
            ),
            SessionActivity(
                activity_id="a1",
                activity_type=ActivityType.USER_MESSAGE,
                content=f"{IIWI_SESSION_TITLE_PREFIX}outcome synthesis\n\nGroup these.",
            ),
        ],
    )

    assert is_iiwi_authored(session) is True
```

Add `ActivityType` and `SessionActivity` to the file's imports from `iiwi.models.session` if they are not already there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/sessions/test_filtering.py -v`
Expected: FAIL — the parametrized marker tests return `False` for `claude-code` and `codex`.

- [ ] **Step 3: Add the second signal**

In `src/iiwi/sessions/filtering.py`:

```python
def _first_user_message(session: AgentSession) -> str:
    for activity in session.activities:
        if activity.activity_type is ActivityType.USER_MESSAGE:
            return activity.content
    return ""


def is_iiwi_authored(session: AgentSession) -> bool:
    """Return whether iiwi's own narration run created this session."""

    title = (session.title or "").strip()
    if title.startswith(IIWI_SESSION_TITLE_PREFIX):
        return True
    # Only `opencode run` accepts `--title`; Claude Code and Codex title their
    # sessions from model output, so the prompt is the one place a marker
    # survives on every harness.
    if _first_user_message(session).lstrip().startswith(IIWI_SESSION_TITLE_PREFIX):
        return True
    if not title:
        return False
    return session.harness == "opencode" and (
        title in _LEGACY_IIWI_TITLES or _LEGACY_IIWI_NARRATIVE.match(title) is not None
    )
```

Import `ActivityType` from `iiwi.models.session` at the top of the module.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/sessions/test_filtering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/sessions/filtering.py tests/unit/sessions/test_filtering.py
git commit -m "fix: exclude iiwi's own runs on every harness, not just opencode"
```

---

### Task 11: Show the resolved narrator in doctor

**Files:**
- Modify: `src/iiwi/services/doctor.py:44-78`
- Modify: `src/iiwi/cli.py` (pass the narrator description into `run_doctor`)
- Test: `tests/unit/services/test_doctor.py`

**Interfaces:**
- Consumes: `cli._resolve_provider`, `cli._resolve_executable` from Task 9.
- Produces: `doctor.build_checks(...)` gains a `narrator: NarratorDescription` parameter, where `NarratorDescription` is a frozen dataclass with `provider: str`, `executable: str`, `source: str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/test_doctor.py`:

```python
from iiwi.services.doctor import NarratorDescription


def test_doctor_reports_a_resolved_narrator(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        doctor.shutil, "which", lambda name: "/usr/local/bin/claude"
    )
    description = NarratorDescription(
        provider="claude", executable="claude", source="--harness claude-code"
    )

    check = doctor._narrator_check(description)

    assert check.ok is True
    assert "claude" in check.detail
    assert "--harness claude-code" in check.detail


def test_doctor_reports_a_missing_narrator_binary(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    description = NarratorDescription(
        provider="codex", executable="codex", source="--harness codex"
    )

    check = doctor._narrator_check(description)

    assert check.ok is False
    assert "codex" in check.detail
    assert "narrator.executable" in check.detail


def test_doctor_points_codex_desktop_users_at_the_documentation(
    monkeypatch, tmp_path
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    description = NarratorDescription(
        provider="codex", executable="codex", source="--harness codex"
    )

    check = doctor._narrator_check(description, codex_home=codex_home)

    assert "docs/configuration.md" in check.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/services/test_doctor.py -v`
Expected: FAIL with `ImportError: cannot import name 'NarratorDescription'`

- [ ] **Step 3: Add the check**

In `src/iiwi/services/doctor.py`, add `import shutil`, `from pathlib import Path` and:

```python
@dataclass(frozen=True)
class NarratorDescription:
    provider: str
    executable: str
    source: str


def _narrator_check(
    narrator: NarratorDescription,
    *,
    codex_home: Path | None = None,
) -> DoctorCheck:
    """Name the provider and say whether the choice was configured or derived."""

    resolved = shutil.which(narrator.executable)
    if resolved is not None:
        return DoctorCheck(
            name="narrator",
            ok=True,
            detail=f"{narrator.provider} (from {narrator.source}) -> {resolved}",
        )
    detail = (
        f"{narrator.executable} not found (from {narrator.source}); "
        "set narrator.provider or narrator.executable"
    )
    # A Codex desktop install ships its CLI outside PATH. The path is private,
    # so point at the documentation rather than hardcoding a location that a
    # future release can move.
    if narrator.provider == "codex" and codex_home is not None and codex_home.is_dir():
        detail += "; see the Codex desktop section of docs/configuration.md"
    return DoctorCheck(name="narrator", ok=False, detail=detail)
```

Add the parameter to the function that builds the checks and append the row unconditionally, before the `git` check:

```python
    checks.append(
        _narrator_check(narrator, codex_home=settings.harnesses.codex.home_directory)
    )
    checks.append(_check(runner, "git", ["git", "--version"]))
```

In `src/iiwi/cli.py`'s `run_doctor` call path, build the description:

```python
    provider = _resolve_provider(settings, harness)
    narrator = NarratorDescription(
        provider=provider,
        executable=_resolve_executable(settings, provider),
        source=(
            "narrator.provider"
            if settings.narrator.provider.strip()
            else f"--harness {harness.value}"
        ),
    )
```

and pass it through to the doctor service.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_doctor.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/services/doctor.py src/iiwi/cli.py tests/unit/services/test_doctor.py
git commit -m "feat: report the resolved narrator in doctor"
```

---

### Task 12: Pin the layering invariant

The reading layer and the narration layer do not import each other today. A violation would produce no symptom until someone tries to replace narration, so it is worth a test rather than a convention.

**Files:**
- Create: `tests/unit/test_layering.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the test**

Create `tests/unit/test_layering.py`:

```python
import ast
from pathlib import Path

HARNESSES = Path("src/iiwi/harnesses")
FORBIDDEN = "iiwi.summarizers"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_harnesses_do_not_import_summarizers() -> None:
    """Reading sessions must stay replaceable without touching narration.

    A violation has no symptom at run time; it only shows up when someone tries
    to swap the narration layer, which is exactly when it is expensive to find.
    """

    offenders = {
        str(path): sorted(
            module
            for module in _imported_modules(path)
            if module == FORBIDDEN or module.startswith(f"{FORBIDDEN}.")
        )
        for path in sorted(HARNESSES.rglob("*.py"))
    }
    offenders = {path: modules for path, modules in offenders.items() if modules}

    assert offenders == {}
```

- [ ] **Step 2: Run the test to verify it passes on clean code**

Run: `uv run pytest tests/unit/test_layering.py -v`
Expected: PASS

- [ ] **Step 3: Verify the test can actually fail**

Temporarily add `from iiwi.summarizers.narrator import NarrativeRunner  # noqa: F401` to `src/iiwi/harnesses/base.py`, run the test, confirm FAIL naming that file, then remove the line.

Run: `uv run pytest tests/unit/test_layering.py -v`
Expected: FAIL, then PASS after removing the line.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_layering.py
git commit -m "test: pin the harness-to-summarizer import direction"
```

---

### Task 13: Documentation

**Files:**
- Modify: `docs/configuration.md`
- Modify: `src/iiwi/interactive/render.py:112-118`
- Modify: `README.md:33`, `:35`, `:141`, `:170`; `README.zh-TW.md` equivalents
- Modify: `tests/unit/test_documentation.py:180-185`
- Test: `tests/unit/test_documentation.py`

**Interfaces:**
- Consumes: setting keys from Task 6; the doctor message from Task 11.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

Replace `test_configuration_documents_opencode_run_settings` in `tests/unit/test_documentation.py` and add the new assertions:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_documentation.py -v`
Expected: FAIL on all three new tests.

- [ ] **Step 3: Write the documentation**

Add to `docs/configuration.md` a `## Narrator` section documenting the four keys with their dotted names, environment variable names, defaults and resolution order, stating that fallbacks to `harnesses.opencode.cli.*` apply only when the provider is `opencode`. Mark the two deprecated keys in the existing OpenCode section with the replacement key name.

Add a `### Codex desktop` subsection:

```markdown
### Codex desktop

The Codex desktop application ships a complete CLI that is not linked onto
`PATH`. Point the narrator at it:

    iiwi config set narrator.provider codex
    iiwi config set narrator.executable ~/.codex/plugins/.plugin-appserver/codex

It shares `~/.codex/auth.json` with the desktop application, so no separate
login is needed. The location is internal to the Codex install and can move
between releases; if narration stops working after an update, check this path
first.
```

- [ ] **Step 4: Update the settings-editor descriptions**

In `src/iiwi/interactive/render.py`, add four entries and amend two:

```python
    "narrator.provider": "Which CLI writes the prose; empty follows the harness.",
    "narrator.executable": "Path to the narration CLI; empty uses the provider's name.",
    "narrator.model": "Model passed to the narration CLI; empty uses its default.",
    "narrator.timeout_seconds": "Timeout for one narration run.",
    "harnesses.opencode.cli.model": "Deprecated; use narrator.model.",
    "harnesses.opencode.cli.run_timeout_seconds": "Deprecated; use narrator.timeout_seconds.",
```

- [ ] **Step 5: Update the READMEs**

In `README.md`, change line 33's parenthetical so it no longer says an `opencode` executable is required, change line 35 so Quick Review synthesis is described as using the resolved narration CLI, change line 141's table cell to say the narrative comes from the harness's own CLI unless `narrator.provider` says otherwise, and keep line 170's "No API key" promise as written. Mirror each change in `README.zh-TW.md`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_documentation.py -v`
Expected: PASS

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add docs/configuration.md README.md README.zh-TW.md src/iiwi/interactive/render.py tests/unit/test_documentation.py
git commit -m "docs: document narrator settings and the Codex desktop CLI location"
```

---

### Task 14: End-to-end scenario coverage

The four scenarios in the spec are the product contract. Each gets an assertion that resolution produces the documented result with no configuration.

**Files:**
- Create: `tests/integration/test_narrator_scenarios.py`

**Interfaces:**
- Consumes: everything from Tasks 6-9.
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Create `tests/integration/test_narrator_scenarios.py`:

```python
import shutil
from pathlib import Path

import pytest

from iiwi import cli
from iiwi.summarizers.narrators.claude import ClaudeNarrator
from iiwi.summarizers.narrators.codex import CodexNarrator
from iiwi.summarizers.opencode_run import OpenCodeRunner


def _only(installed: str | None) -> object:
    def which(name: str) -> str | None:
        return f"/usr/local/bin/{name}" if installed and name == installed else None

    return which


def test_only_opencode_behaves_exactly_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", _only("opencode"))
    monkeypatch.setattr(cli.shutil, "which", _only("opencode"))
    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(tmp_path / "absent")
    )
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent"))
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "deepseek-r1")

    settings = cli._load_settings()
    harness = cli._default_harness(settings)
    provider = cli._resolve_provider(settings, harness)

    assert harness == cli.Harness.OPENCODE
    assert provider == "opencode"
    assert cli._resolve_model(settings, provider) == "deepseek-r1"
    assert isinstance(cli._build_narrator(settings, harness), OpenCodeRunner)


def test_only_claude_code_works_without_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(shutil, "which", _only("claude"))
    monkeypatch.setattr(cli.shutil, "which", _only("claude"))
    monkeypatch.setenv("IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(projects))
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(tmp_path / "absent"))
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__MODEL", "deepseek-r1")

    settings = cli._load_settings()
    harness = cli._default_harness(settings)
    provider = cli._resolve_provider(settings, harness)

    assert harness == cli.Harness.CLAUDE_CODE
    assert provider == "claude"
    # The leftover OpenCode model must not reach `claude --model`.
    assert cli._resolve_model(settings, provider) == ""
    assert cli._resolve_executable(settings, provider) == "claude"
    assert isinstance(cli._build_narrator(settings, harness), ClaudeNarrator)


def test_only_codex_with_the_cli_on_path_works_without_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    monkeypatch.setattr(shutil, "which", _only("codex"))
    monkeypatch.setattr(cli.shutil, "which", _only("codex"))
    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(tmp_path / "absent")
    )
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(codex_home))

    settings = cli._load_settings()
    harness = cli._default_harness(settings)

    assert harness == cli.Harness.CODEX
    assert isinstance(cli._build_narrator(settings, harness), CodexNarrator)


def test_codex_desktop_reads_but_needs_an_executable_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    bundled = codex_home / "plugins" / ".plugin-appserver" / "codex"
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    monkeypatch.setattr(shutil, "which", _only(None))
    monkeypatch.setattr(cli.shutil, "which", _only(None))
    monkeypatch.setenv(
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY", str(tmp_path / "absent")
    )
    monkeypatch.setenv("IIWI_HARNESSES__CODEX__HOME_DIRECTORY", str(codex_home))

    settings = cli._load_settings()

    # Reading works: availability is about the session store, not the binary.
    assert cli._default_harness(settings) == cli.Harness.CODEX

    monkeypatch.setenv("IIWI_NARRATOR__EXECUTABLE", str(bundled))
    settings = cli._load_settings()

    assert cli._resolve_executable(settings, "codex") == str(bundled)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_narrator_scenarios.py -v`
Expected: PASS

- [ ] **Step 3: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_narrator_scenarios.py
git commit -m "test: cover the four installation scenarios end to end"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| Narration contract | 2 |
| Adapters (three command surfaces) | 3, 4, 5 |
| Availability (predicates, six sites, Daily relationship) | 7, 8 |
| Resolution rules (provider/executable/model/timeout) | 9 |
| Configuration and compatibility | 6, 14 |
| Self-authored session exclusion | 3, 10 |
| Failure behaviour | 3, 4, 5, 9 |
| Doctor | 11 |
| Scenarios | 14 |
| Direction invariant | 12 |
| Prompt de-branding, message de-branding, prompt module move | 2, 9 |
| Documentation | 13 |

**Gap found and closed during planning:** the spec assumes a transcript can be
sent on stdin, but `CommandRunner.run` had no such parameter. Task 1 adds it.

**Type consistency:** `NarrativeRunner`, `NarrativeRunError`, `CommandRunnerLike`,
`marked_prompt`, `failure_detail`, `ClaudeNarrator`, `CodexNarrator`,
`NarratorSettings`, `is_available`, `_available_harnesses`, `_default_harness`,
`_resolve_provider`, `_resolve_executable`, `_resolve_model`, `_resolve_timeout`,
`_build_narrator`, `_build_daily_narrator`, `NarratorDescription` are each
defined once and referenced with the same name and signature throughout.
`ReportService`'s `opencode_runner` keyword is renamed to `narrator` in Task 9 at
both its definition and its call sites.
