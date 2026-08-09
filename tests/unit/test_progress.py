from iiwi.progress import NullProgressReporter, ProgressStage


def test_progress_stages_are_stable_and_complete() -> None:
    assert [stage.value for stage in ProgressStage] == [
        "discovering_sessions",
        "exporting_sessions",
        "preparing_evidence",
        "summarizing_repositories",
        "collecting_usage",
        "rendering_report",
        "writing_report",
    ]


def test_null_progress_reporter_accepts_the_full_lifecycle() -> None:
    reporter = NullProgressReporter()

    assert reporter.start(ProgressStage.EXPORTING_SESSIONS, total=3) is None
    assert reporter.advance(1) is None
    assert reporter.advance(3) is None
    assert reporter.finish() is None
    assert reporter.finish() is None
