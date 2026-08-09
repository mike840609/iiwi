from iiwi.progress import ProgressStage


class RecordingProgressReporter:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None:
        self.events.append(("start", stage, total))

    def advance(self, completed: int) -> None:
        self.events.append(("advance", completed))

    def finish(self) -> None:
        self.events.append(("finish",))
