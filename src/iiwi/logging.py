"""Rich console helpers for already-redacted user-facing messages."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.padding import Padding
from rich.status import Status
from rich.table import Table
from rich.text import Text

from iiwi.config_store import SettingRow
from iiwi.history import HistoryEntry
from iiwi.progress import (
    NullProgressReporter,
    ProgressReporter,
    ProgressStage,
)
from iiwi.security.redactor import redact_text
from iiwi.services.scan import ScanResult


def _collapse_whitespace(value: str) -> str:
    """Fold embedded newlines and space runs so a title is one logical line.

    Callers pair this with `no_wrap` rendering: collapsing alone does not stop
    Rich from soft-wrapping a long line, and a wrapped continuation starts in
    column 0 — where repository names are printed, so it reads as a heading.
    """

    return " ".join(value.split())


_STAGE_LABELS = {
    ProgressStage.DISCOVERING_SESSIONS: "Finding sessions",
    ProgressStage.EXPORTING_SESSIONS: "Exporting sessions",
    ProgressStage.PREPARING_EVIDENCE: "Preparing repository evidence",
    ProgressStage.SUMMARIZING_REPOSITORIES: "Summarizing repositories",
    ProgressStage.COLLECTING_USAGE: "Collecting usage statistics",
    ProgressStage.RENDERING_REPORT: "Rendering report",
    ProgressStage.WRITING_REPORT: "Writing report",
}


class RichProgressReporter:
    """Render one transient, continuously animated Rich status line."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._status: Status | None = None
        self._stage: ProgressStage | None = None
        self._total: int | None = None
        self._completed = 0

    def _description(self) -> Padding:
        assert self._stage is not None
        label = _STAGE_LABELS[self._stage]
        description = label
        if self._total is not None:
            description = f"{label} {self._completed}/{self._total}"
        text = Text(description, overflow="ellipsis", no_wrap=True)
        return Padding(text, (0, 0))

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None:
        self._stage = stage
        self._total = total
        self._completed = 0
        description = self._description()
        if self._status is None:
            self._status = self._console.status(description, spinner="dots")
            self._status.start()
        else:
            self._status.update(description)

    def advance(self, completed: int) -> None:
        self._completed = completed
        if self._status is not None:
            self._status.update(self._description())

    def finish(self) -> None:
        status = self._status
        self._status = None
        self._stage = None
        if status is not None:
            status.stop()


class ConsoleReporter:
    """Render concise CLI output; callers must pass redacted strings."""

    def __init__(
        self,
        *,
        quiet: bool = False,
        verbose: bool = False,
        console: Console | None = None,
        progress_console: Console | None = None,
    ) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.console = console or Console()
        self.progress_console = progress_console or Console(stderr=True)

    @contextmanager
    def progress(self) -> Iterator[ProgressReporter]:
        progress: ProgressReporter
        if self.quiet:
            progress = NullProgressReporter()
        else:
            progress = RichProgressReporter(self.progress_console)
        try:
            yield progress
        finally:
            progress.finish()

    def message(self, text: str) -> None:
        if not self.quiet:
            self.console.print(text)

    def output_path(self, path: Path) -> None:
        self.console.print(str(path))

    def doctor_check(self, name: str, ok: bool, detail: str) -> None:
        if self.quiet:
            return
        status = "[green]OK[/green]" if ok else "[red]ERROR[/red]"
        self.console.print(f"[{status}] {name}: {detail}")

    def settings_table(self, rows: Sequence[SettingRow], *, path: Path) -> None:
        """Render every setting with the value in force and where it came from.

        Values are wrapped in `Text` rather than redacted: these are the user's
        own settings, printed at their own request, and `redact_text` would
        mangle a legitimate value that happens to look like a secret.
        """

        table = Table(title="Agent Worklog Settings")
        # `config list`'s whole job is teaching the user the key names they
        # type into `config set`; at the default 80-column terminal, Rich's
        # default ellipsis truncation cuts most keys down to an identical
        # "harnesses.opencode.…" prefix. Folding wraps instead, so the full
        # key, value, and default are always readable regardless of width.
        table.add_column("Setting", overflow="fold")
        table.add_column("Value", overflow="fold")
        table.add_column("From")
        table.add_column("Default", overflow="fold")
        for row in rows:
            table.add_row(row.key, Text(row.value), row.source, Text(row.default))
        self.console.print(table)
        self.console.print(f"Settings file: {path}")
        self.console.print(
            "Every setting is optional. Leave one out — or set it to an empty "
            "value — to fall back to the default in the last column."
        )

    def history_table(self, entries: Sequence[HistoryEntry]) -> None:
        """Render the generated-report log, newest first."""

        table = Table(title="Generated Reports")
        table.add_column("Generated")
        table.add_column("Period")
        table.add_column("Harness")
        table.add_column("Sessions", justify="right")
        table.add_column("Repos", justify="right")
        table.add_column("Narrative")
        table.add_column("Path", overflow="fold")
        for entry in reversed(entries):
            table.add_row(
                f"{entry.generated_at:%Y-%m-%d %H:%M}",
                f"{entry.since:%Y-%m-%d} – {entry.until:%Y-%m-%d}",
                entry.harness,
                str(entry.session_count),
                str(entry.repository_count),
                "yes" if entry.narrative else "no",
                str(entry.output_path),
            )
        self.console.print(table)

    def scan_result(self, result: ScanResult) -> None:
        if self.quiet:
            self.console.print(str(result.loaded_session_count))
            return
        table = Table(title="Agent Worklog Scan")
        table.add_column("Repository")
        table.add_column("Identity")
        table.add_column("Sessions", justify="right")
        for repository_id, sessions in result.sessions_by_repository.items():
            name = sessions[0].repository.display_name if sessions else repository_id
            table.add_row(Text(redact_text(name)), repository_id, str(len(sessions)))
        self.console.print(table)
        if self.verbose:
            for warning in result.warnings:
                self.console.print(f"[yellow]Warning:[/yellow] {warning}")
            for repository_id, sessions in result.sessions_by_repository.items():
                name = sessions[0].repository.display_name if sessions else repository_id
                self.console.print(f"\n{redact_text(name)}", markup=False, highlight=False)
                for resolved in sessions:
                    session = resolved.session
                    title = _collapse_whitespace(session.title) if session.title else None
                    label = redact_text(title or session.session_id)
                    directory = session.working_directory
                    location = f" — {redact_text(directory)}" if directory else ""
                    self.console.print(
                        Text(f"  • {label}{location}"),
                        overflow="ellipsis",
                        no_wrap=True,
                        highlight=False,
                    )
