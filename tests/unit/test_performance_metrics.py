"""Requirement coverage for the performance collector behind `--verbose`."""

import time
from io import StringIO

import pytest
from rich.console import Console

from iiwi.logging import ConsoleReporter
from iiwi.metrics import MetricStage, PerformanceMetrics


def forced_console(stream: StringIO, *, width: int = 100) -> Console:
    return Console(file=stream, force_terminal=True, color_system=None, width=width)


def reporter_output(metrics: PerformanceMetrics, **kwargs: bool) -> str:
    """Render `performance` into a string, capturing the stderr console it uses."""

    stream = StringIO()
    reporter = ConsoleReporter(
        console=forced_console(StringIO()),
        progress_console=forced_console(stream),
        **kwargs,
    )
    reporter.performance(metrics)
    return stream.getvalue()


def busy_wait(seconds: float) -> None:
    """Burn measurable wall time without `sleep`, which a loaded CI box oversleeps."""

    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        pass


# --- collection ---------------------------------------------------------------


def test_measure_records_the_stage_it_was_given() -> None:
    metrics = PerformanceMetrics()

    with metrics.measure(MetricStage.EXPORT_SESSIONS):
        busy_wait(0.001)

    assert list(metrics.durations) == [MetricStage.EXPORT_SESSIONS]
    assert metrics.durations[MetricStage.EXPORT_SESSIONS] > 0


def test_repeated_measures_of_one_stage_accumulate() -> None:
    """Export is entered once per session; the summary owes the user the total."""

    metrics = PerformanceMetrics()

    for _ in range(3):
        with metrics.measure(MetricStage.EXPORT_SESSIONS):
            busy_wait(0.002)

    single = PerformanceMetrics()
    with single.measure(MetricStage.EXPORT_SESSIONS):
        busy_wait(0.002)

    assert (
        metrics.durations[MetricStage.EXPORT_SESSIONS]
        > single.durations[MetricStage.EXPORT_SESSIONS]
    )


def test_measure_records_time_spent_before_an_exception() -> None:
    """A run that died mid-export still spent that time, and must still report it."""

    metrics = PerformanceMetrics()

    with pytest.raises(RuntimeError):  # noqa: SIM117
        with metrics.measure(MetricStage.EXPORT_SESSIONS):
            busy_wait(0.001)
            raise RuntimeError("export failed")

    assert metrics.durations[MetricStage.EXPORT_SESSIONS] > 0


def test_distinct_stages_are_kept_apart() -> None:
    metrics = PerformanceMetrics()

    with metrics.measure(MetricStage.DISCOVER_SESSIONS):
        busy_wait(0.001)
    with metrics.measure(MetricStage.NARRATE):
        busy_wait(0.001)

    assert set(metrics.durations) == {
        MetricStage.DISCOVER_SESSIONS,
        MetricStage.NARRATE,
    }


def test_counts_and_labels_are_recorded_and_overwritten_not_summed() -> None:
    metrics = PerformanceMetrics()

    metrics.count("loaded_sessions", 3)
    metrics.count("loaded_sessions", 42)
    metrics.label("narrator", "opencode")

    assert metrics.counts == {"loaded_sessions": 42}
    assert metrics.labels == {"narrator": "opencode"}


# --- aggregation --------------------------------------------------------------


def test_total_is_the_sum_of_the_measured_stages() -> None:
    metrics = PerformanceMetrics()
    metrics.durations[MetricStage.EXPORT_SESSIONS] = 11.84
    metrics.durations[MetricStage.NARRATE] = 18.96

    assert metrics.total_seconds == pytest.approx(30.80)


def test_an_empty_collector_totals_zero_and_reports_nothing() -> None:
    metrics = PerformanceMetrics()

    assert metrics.total_seconds == 0.0
    assert metrics.ordered_durations() == []


def test_ordered_durations_follow_declaration_order_not_recording_order() -> None:
    """The summary must read the same on every run, whichever path recorded first."""

    metrics = PerformanceMetrics()
    with metrics.measure(MetricStage.WRITE_REPORT):
        pass
    with metrics.measure(MetricStage.DISCOVER_SESSIONS):
        pass

    assert [stage for stage, _ in metrics.ordered_durations()] == [
        MetricStage.DISCOVER_SESSIONS,
        MetricStage.WRITE_REPORT,
    ]


# --- rendering ----------------------------------------------------------------


def test_verbose_rendering_names_every_recorded_stage_and_the_total() -> None:
    metrics = PerformanceMetrics()
    metrics.durations[MetricStage.DISCOVER_SESSIONS] = 0.31
    metrics.durations[MetricStage.EXPORT_SESSIONS] = 11.84
    metrics.durations[MetricStage.NARRATE] = 18.96

    output = reporter_output(metrics, verbose=True)

    assert "Performance" in output
    assert "Discover sessions" in output
    assert "0.31s" in output
    assert "Export sessions" in output
    assert "11.84s" in output
    assert "Narration" in output
    assert "18.96s" in output
    assert "Total" in output
    assert "31.11s" in output


def test_verbose_rendering_shows_the_counts_that_explain_the_timings() -> None:
    metrics = PerformanceMetrics()
    metrics.count("loaded_sessions", 42)
    metrics.count("repositories", 6)
    metrics.count("transcript_bytes", 831488)
    metrics.label("narrator", "opencode")

    output = reporter_output(metrics, verbose=True)

    assert "Sessions" in output
    assert "42" in output
    assert "Repositories" in output
    assert "Transcript" in output
    assert "812 KB" in output
    assert "Narrator" in output
    assert "opencode" in output


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 B"), (512, "512 B"), (1024, "1 KB"), (1536, "2 KB"), (1048576, "1.0 MB")],
)
def test_transcript_size_is_rendered_in_human_units(value: int, expected: str) -> None:
    metrics = PerformanceMetrics()
    metrics.count("transcript_bytes", value)

    assert expected in reporter_output(metrics, verbose=True)


def test_an_unmapped_counter_still_renders_readably() -> None:
    """A metric added before its label is, is worth less than nothing if hidden."""

    metrics = PerformanceMetrics()
    metrics.count("cache_hits", 37)

    output = reporter_output(metrics, verbose=True)

    assert "Cache hits" in output
    assert "37" in output


def test_normal_mode_prints_no_timings() -> None:
    metrics = PerformanceMetrics()
    metrics.durations[MetricStage.NARRATE] = 18.96

    assert reporter_output(metrics) == ""


def test_quiet_mode_prints_no_timings() -> None:
    metrics = PerformanceMetrics()
    metrics.durations[MetricStage.NARRATE] = 18.96

    assert reporter_output(metrics, quiet=True) == ""


def test_verbose_prints_nothing_when_nothing_was_measured() -> None:
    """An empty table is noise; a command that recorded nothing says nothing."""

    assert reporter_output(PerformanceMetrics(), verbose=True) == ""
