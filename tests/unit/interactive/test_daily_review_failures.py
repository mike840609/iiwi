from __future__ import annotations

from datetime import date, datetime
from io import StringIO

import pytest
from rich.console import Console

from iiwi.errors import (
    ConfigurationError,
    DailySourceUnavailableError,
    IiwiError,
    ReportOutputError,
)
from iiwi.interactive import controller
from iiwi.interactive.controller import InteractiveActions
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import Screen
from iiwi.models.daily import DailyStandupDraft
from iiwi.summarizers.narrator import NarrativeRunError

from .test_daily_review_controller import ActionLog, _actions, _draft, _state


def _source_error() -> DailySourceUnavailableError:
    return DailySourceUnavailableError(
        unavailable_harnesses=("codex", "claude_code"),
        standup_date=date(2026, 8, 13),
        since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        until=datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
    )


def _console() -> Console:
    return Console(file=StringIO(), color_system=None, force_terminal=False)


def _replace_daily_actions(
    actions: InteractiveActions,
    **changes: object,
) -> InteractiveActions:
    values = {
        field: getattr(actions, field)
        for field in actions.__dataclass_fields__
    }
    values.update(changes)
    return InteractiveActions(**values)  # type: ignore[arg-type]


def test_all_source_error_preserves_original_window_and_offers_recovery() -> None:
    log = ActionLog()
    original = _source_error()
    actions = _replace_daily_actions(
        _actions(log),
        start_daily=lambda previous: (_ for _ in ()).throw(original),
    )
    state = _state()

    controller._begin_daily_review(state, actions, _console())

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "daily-source"
    assert state.error.daily_source_error is original
    assert controller._error_options(state.error) == [
        "Retry",
        "Continue with empty draft",
        "Back",
    ]


def test_configuration_error_from_start_daily_is_recoverable_not_fatal() -> None:
    """start_daily reads settings, the enabled harnesses and the clock first.

    Every one of those raises ConfigurationError on an unusable config, and
    _dispatch catches only KeyboardInterrupt and typer.Abort, so anything that
    escapes here takes the whole interactive app down with a traceback.
    """

    log = ActionLog()
    actions = _replace_daily_actions(
        _actions(log),
        start_daily=lambda previous: (_ for _ in ()).throw(
            ConfigurationError("no harness is enabled")
        ),
    )
    state = _state()

    controller._begin_daily_review(state, actions, _console())

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "daily-start"
    assert "no harness is enabled" in state.error.detail


def test_narrative_run_error_is_an_iiwi_error() -> None:
    """NarrativeRunError subclasses IiwiError, so a single `except IiwiError`
    arm catches it alongside ConfigurationError and the other expected errors."""

    assert issubclass(NarrativeRunError, IiwiError)


def test_narrative_run_error_from_start_daily_is_recoverable_not_fatal() -> None:
    """start_daily builds the daily narrator from whichever harness is

    installed (cli._build_daily_narrator), which raises NarrativeRunError
    when no provider CLI is on PATH, or when narrator.executable is set
    without narrator.provider. NarrativeRunError subclasses Exception, not
    IiwiError, so it needs its own except arm here; without it this escapes
    _begin_daily_review, then run_interactive's direct call to it at startup
    (before the main loop's try/except exists), and takes the whole
    interactive app down with a traceback instead of showing this screen.
    """

    log = ActionLog()
    actions = _replace_daily_actions(
        _actions(log),
        start_daily=lambda previous: (_ for _ in ()).throw(
            NarrativeRunError("no narration provider is installed; looked for codex")
        ),
    )
    state = _state()

    controller._begin_daily_review(state, actions, _console())

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "daily-start"
    assert "no narration provider is installed" in state.error.detail


def test_daily_source_retry_passes_current_daily_draft() -> None:
    log = ActionLog()
    previous = _draft()
    calls: list[DailyStandupDraft | None] = []

    def start(current: DailyStandupDraft | None) -> DailyStandupDraft:
        calls.append(current)
        return previous

    actions = _replace_daily_actions(_actions(log), start_daily=start)
    state = _state(previous)
    state.error = controller._ErrorState(
        kind="daily-source",
        title="Could not read Daily sources",
        detail="all unavailable",
        retry="daily-source",
        daily_source_error=_source_error(),
    )
    state.screen = Screen.RECOVERABLE_ERROR

    controller._error_key(state, KeyPress(key=Key.ENTER), actions, _console())

    assert calls == [previous]
    assert state.screen is Screen.DAILY_REVIEW


def test_daily_source_continue_uses_original_error_and_current_draft() -> None:
    log = ActionLog()
    previous = _draft()
    original = _source_error()
    calls: list[tuple[DailySourceUnavailableError, DailyStandupDraft | None]] = []

    def continue_empty(
        error: DailySourceUnavailableError,
        current: DailyStandupDraft | None,
    ) -> DailyStandupDraft:
        calls.append((error, current))
        return current or _draft()

    actions = _replace_daily_actions(
        _actions(log),
        continue_daily_empty=continue_empty,
    )
    state = _state(previous)
    state.error = controller._ErrorState(
        kind="daily-source",
        title="Could not read Daily sources",
        detail="all unavailable",
        retry="daily-source",
        selected=1,
        daily_source_error=original,
    )
    state.screen = Screen.RECOVERABLE_ERROR

    controller._error_key(state, KeyPress(key=Key.ENTER), actions, _console())

    assert calls == [(original, previous)]
    assert state.screen is Screen.DAILY_REVIEW


def test_daily_source_back_returns_main() -> None:
    state = _state()
    state.error = controller._ErrorState(
        kind="daily-source",
        title="Could not read Daily sources",
        detail="all unavailable",
        retry="daily-source",
        daily_source_error=_source_error(),
    )
    state.screen = Screen.RECOVERABLE_ERROR

    controller._error_key(state, KeyPress(char="b"), _actions(ActionLog()), _console())

    assert state.screen is Screen.MAIN


@pytest.mark.parametrize(("preview", "kind"), [(True, "daily-preview"), (False, "daily-write")])
def test_daily_output_failures_return_to_daily_review(
    preview: bool,
    kind: str,
) -> None:
    log = ActionLog()

    def fail(draft: DailyStandupDraft) -> None:
        raise ReportOutputError("disk unavailable")

    changes = {"preview_daily" if preview else "generate_daily": fail}
    actions = _replace_daily_actions(_actions(log), **changes)
    state = _state()

    controller._generate_daily_review(state, actions, preview=preview)

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == kind
    assert controller._error_back_screen(state.error) is Screen.DAILY_REVIEW


def test_daily_start_error_enter_returns_to_main_without_crash() -> None:
    log = ActionLog()
    actions = _replace_daily_actions(
        _actions(log),
        start_daily=lambda previous: (_ for _ in ()).throw(
            ConfigurationError("no harness is enabled")
        ),
    )
    state = _state()

    controller._begin_daily_review(state, actions, _console())

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "daily-start"
    assert controller._error_options(state.error) == ["Back", "Main menu"]

    # Pressing Enter on option 0 ("Back") must not raise AssertionError on state.draft
    controller._error_key(state, KeyPress(key=Key.ENTER), actions, _console())

    assert state.screen is Screen.MAIN

