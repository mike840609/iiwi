# Daily Standup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class `iiwi daily` workflow that automatically scans all enabled harnesses from yesterday 00:00 through now, turns the evidence into a reviewer-editable Yesterday / Today / Blockers standup, preserves reviewer decisions across same-day reruns, previews the exact Markdown that will be written, and records the generated standup in History.

**Architecture:** Extend the existing evidence-first Quick Review boundary rather than building another reporting engine. Make cross-harness evidence identity collision-safe, scan each enabled harness independently through the existing `ScanService`, reuse `OutcomeSynthesisService` for work grouping, project grouped evidence deterministically into Daily sections by activity timestamp, reconcile that fresh projection against a persisted Daily-local draft, then render and write the reviewed artifact through Daily-specific renderer/state/UI seams. General Report Setup, Session Review, and existing `OutcomeReviewDraft` stay independent.

**Tech Stack:** Python 3.11+, Pydantic 2, Typer, Rich, Jinja-free deterministic Markdown rendering for Daily, platformdirs, pytest, Ruff, Pyright, existing `ScanService`, `OutcomeSynthesisService`, `atomic_secure_write`, and the interactive state-machine controller.

## Global Constraints

- Spec: `docs/2026-08-13-daily-standup-design.md`.
- Daily Standup always has exactly three final sections in this order: `Yesterday`, `Today`, `Blockers`; an empty section renders `- None`.
- The standup title date and day boundaries use `report.timezone`; derive local calendar midnights, never `now - timedelta(hours=24)`.
- Scan one union window from yesterday local `00:00` through the command's single `now` value.
- Scan every enabled harness automatically; there is no Daily harness picker and subagents are always included.
- One failed harness is partial success with an explicit coverage warning; all enabled harnesses failing is a recoverable source error, not “no activity.”
- No activity is valid and opens an empty Daily Quick Review with manual Add available in all three sections.
- Reuse the existing outcome-grouping boundary. Do not introduce a second model call that re-groups work for Daily.
- Cross-harness source identity is `(harness, session_id)`; raw `session_id` alone must never key merged Daily evidence.
- Daily evidence identity for reconciliation is `(harness, session_id, activity_id)` with unambiguous `(harness, session_id)` overlap as the only coarser fallback.
- The LLM never decides Yesterday versus Today. Section assignment uses `SessionActivity.timestamp` only.
- Yesterday may include substantive in-progress progress. Today prefers actual Today activity, then only an explicitly supported unfinished/next-step signal from Yesterday. Never invent a plan.
- Blockers require unresolved blocker evidence. Resolved command failures and ordinary debugging errors are not blockers.
- Yesterday and Today preselect at most five items each; extra candidates remain available under section-specific More candidates. This is not a final-output hard cap.
- Final bullets are standup-first and list all participating repositories as `[repo-a, repo-b]`; harness names and review provenance labels stay out of final Markdown.
- Review-only labels include `Activity today`, `Suggested from yesterday`, `Detected blocker`, `User added`, `New activity`, and `Fallback draft`.
- Daily review reuses `Space`, `e`, `J/K`, `v`, `a`, `p`, `g`, and `b`; v1 has no Report type, Detail, Next week, or Daily Split interaction.
- `p Preview` and `g Generate` consume the same in-memory reviewed draft. Generate must not re-run synthesis or rewrite reviewed text.
- Daily output is `<report.output_directory>/daily-standup-YYYY-MM-DD.md`. Same-day generation intentionally replaces that file atomically; it does not raise the generic report-exists conflict.
- Same-day reruns preserve user-added items, reviewer wording, exclusions, and order. New evidence may extend an existing work item without silently rewriting reviewer-owned text.
- Daily-local work-item ids are persisted and are never recomputed from model prose or `Outcome.id`.
- A new calendar day does not load or copy the previous day's Today plan.
- Persist Daily review state under the Iiwi user-data directory, owner-only where supported, with no copied full transcripts. Retain state for 30 days with opportunistic non-fatal cleanup.
- Total outcome-synthesis failure enters the normal Daily Quick Review through a deterministic fallback draft; it is not a fatal error.
- History must remain backward-compatible with existing JSONL entries and must distinguish `daily_standup` from general reports without fabricating a `multiple` harness.
- Existing general report behavior, single-harness `ScanService`, Report Setup, Session Review, and normal Quick Review persistence semantics must not change unless a task below explicitly says so.
- Do not add new runtime dependencies.

---

## File map

The implementation should land in focused files so Daily-specific concerns do not make `interactive/controller.py` and `services/outcomes.py` own unrelated responsibilities.

**New domain/service files**

- `src/iiwi/models/daily.py` — Daily section/work-item/draft models and reviewer-owned mutation methods.
- `src/iiwi/services/daily_scan.py` — timezone-aware Daily window and multi-harness scan coordinator.
- `src/iiwi/services/daily_projection.py` — deterministic timestamp projection, blocker resolution, initial candidate selection, and synthesis fallback.
- `src/iiwi/services/daily_reconcile.py` — same-day evidence-overlap reconciliation and reviewer-decision preservation.
- `src/iiwi/daily_state.py` — persisted Daily draft load/save and 30-day cleanup.
- `src/iiwi/renderers/daily_markdown.py` — exact final Daily Markdown renderer.
- `src/iiwi/services/daily_report.py` — preview/write result service; same-day atomic replacement.
- `src/iiwi/interactive/daily_review.py` — Daily review row derivation and section-specific More-candidate visibility.
- `docs/daily-standup.md` — user-facing Daily workflow guide.

**Existing files with bounded changes**

- `src/iiwi/models/evidence.py`, `src/iiwi/models/outcome.py`, `src/iiwi/extraction/pipeline.py`, `src/iiwi/services/outcomes.py`, `src/iiwi/summarizers/outcome_prompt.py` — collision-safe cross-harness source ids and richer evidence refs.
- `src/iiwi/errors.py` — all-sources-unavailable Daily error.
- `src/iiwi/history.py`, `src/iiwi/logging.py`, `src/iiwi/interactive/render.py` — first-class Daily history and Daily review/result rendering.
- `src/iiwi/interactive/models.py`, `src/iiwi/interactive/controller.py`, `src/iiwi/interactive/cli_actions.py` — Daily screens/actions only; keep the existing report flow intact.
- `src/iiwi/cli.py` — `iiwi daily`, common Daily action wiring, and direct start into Daily review.
- `README.md`, `README.zh-TW.md`, `docs/cli-reference.md`, `docs/evidence-first-quick-review.md` — discoverability and the explicit Daily persistent-draft exception.

---

### Task 1: Make outcome grouping collision-safe across harnesses

**Files:**
- Modify: `src/iiwi/models/evidence.py`
- Modify: `src/iiwi/models/outcome.py`
- Modify: `src/iiwi/models/__init__.py`
- Modify: `src/iiwi/extraction/pipeline.py`
- Modify: `src/iiwi/services/outcomes.py`
- Modify: `src/iiwi/summarizers/outcome_prompt.py`
- Modify: `tests/unit/extraction/test_pipeline.py`
- Modify: `tests/unit/models/test_outcome.py`
- Modify: `tests/unit/services/test_outcomes.py`
- Modify: `tests/unit/summarizers/test_outcome_prompt.py`

**Interfaces:**
- Consumes: `ResolvedSession.session.harness`, existing `EvidenceItem.source_activity_ids`, current `OutcomeSynthesisService` grouping/validation path.
- Produces:
  - `SessionEvidence.harness: str`.
  - `EvidenceRef.harness: str | None = None` and `EvidenceRef.activity_ids: list[str] = Field(default_factory=list)`; old serialized refs remain valid.
  - Private collision-safe `_source_id(evidence: SessionEvidence) -> str` in `services/outcomes.py`; representation is `json.dumps([harness, session_id], separators=(",", ":"), ensure_ascii=False)` and is treated as opaque after construction.
  - `_CompactSession.source_id: str` instead of `_CompactSession.session_id`.
  - `_ProposedOutcome.source_ids: list[str]` instead of `source_session_ids`.
  - Every map/set/signature used to correlate model proposals with evidence keys by opaque source id, not raw session id.
  - `_evidence_refs(SessionEvidence)` includes the harness and the stable sorted union of all source activity ids for that selected session evidence.

- [ ] **Step 1: Write failing model/extraction tests for harness provenance and backward-compatible refs**

Add focused cases:

```python
from iiwi.models.outcome import EvidenceRef


def test_extract_evidence_keeps_harness(resolved_session) -> None:
    resolved_session.session.harness = "claude-code"
    evidence = extract_evidence(resolved_session)
    assert evidence.harness == "claude-code"


def test_evidence_ref_old_payload_remains_valid() -> None:
    ref = EvidenceRef.model_validate(
        {"session_id": "same", "repository_id": "repo"}
    )
    assert ref.harness is None
    assert ref.activity_ids == []
```

Update direct `SessionEvidence(...)` test factories in `test_outcomes.py` to pass an explicit harness so the production contract is represented in tests.

- [ ] **Step 2: Run the focused tests and verify they fail before implementation**

Run:

```bash
uv run pytest \
  tests/unit/extraction/test_pipeline.py \
  tests/unit/models/test_outcome.py -q
```

Expected: FAIL because `SessionEvidence` has no `harness` field and `EvidenceRef` has no `harness` / `activity_ids` fields yet.

- [ ] **Step 3: Add the minimal provenance fields and populate them during extraction**

Implement the model additions exactly:

```python
class SessionEvidence(BaseModel):
    harness: str
    session_id: str
    repository_id: str
    # existing fields unchanged


class EvidenceRef(BaseModel):
    session_id: str
    repository_id: str
    harness: str | None = None
    activity_ids: list[str] = Field(default_factory=list)
    commit: str | None = None
    file: str | None = None
```

In `extract_evidence` initialize `harness=resolved.session.harness`. Keep the new `EvidenceRef` fields optional/defaulted because existing history/report/draft payloads may deserialize refs that predate Daily.

- [ ] **Step 4: Write a failing cross-harness collision test around `OutcomeSynthesisService`**

Create two resolved sessions with the same raw id but different harnesses and unique titles/goals. Use a fake runner whose model reply returns both `source_ids` as separate proposals. Pin these facts:

```python
assert len(result.outcomes) == 2
assert {ref.harness for outcome in result.outcomes for ref in outcome.evidence_refs} == {
    "opencode",
    "claude-code",
}
assert all(ref.activity_ids for outcome in result.outcomes for ref in outcome.evidence_refs)
```

Also inspect the transcript given to the fake runner and assert two distinct `source_id` values exist even though both raw session ids are `same-id`.

- [ ] **Step 5: Run the collision and prompt tests and verify the old contract fails**

Run:

```bash
uv run pytest \
  tests/unit/services/test_outcomes.py \
  tests/unit/summarizers/test_outcome_prompt.py -q
```

Expected: FAIL because `_CompactSession` / prompt / proposal schema still use raw `session_id` / `source_session_ids`, causing one session to overwrite the other in raw-id-keyed maps.

- [ ] **Step 6: Refactor the grouping boundary to opaque `source_id` keys**

Use one constructor everywhere:

```python
def _source_id(evidence: SessionEvidence) -> str:
    return json.dumps(
        [evidence.harness, evidence.session_id],
        separators=(",", ":"),
        ensure_ascii=False,
    )
```

Change `_CompactSession` to expose `source_id`, change model prompt/output schema to `source_ids`, and key `evidence_by_source`, `compact_by_source`, `local_texts_by_source`, `started_at`, `used_source_ids`, proposal signatures, and synthesized-id inputs by this value. Do not parse or trust a model-produced source id beyond an exact dictionary lookup.

Update `_evidence_refs` with:

```python
def _activity_ids(evidence: SessionEvidence) -> list[str]:
    return sorted(
        {
            activity_id
            for collection in (
                evidence.goals,
                evidence.commands,
                evidence.files_changed,
                evidence.errors,
                evidence.outcomes,
            )
            for item in collection
            for activity_id in item.source_activity_ids
        }
    )
```

Every generated ref gets `harness=evidence.harness` and `activity_ids=_activity_ids(evidence)`. Keep existing commit/file behavior unchanged.

- [ ] **Step 7: Run the complete affected suite and commit**

Run:

```bash
uv run pytest \
  tests/unit/extraction/test_pipeline.py \
  tests/unit/models/test_outcome.py \
  tests/unit/services/test_outcomes.py \
  tests/unit/summarizers/test_outcome_prompt.py -q
uv run ruff check src/iiwi/models src/iiwi/extraction src/iiwi/services/outcomes.py src/iiwi/summarizers/outcome_prompt.py
uv run pyright
```

Expected: PASS. Existing single-harness Quick Review tests must remain green.

Commit:

```bash
git add src/iiwi/models src/iiwi/extraction/pipeline.py src/iiwi/services/outcomes.py \
  src/iiwi/summarizers/outcome_prompt.py tests/unit/extraction tests/unit/models \
  tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py
git commit -m "refactor: make outcome sources harness-safe"
```

---

### Task 2: Add timezone-aware Daily windows and the multi-harness scan coordinator

**Files:**
- Create: `src/iiwi/services/daily_scan.py`
- Modify: `src/iiwi/errors.py`
- Create: `tests/unit/services/test_daily_scan.py`

**Interfaces:**
- Consumes: existing one-harness `ScanService.scan() -> ScanResult`, `DateRange` half-open semantics, `HarnessSourceError`.
- Produces:

```python
@dataclass(frozen=True)
class DailyWindow:
    standup_date: date
    yesterday_start: datetime
    today_start: datetime
    now: datetime

    @property
    def period(self) -> DateRange: ...


@dataclass(frozen=True)
class DailyScanResult:
    window: DailyWindow
    scan: ScanResult
    successful_harnesses: tuple[str, ...]
    unavailable_harnesses: tuple[str, ...]
    coverage_warnings: tuple[str, ...]


class Scanner(Protocol):
    def scan(self) -> ScanResult: ...


def daily_window(now: datetime) -> DailyWindow: ...


class DailyScanCoordinator:
    def __init__(
        self,
        *,
        window: DailyWindow,
        scanners: Mapping[str, Scanner],
    ) -> None: ...

    def scan(self) -> DailyScanResult: ...
```

- `DailySourceUnavailableError(IiwiError)` carries `unavailable_harnesses: tuple[str, ...]` and an aggregate human-readable message.
- A harness is considered successful when its `ScanService.scan()` returns, even when its returned scan contains zero sessions. Only a thrown `HarnessSourceError` makes that harness unavailable.

- [ ] **Step 1: Write failing local-day boundary tests, including a DST transition**

Use `ZoneInfo("America/New_York")` to prove calendar semantics rather than 24-hour arithmetic:

```python
def test_daily_window_uses_local_midnights_across_dst() -> None:
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 3, 9, 10, 30, tzinfo=tz)
    window = daily_window(now)

    assert window.standup_date == date(2026, 3, 9)
    assert window.yesterday_start == datetime(2026, 3, 8, 0, 0, tzinfo=tz)
    assert window.today_start == datetime(2026, 3, 9, 0, 0, tzinfo=tz)
    assert window.period == DateRange(since=window.yesterday_start, until=now)
```

Also reject naive `now` with `ValueError("now must be timezone-aware")`.

- [ ] **Step 2: Write failing coordinator tests for success, partial failure, all failure, and no activity**

Create a `StubScanner` returning a supplied `ScanResult` and a `FailingScanner` raising `HarnessSourceError`. Pin:

```python
assert result.successful_harnesses == ("opencode", "codex")
assert result.unavailable_harnesses == ("claude-code",)
assert "Claude Code" in result.coverage_warnings[0] or "claude-code" in result.coverage_warnings[0]
assert result.scan.loaded_session_count == opencode.loaded_session_count + codex.loaded_session_count
```

For all-success/no-activity, assert `scan.loaded_session_count == 0` and no exception. For all failures, assert `DailySourceUnavailableError` and all attempted harness names are preserved.

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/services/test_daily_scan.py -q
```

Expected: FAIL because the module/classes do not exist.

- [ ] **Step 4: Implement calendar window derivation and deterministic scan merging**

Derive midnights by local date, not subtraction:

```python
def daily_window(now: datetime) -> DailyWindow:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.date()
    today_start = datetime.combine(today, time.min, tzinfo=now.tzinfo)
    yesterday_start = datetime.combine(
        today - timedelta(days=1),
        time.min,
        tzinfo=now.tzinfo,
    )
    return DailyWindow(today, yesterday_start, today_start, now)
```

`DailyScanCoordinator.scan()` iterates `scanners` in insertion order for stable warnings, catches only `HarnessSourceError`, and merges returned scans into one `ScanResult` whose `period` is `window.period`, counts are summed, resolved sessions are concatenated, warnings are concatenated, and `sessions_by_repository` is recomputed with `group_resolved_sessions(merged_sessions)`. Never mutate source results.

If no scanner returns successfully, raise `DailySourceUnavailableError` instead of manufacturing an empty result.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
uv run pytest tests/unit/services/test_daily_scan.py tests/integration/test_scan_service.py -q
uv run ruff check src/iiwi/services/daily_scan.py src/iiwi/errors.py tests/unit/services/test_daily_scan.py
uv run pyright
```

Expected: PASS; existing single-harness scan behavior remains unchanged.

Commit:

```bash
git add src/iiwi/services/daily_scan.py src/iiwi/errors.py tests/unit/services/test_daily_scan.py
git commit -m "feat: coordinate daily scans across harnesses"
```

---

### Task 3: Model Daily review state and project grouped evidence into Yesterday / Today / Blockers

**Files:**
- Create: `src/iiwi/models/daily.py`
- Modify: `src/iiwi/models/__init__.py`
- Create: `src/iiwi/services/daily_projection.py`
- Create: `tests/unit/models/test_daily.py`
- Create: `tests/unit/services/test_daily_projection.py`

**Interfaces:**
- Consumes: `DailyScanResult`, grouped `OutcomeSynthesisResult.outcomes`, `SessionEvidence` from `extract_evidence`, `EvidenceStatus`, `EvidenceConfidence`, `OutcomeStatus`, `EvidenceRef`, and activity timestamps from merged `ScanResult`.
- Produces:

```python
class DailySection(StrEnum):
    YESTERDAY = "yesterday"
    TODAY = "today"
    BLOCKERS = "blockers"


class DailyStatementSource(StrEnum):
    ACTIVITY_YESTERDAY = "activity_yesterday"
    ACTIVITY_TODAY = "activity_today"
    SUGGESTED_FROM_YESTERDAY = "suggested_from_yesterday"
    DETECTED_BLOCKER = "detected_blocker"
    USER_ADDED = "user_added"
    FALLBACK = "fallback"


class DailySectionItem(BaseModel):
    statement: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    included: bool = True
    rank: int = 0
    bucket: OutcomeBucket = OutcomeBucket.PRIMARY
    user_edited: bool = False
    source: DailyStatementSource
    new_activity: bool = False


class DailyStandupWorkItem(BaseModel):
    id: str
    source_outcome_ids: list[str] = Field(default_factory=list)
    repository_ids: list[str] = Field(default_factory=list)
    yesterday: DailySectionItem | None = None
    today: DailySectionItem | None = None
    blocker: DailySectionItem | None = None


class DailyStandupDraft(BaseModel):
    standup_date: date
    scan_since: datetime
    scan_until: datetime
    work_items: list[DailyStandupWorkItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    successful_harnesses: list[str] = Field(default_factory=list)
    unavailable_harnesses: list[str] = Field(default_factory=list)
    fallback: bool = False
```

`DailyStandupDraft` methods:

```python
def ordered_items(self, section: DailySection) -> list[tuple[DailyStandupWorkItem, DailySectionItem]]: ...
def toggle_included(self, section: DailySection, work_item_id: str) -> None: ...
def move(self, section: DailySection, work_item_id: str, delta: int) -> None: ...
def edit(self, section: DailySection, work_item_id: str, statement: str) -> None: ...
def add_user_item(self, section: DailySection, statement: str) -> DailyStandupWorkItem: ...
```

Service functions:

```python
def project_daily_standup(
    *,
    daily_scan: DailyScanResult,
    outcomes: list[Outcome],
) -> DailyStandupDraft: ...


def build_daily_fallback(*, daily_scan: DailyScanResult) -> DailyStandupDraft: ...
```

- [ ] **Step 1: Write failing model mutation tests**

Pin section ownership and review semantics:

```python
def test_edit_marks_only_that_section_as_reviewer_owned() -> None:
    draft = sample_daily_draft()
    draft.edit(DailySection.TODAY, "work-1", "Finish the renderer")
    work = draft.work_items[0]
    assert work.today.statement == "Finish the renderer"
    assert work.today.user_edited is True
    assert work.yesterday.user_edited is False


def test_add_user_item_needs_no_evidence() -> None:
    draft = empty_daily_draft()
    work = draft.add_user_item(DailySection.BLOCKERS, "Waiting on staging access")
    assert work.blocker.source is DailyStatementSource.USER_ADDED
    assert work.blocker.evidence_refs == []
```

Test `move` only swaps within the selected section and `toggle_included` on a More item promotes it to primary, matching general Quick Review behavior.

- [ ] **Step 2: Write failing timestamp-projection tests**

Construct one resolved session spanning midnight with activity ids `y1` at yesterday 16:00 and `t1` at today 09:00, and an `Outcome` whose evidence ref points to both ids. Assert one `DailyStandupWorkItem` contains both section items with the same Daily-local id and section-specific sources:

```python
assert work.yesterday.source is DailyStatementSource.ACTIVITY_YESTERDAY
assert work.today.source is DailyStatementSource.ACTIVITY_TODAY
assert work.yesterday.statement == outcome.title
assert work.today.statement == outcome.title
```

Also test an in-progress Yesterday-only outcome becomes a `SUGGESTED_FROM_YESTERDAY` Today candidate only when extracted evidence carries an explicit in-progress goal/unfinished signal; a completed Yesterday-only outcome does not create Today.

- [ ] **Step 3: Write failing blocker-resolution and selection-limit tests**

Pin conservative blocker behavior:

- a `BLOCKED` evidence item with no later completion becomes a blocker candidate;
- a later `COMPLETED` item in the same `(harness, session_id)` resolves it and removes the blocker;
- an unrelated completed item in another source session does not resolve it;
- ordinary errors with no `BLOCKED` evidence do not become blockers;
- Yesterday/Today candidates ranked 0–4 are `PRIMARY` + included, rank 5+ are `MORE` + excluded;
- blockers are not capped at five.

- [ ] **Step 4: Run the new tests and verify the modules are missing**

Run:

```bash
uv run pytest tests/unit/models/test_daily.py tests/unit/services/test_daily_projection.py -q
```

Expected: FAIL because Daily models/projection do not exist.

- [ ] **Step 5: Implement Daily models and deterministic activity lookup**

In `daily_projection.py`, build indexes once:

```python
activity_times: dict[tuple[str, str, str], datetime] = {}
resolved_by_source: dict[tuple[str, str], ResolvedSession] = {}
for resolved in daily_scan.scan.resolved_sessions:
    source = (resolved.session.harness, resolved.session.session_id)
    resolved_by_source[source] = resolved
    for activity in resolved.session.activities:
        if activity.timestamp is not None:
            activity_times[(*source, activity.activity_id)] = activity.timestamp
```

Partition refs solely through these timestamps and half-open boundaries:

```python
if window.yesterday_start <= ts < window.today_start:
    yesterday_refs.append(...)
elif window.today_start <= ts < window.now:
    today_refs.append(...)
```

Do not classify timestamp-less ids.

Daily-local ids are newly generated once with `uuid4().hex`; source outcome ids are diagnostic only.

- [ ] **Step 6: Implement Today suggestion and unresolved-blocker helpers conservatively**

Extract evidence for the relevant resolved sources locally. An inferred Today candidate requires both:

```python
outcome.status is OutcomeStatus.IN_PROGRESS
```

and at least one Yesterday-window evidence item with `status is EvidenceStatus.IN_PROGRESS` from a goal/outcome carrying a source activity id. If no explicit signal exists, omit Today.

For blockers, compare activity timestamps within the same source session. A `BLOCKED` item is unresolved only when there is no later `COMPLETED` evidence item in that source session. Use the blocked evidence text as the blocker statement so fallback and normal mode do not fabricate a cause.

- [ ] **Step 7: Implement deterministic fallback from local evidence**

`build_daily_fallback` does not call a model. For each resolved session, extract local evidence and produce a work item anchored to the best available local statement in this order:

1. latest assistant-claim/outcome text in the relevant section;
2. first meaningful goal text;
3. redacted session title;
4. repository display name.

It uses the same timestamp partition and blocker helper, never creates a speculative Today item without the explicit in-progress signal above, sets `fallback=True`, and marks generated section items `source=FALLBACK` except detected blockers, which remain `DETECTED_BLOCKER`.

- [ ] **Step 8: Run focused tests and commit**

Run:

```bash
uv run pytest tests/unit/models/test_daily.py tests/unit/services/test_daily_projection.py -q
uv run ruff check src/iiwi/models/daily.py src/iiwi/services/daily_projection.py tests/unit/models/test_daily.py tests/unit/services/test_daily_projection.py
uv run pyright
```

Expected: PASS.

Commit:

```bash
git add src/iiwi/models/daily.py src/iiwi/models/__init__.py \
  src/iiwi/services/daily_projection.py tests/unit/models/test_daily.py \
  tests/unit/services/test_daily_projection.py
git commit -m "feat: project evidence into daily standup sections"
```

---

### Task 4: Persist and reconcile same-day reviewed drafts

**Files:**
- Create: `src/iiwi/services/daily_reconcile.py`
- Create: `src/iiwi/daily_state.py`
- Create: `tests/unit/services/test_daily_reconcile.py`
- Create: `tests/unit/test_daily_state.py`

**Interfaces:**
- Consumes: `DailyStandupDraft`, `DailyStandupWorkItem`, `DailySectionItem`, `EvidenceRef`, `atomic_secure_write`, `platformdirs.user_data_dir`.
- Produces:

```python
DAILY_STATE_DIR_VARIABLE = "IIWI_DAILY_STATE_DIR"
DAILY_STATE_RETENTION_DAYS = 30


@dataclass(frozen=True)
class DailyStateLoadResult:
    draft: DailyStandupDraft | None
    warning: str | None = None


def daily_state_directory() -> Path: ...
def daily_state_path(standup_date: date, *, directory: Path | None = None) -> Path: ...
def load_daily_draft(standup_date: date, *, directory: Path | None = None) -> DailyStateLoadResult: ...
def save_daily_draft(draft: DailyStandupDraft, *, directory: Path | None = None) -> None: ...
def cleanup_daily_state(
    today: date,
    *,
    directory: Path | None = None,
    retention_days: int = DAILY_STATE_RETENTION_DAYS,
) -> None: ...


def reconcile_daily_draft(
    previous: DailyStandupDraft | None,
    fresh: DailyStandupDraft,
) -> DailyStandupDraft: ...
```

- [ ] **Step 1: Write failing state-path, permission, corruption, and retention tests**

Pin the feature-new path without legacy migration:

```python
def test_daily_state_uses_its_own_user_data_subdirectory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IIWI_DAILY_STATE_DIR", str(tmp_path / "daily"))
    assert daily_state_path(date(2026, 8, 13)) == tmp_path / "daily" / "2026-08-13.json"
```

Test save/load round trip, mode `0600` on POSIX, parent mode `0700` where supported, and corrupt JSON returning `DailyStateLoadResult(draft=None, warning=...)` instead of raising or silently pretending no previous review existed.

For cleanup, create dates 31 days old, exactly 30 days old, today, and a non-date file. Assert only files with a valid `YYYY-MM-DD.json` name older than the retention threshold are removed. Monkeypatch unlink to raise for one file and assert cleanup remains non-fatal.

- [ ] **Step 2: Write failing reconciliation tests for reviewer priority**

Cover each approved rule independently:

```python
def test_reconcile_preserves_reviewer_edit_and_adds_new_evidence() -> None:
    previous = reviewed_draft(statement="My wording", user_edited=True)
    fresh = fresh_matching_draft(statement="Machine wording", extra_activity="a2")

    merged = reconcile_daily_draft(previous, fresh)

    item = merged.work_items[0].today
    assert item.statement == "My wording"
    assert item.user_edited is True
    assert "a2" in {aid for ref in item.evidence_refs for aid in ref.activity_ids}
    assert item.new_activity is True
```

Also pin: exclusions remain excluded; user-added items survive; previous order survives among matched items; unmatched fresh work is appended and marked `new_activity`; previous unmatched reviewed work survives partial-source gaps.

- [ ] **Step 3: Write failing identity-match tests for exact, coarse, ambiguous, and no overlap**

Use refs to assert this priority:

1. exact `(harness, session_id, activity_id)` overlap matches;
2. otherwise one unambiguous `(harness, session_id)` overlap matches;
3. if a fresh item could match two previous items through coarse overlap, neither prior item is silently merged and the fresh item remains a new candidate with a new Daily-local id;
4. no overlap creates a new item.

Explicitly include same raw `session_id` from two different harnesses and assert they do not match.

- [ ] **Step 4: Run the new tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/services/test_daily_reconcile.py tests/unit/test_daily_state.py -q
```

Expected: FAIL because the modules do not exist.

- [ ] **Step 5: Implement evidence identity helpers and reconciliation without prose matching**

Use only evidence identity, never title similarity:

```python
def _activity_keys(item: DailySectionItem) -> set[tuple[str, str, str]]:
    return {
        (ref.harness, ref.session_id, activity_id)
        for ref in item.evidence_refs
        if ref.harness is not None
        for activity_id in ref.activity_ids
    }


def _session_keys(item: DailySectionItem) -> set[tuple[str, str]]:
    return {
        (ref.harness, ref.session_id)
        for ref in item.evidence_refs
        if ref.harness is not None
    }
```

Aggregate keys across all three sections of one work item. Find exactly one previous match; multiple candidates are ambiguous and therefore not a match.

When matched, copy the previous Daily-local `id`, then merge section-by-section. Preserve previous `statement` when `user_edited` or `source is USER_ADDED`, preserve `included`, preserve old relative order, union refs, and set `new_activity=True` when fresh introduces a previously unseen exact activity key.

- [ ] **Step 6: Implement owner-only Daily state persistence**

`daily_state_directory()` uses `IIWI_DAILY_STATE_DIR` when set, otherwise `Path(user_data_dir("iiwi")) / "daily"`. Create the directory with mode `0700`; POSIX `chmod(0o700)` after creation so an existing permissive umask does not weaken it.

Serialize with:

```python
content = draft.model_dump_json(indent=2) + "\n"
atomic_secure_write(destination, content, force=True)
```

`atomic_secure_write` already produces owner-only report/state files on POSIX. Wrap no new copy of its atomic-write algorithm.

- [ ] **Step 7: Run focused tests and commit**

Run:

```bash
uv run pytest tests/unit/services/test_daily_reconcile.py tests/unit/test_daily_state.py tests/unit/test_state.py -q
uv run ruff check src/iiwi/services/daily_reconcile.py src/iiwi/daily_state.py tests/unit/services/test_daily_reconcile.py tests/unit/test_daily_state.py
uv run pyright
```

Expected: PASS; ordinary selection memory still passes unchanged.

Commit:

```bash
git add src/iiwi/services/daily_reconcile.py src/iiwi/daily_state.py \
  tests/unit/services/test_daily_reconcile.py tests/unit/test_daily_state.py
git commit -m "feat: preserve reviewed daily standup state"
```

---

### Task 5: Render exact Daily Markdown and write the same-day artifact safely

**Files:**
- Create: `src/iiwi/renderers/daily_markdown.py`
- Create: `src/iiwi/services/daily_report.py`
- Create: `tests/unit/renderers/test_daily_markdown.py`
- Create: `tests/unit/services/test_daily_report.py`

**Interfaces:**
- Consumes: reviewed `DailyStandupDraft`, configured output directory, `atomic_secure_write`.
- Produces:

```python
def render_daily_standup(draft: DailyStandupDraft) -> str: ...

def daily_output_path(output_directory: Path, standup_date: date) -> Path: ...


@dataclass(frozen=True)
class DailyReportResult:
    content: str
    output_path: Path | None
    repository_count: int
    session_count: int


class DailyReportService:
    def preview(
        self,
        draft: DailyStandupDraft,
        *,
        repository_count: int,
        session_count: int,
    ) -> DailyReportResult: ...

    def generate(
        self,
        draft: DailyStandupDraft,
        *,
        output_path: Path,
        repository_count: int,
        session_count: int,
    ) -> DailyReportResult: ...
```

- [ ] **Step 1: Write failing Markdown contract tests**

Pin exact order/content, including empty sections and all repository labels:

```python
assert render_daily_standup(draft) == (
    "# Daily Standup — 2026-08-13\n\n"
    "> Warning: OpenCode activity could not be loaded.\n\n"
    "## Yesterday\n"
    "- [api, sdk, web] Finished the authentication migration.\n\n"
    "## Today\n"
    "- [iiwi] Implement the Daily Standup draft.\n\n"
    "## Blockers\n"
    "- None\n"
)
```

Also assert:

- review labels (`Activity today`, `User added`, `Fallback draft`, `New activity`) never appear;
- excluded items never appear;
- a user-added item with no repositories renders `- Manual statement`, never `- [] Manual statement`;
- every empty section renders `- None`.

- [ ] **Step 2: Write failing preview/write parity and overwrite tests**

Test:

```python
preview = service.preview(draft, repository_count=2, session_count=4)
generated = service.generate(
    draft,
    output_path=path,
    repository_count=2,
    session_count=4,
)
assert preview.content == generated.content == path.read_text(encoding="utf-8")
```

Write an old value to the same path first and assert `generate` replaces it without `ReportAlreadyExistsError`. Monkeypatch `atomic_secure_write` to raise `ReportOutputError` and assert the error propagates as a write failure rather than returning success.

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/renderers/test_daily_markdown.py tests/unit/services/test_daily_report.py -q
```

Expected: FAIL because Daily renderer/report service do not exist.

- [ ] **Step 4: Implement one pure renderer and one write boundary**

Renderer logic is deterministic string assembly; no template/model call. Repository labels are computed from `work.repository_ids`, sorted/deduplicated once:

```python
def _bullet(work: DailyStandupWorkItem, item: DailySectionItem) -> str:
    repositories = sorted(set(work.repository_ids))
    prefix = f"[{', '.join(repositories)}] " if repositories else ""
    return f"- {prefix}{item.statement}"
```

Coverage warnings are the draft warnings that describe unavailable harnesses and are emitted immediately after the title as Markdown blockquotes. Do not leak internal persistence/synthesis warnings into final Markdown unless they represent source coverage.

`daily_output_path` returns `output_directory / f"daily-standup-{standup_date:%Y-%m-%d}.md"`.

`DailyReportService.generate` calls exactly:

```python
atomic_secure_write(output_path, content, force=True)
```

and does no synthesis, projection, reconcile, or state mutation.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
uv run pytest tests/unit/renderers/test_daily_markdown.py tests/unit/services/test_daily_report.py tests/unit/security/test_secure_files.py -q
uv run ruff check src/iiwi/renderers/daily_markdown.py src/iiwi/services/daily_report.py tests/unit/renderers/test_daily_markdown.py tests/unit/services/test_daily_report.py
uv run pyright
```

Expected: PASS.

Commit:

```bash
git add src/iiwi/renderers/daily_markdown.py src/iiwi/services/daily_report.py \
  tests/unit/renderers/test_daily_markdown.py tests/unit/services/test_daily_report.py
git commit -m "feat: render and write daily standups"
```

---

### Task 6: Evolve History for first-class Daily Standup entries

**Files:**
- Modify: `src/iiwi/history.py`
- Modify: `src/iiwi/logging.py`
- Modify: `src/iiwi/interactive/render.py`
- Modify: `src/iiwi/cli.py`
- Modify: `src/iiwi/interactive/cli_actions.py`
- Modify: `tests/unit/test_history.py`
- Modify: `tests/unit/interactive/test_render.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: existing append-only JSONL history and absolute output-path anchoring.
- Produces:

```python
class HistoryKind(StrEnum):
    REPORT = "report"
    DAILY_STANDUP = "daily_standup"


@dataclass(frozen=True)
class HistoryEntry:
    generated_at: datetime
    since: datetime
    until: datetime
    output_path: Path
    repository_count: int
    session_count: int
    harness: str | None = None
    narrative: bool | None = None
    detail: str | None = None
    kind: HistoryKind = HistoryKind.REPORT
    harnesses: tuple[str, ...] = ()
    unavailable_harnesses: tuple[str, ...] = ()

    @property
    def effective_harnesses(self) -> tuple[str, ...]: ...
```

Existing general report call sites keep `harness=...`, `narrative=...`, `detail=...`. A new Daily entry uses `kind=DAILY_STANDUP`, `harness=None`, successful `harnesses`, failed `unavailable_harnesses`, and `narrative/detail=None`.

- [ ] **Step 1: Write failing backward-compatibility and Daily round-trip tests**

Keep every existing history test. Add an explicit old JSON line containing only the old fields and assert:

```python
entry.kind is HistoryKind.REPORT
entry.effective_harnesses == ("opencode",)
entry.unavailable_harnesses == ()
```

Add a Daily entry and round-trip:

```python
assert loaded.kind is HistoryKind.DAILY_STANDUP
assert loaded.harness is None
assert loaded.harnesses == ("opencode", "codex")
assert loaded.unavailable_harnesses == ("claude-code",)
assert loaded.narrative is None
assert loaded.detail is None
```

- [ ] **Step 2: Write failing human/interactive rendering tests**

Pin that a Daily history row/table says `Daily Standup` and never `multiple`; source coverage may be summarized in detail text but the artifact label stays Daily Standup. Existing report rows keep their current harness labels.

Also pin `history --json` emits `kind`, `harnesses`, and `unavailable_harnesses` for both new and old records after normalization.

- [ ] **Step 3: Run history/render tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/test_history.py tests/unit/interactive/test_render.py tests/integration/test_cli.py -q
```

Expected: FAIL because `HistoryEntry` has no kind/multi-harness fields and renderers assume one harness.

- [ ] **Step 4: Implement tolerant history decoding without rewriting old files**

In `read_history`, normalize one raw dict with defaults:

```python
kind = HistoryKind(raw.get("kind", HistoryKind.REPORT.value))
legacy_harness = raw.get("harness")
harnesses = tuple(raw.get("harnesses") or ())
if kind is HistoryKind.REPORT and not harnesses and isinstance(legacy_harness, str):
    harnesses = (legacy_harness,)
```

Do not migrate/rewrite previous lines. Preserve current corrupt-line containment and absolute-path behavior.

For append serialization, tuples may serialize through `asdict` to lists normally; keep ISO datetime handling unchanged.

- [ ] **Step 5: Update History display contracts and ordinary report call sites**

Make display code branch on `entry.kind`:

```python
def _history_kind_label(entry: HistoryEntry) -> str:
    if entry.kind is HistoryKind.DAILY_STANDUP:
        return "Daily Standup"
    return _harness_label(entry.harness or "report")
```

Do not fabricate a harness for Daily. Existing `_record_history`, `_generate`, and `_generate_reviewed` keep writing Report entries and should need only constructor compatibility changes caused by reordered/defaulted dataclass fields.

Daily history append itself is wired in Task 8 after successful Daily generation.

- [ ] **Step 6: Run affected tests and commit**

Run:

```bash
uv run pytest tests/unit/test_history.py tests/unit/interactive/test_render.py tests/integration/test_cli.py -q
uv run ruff check src/iiwi/history.py src/iiwi/logging.py src/iiwi/interactive/render.py src/iiwi/cli.py src/iiwi/interactive/cli_actions.py tests/unit/test_history.py
uv run pyright
```

Expected: PASS.

Commit:

```bash
git add src/iiwi/history.py src/iiwi/logging.py src/iiwi/interactive/render.py \
  src/iiwi/cli.py src/iiwi/interactive/cli_actions.py tests/unit/test_history.py \
  tests/unit/interactive/test_render.py tests/integration/test_cli.py
git commit -m "feat: record daily standups in history"
```

---

### Task 7: Add the Daily Quick Review screen and interactions

**Files:**
- Create: `src/iiwi/interactive/daily_review.py`
- Modify: `src/iiwi/interactive/models.py`
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `src/iiwi/interactive/render.py`
- Modify: `tests/unit/interactive/test_activity_first_home.py`
- Create: `tests/unit/interactive/test_daily_review.py`
- Create: `tests/unit/interactive/test_daily_review_render.py`
- Create: `tests/unit/interactive/test_daily_review_controller.py`
- Create: `tests/unit/interactive/test_daily_review_failures.py`
- Modify: `tests/unit/interactive/test_viewport_wrapping_regressions.py`

**Interfaces:**
- Consumes: `DailyStandupDraft` mutation methods, `DailySection`, `DailyReportResult`, existing `_paint`, report preview screen, recoverable-error screen, and existing keyboard helpers.
- Produces:

```python
@dataclass(frozen=True)
class DailyReviewRow:
    kind: str                 # section | item | more
    section: DailySection
    work_item_id: str | None = None


YESTERDAY_MORE_SECTION = "__daily_yesterday_more__"
TODAY_MORE_SECTION = "__daily_today_more__"


def visible_daily_review_rows(
    draft: DailyStandupDraft,
    expanded: set[str],
) -> list[DailyReviewRow]: ...
```

Add screens:

```python
Screen.DAILY_REVIEW
Screen.DAILY_RESULT
```

Extend `_State` with:

```python
daily_review: DailyStandupDraft | None = None
daily_cursor: int = 0
daily_message: str | None = None
daily_expanded: set[str] | None = None
daily_result: InteractiveReportResult | None = None
```

Extend `InteractiveActions` with exact seams:

```python
start_daily: Callable[[DailyStandupDraft | None], DailyStandupDraft]
continue_daily_empty: Callable[[tuple[str, ...]], DailyStandupDraft]
persist_daily: Callable[[DailyStandupDraft], str | None]
preview_daily: Callable[[DailyStandupDraft], InteractiveReportResult]
generate_daily: Callable[[DailyStandupDraft], InteractiveReportResult]
edit_daily_statement: Callable[[str], str | None]
add_daily_statement: Callable[[DailySection], str | None]
```

`persist_daily` returns a warning string on non-fatal persistence failure, else `None`; this keeps storage failure visible without taking the interactive app down.

- [ ] **Step 1: Write failing row-visibility tests**

Pin fixed section order and section-specific More behavior:

```python
assert [row.section for row in rows if row.kind == "section"] == [
    DailySection.YESTERDAY,
    DailySection.TODAY,
    DailySection.BLOCKERS,
]
```

Yesterday/Today More items are hidden until only their own disclosure id is expanded. Blockers are all visible and have no More disclosure. Empty sections still produce a section row so `a Add` has a current destination.

- [ ] **Step 2: Write failing rendering tests for provenance labels, viewport safety, and hints**

Render a mixed draft and assert visible text contains:

```text
Daily Standup — Aug 13
Yesterday
Today
Blockers
Activity today
Suggested from yesterday
Detected blocker
User added
New activity
```

but does not wrap any single-line row past the terminal width. Reuse the existing viewport regression pattern at narrow width/height and assert cursor/hints remain visible.

Hints must be exactly the approved interaction set; do not show `s Split`, report type, detail, or Next week.

- [ ] **Step 3: Write failing controller interaction tests**

Using fake `InteractiveActions`, pin:

- `Space` toggles only the focused section item and persists the draft;
- `e` replaces the focused statement and sets `user_edited` through the model method;
- uppercase `J/K` reorder only inside the focused section;
- `v` toggles evidence for the focused item;
- `a` adds to the focused section, including an empty section;
- `b` returns directly to Main;
- `p` calls `preview_daily`, sets `preview_return_screen=DAILY_REVIEW`, and opens existing `REPORT_PREVIEW`;
- returning from preview preserves the exact Daily draft object/decisions;
- `g` calls `generate_daily` and opens `DAILY_RESULT`;
- `DAILY_RESULT` offers Main menu and report path without a generic “Generate another report” action.

- [ ] **Step 4: Write failing source-error tests**

Introduce recoverable error kind `daily-source` with exact options:

```text
Retry
Continue with empty draft
Back
```

Pin Retry calls `start_daily(previous_daily_review)` again, Continue calls `continue_daily_empty(error.unavailable_harnesses)` and opens Daily Review, and Back returns Main. Add `unavailable_harnesses: tuple[str, ...] = ()` to `_ErrorState` rather than parsing names out of detail text.

Also pin Daily preview/write errors return to Daily Review, not general Outcome Review.

- [ ] **Step 5: Run the new interaction suite and verify it fails**

Run:

```bash
uv run pytest \
  tests/unit/interactive/test_daily_review.py \
  tests/unit/interactive/test_daily_review_render.py \
  tests/unit/interactive/test_daily_review_controller.py \
  tests/unit/interactive/test_daily_review_failures.py -q
```

Expected: FAIL because Daily screens/actions do not exist.

- [ ] **Step 6: Implement the focused Daily row module and renderer**

Keep row derivation in `interactive/daily_review.py`; render.py consumes those rows. Render one header, fixed section labels, item summaries, optional provenance subline for the focused/visible item, evidence detail using existing `EvidenceRef` values, and packed hints through existing `_print_hints`.

The renderer must use the same display-line budgeting strategy as Outcome Quick Review: rows are blocks, focus remains in the visible window, and all summary/control rows use no-wrap/ellipsis. Do not introduce raw `console.print(Text(...))` lines that can wrap the cursor off screen.

- [ ] **Step 7: Implement Daily dispatch/state transitions without changing general Outcome Review**

Add `_daily_review_key`, `_begin_daily_review`, `_generate_daily_review`, and `_daily_result_key` as separate handlers. Mutation flow is always:

```python
mutate draft
warning = actions.persist_daily(draft)
state.daily_message = warning
```

A persistence warning does not roll back the in-memory mutation.

`_begin_daily_review` catches `DailySourceUnavailableError` and builds the `daily-source` recoverable error. It does not catch `OutcomeSynthesisError`; Task 8's Daily workflow converts that to a fallback draft before the controller sees it.

- [ ] **Step 8: Add main-menu positioning and viewport regression coverage**

Insert `Daily Standup` after `Review Activity`:

```python
_MAIN_OPTIONS = [
    "Review Activity",
    "Daily Standup",
    "Generate Report",
    "History",
    "Check Setup",
    "Settings",
]
```

Description: `"Draft yesterday, today and blockers"` or shorter if needed to preserve the existing one-line menu layout. Update the menu dispatch test so selecting Daily invokes `_begin_daily_review`, not Report Setup.

- [ ] **Step 9: Run interactive tests and commit**

Run:

```bash
uv run pytest tests/unit/interactive -q
uv run ruff check src/iiwi/interactive tests/unit/interactive
uv run pyright
```

Expected: PASS, including existing Outcome Quick Review and History screens.

Commit:

```bash
git add src/iiwi/interactive tests/unit/interactive
git commit -m "feat: add daily quick review"
```

---

### Task 8: Wire the Daily workflow, state, history, main menu, and `iiwi daily`

**Files:**
- Create: `src/iiwi/services/daily_workflow.py`
- Modify: `src/iiwi/interactive/cli_actions.py`
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `src/iiwi/cli.py`
- Modify: `src/iiwi/history.py` only if constructor helpers are needed; do not reopen schema design.
- Create: `tests/unit/services/test_daily_workflow.py`
- Modify: `tests/unit/interactive/test_cli_actions.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/test_interactive_cli.py`

**Interfaces:**
- Consumes: Tasks 2–6 services, `_enabled_harnesses`, `_build_scan_service`, `OutcomeSynthesisService`, `OpenCodeRunner`, Daily state helpers, `append_history`.
- Produces:

```python
class DailyWorkflowService:
    def __init__(
        self,
        *,
        scan_coordinator_factory: Callable[[DailyWindow], DailyScanCoordinator],
        outcome_service: OutcomeSynthesisService,
        now_factory: Callable[[], datetime],
    ) -> None: ...

    def refresh(
        self,
        previous: DailyStandupDraft | None = None,
    ) -> tuple[DailyStandupDraft, DailyScanResult]: ...
```

Behavior:

1. one `now = now_factory()`;
2. derive DailyWindow;
3. cleanup old state non-fatally;
4. scan all enabled harnesses;
5. try existing outcome synthesis;
6. on `OutcomeSynthesisError`, build deterministic fallback;
7. append source-coverage warnings and state-load warning if present;
8. reconcile fresh draft with same-day previous/persisted draft;
9. return reviewed draft + scan metadata needed for final counts/history.

`run_interactive` gains:

```python
def run_interactive(
    *,
    actions: InteractiveActions,
    input_source: KeySource,
    console: Console,
    initial_screen: Screen = Screen.MAIN,
) -> None: ...
```

If `initial_screen is Screen.DAILY_REVIEW`, initialize state and call `_begin_daily_review` before the first paint.

- [ ] **Step 1: Write failing workflow tests for normal synthesis, fallback, state reconcile, and no activity**

Use injected fakes. Pin that `now_factory` is called once per refresh and the same time drives title/window. Normal path calls `OutcomeSynthesisService.synthesize` once. A raised `OutcomeSynthesisError` returns `draft.fallback is True` and still produces a draft. Zero-session successful scan returns a normal empty draft.

When an existing same-day state is supplied, assert reconcile preserves reviewer wording. The service never loads yesterday's state file when `standup_date` advances.

- [ ] **Step 2: Write failing cli-action wiring tests for all enabled harnesses**

Monkeypatch `_enabled_harnesses` to return OpenCode, Claude Code, Codex and `_build_scan_service` to record calls. `start_daily` must build all three with:

```python
root_only=False
period=window.period
```

OpenCode sanitize uses its configured default; non-OpenCode sources remain unsanitized because they do not expose that option. Assert each scanner receives the identical `DateRange` object/value.

- [ ] **Step 3: Write failing `iiwi daily` command tests**

Pin help/discoverability:

```python
result = runner.invoke(app, ["daily", "--help"])
assert result.exit_code == 0
assert "Daily Standup" in result.output or "daily standup" in result.output.lower()
```

Pin non-TTY rejection with a clear configuration error. For a forced terminal/key-navigation test, monkeypatch `run_interactive` and assert:

```python
assert captured["initial_screen"] is Screen.DAILY_REVIEW
```

There is no `--harness`, `--period`, `--days`, or `--no-review` option on this command.

- [ ] **Step 4: Run the new workflow/CLI tests and verify they fail**

Run:

```bash
uv run pytest \
  tests/unit/services/test_daily_workflow.py \
  tests/unit/interactive/test_cli_actions.py \
  tests/unit/test_cli.py \
  tests/integration/test_interactive_cli.py -q
```

Expected: FAIL because the workflow and command are not wired.

- [ ] **Step 5: Implement `DailyWorkflowService` and keep synthesis fallback below the controller**

The workflow service owns model/fallback/reconcile orchestration so the interactive action is thin. It may accept already-loaded `previous` from the controller; when `previous is None`, load today's state via `load_daily_draft`. If load returns a warning, append it to review warnings only; final Markdown filtering in Task 5 ensures a local-state warning does not masquerade as a source-coverage warning.

Catch only `OutcomeSynthesisError` for fallback. Let `DailySourceUnavailableError` propagate so the controller shows Retry / Continue / Back.

- [ ] **Step 6: Implement Daily interactive actions and successful-generation side effects**

In `build_interactive_actions`, wire:

```python
start_daily=_start_daily
continue_daily_empty=_continue_daily_empty
persist_daily=_persist_daily
preview_daily=_preview_daily
generate_daily=_generate_daily
edit_daily_statement=_edit_daily_statement
add_daily_statement=_add_daily_statement
```

`_generate_daily` sequence is strict:

1. render/write through `DailyReportService.generate`;
2. if write succeeds, save the latest draft state;
3. append one `HistoryKind.DAILY_STANDUP` entry with successful/unavailable harnesses and absolute output path;
4. history failure is non-fatal, following existing report bookkeeping semantics;
5. return `InteractiveReportResult`.

Store the latest `DailyScanResult` counts needed for result/history in the Daily draft metadata or in a Daily action closure keyed to the current draft; prefer explicit fields on `DailyStandupDraft` (`repository_count`, `session_count`) if this keeps callbacks stateless. If adding those fields, update Task 3 model tests accordingly rather than maintaining hidden module globals.

- [ ] **Step 7: Implement `continue_daily_empty` explicitly**

When all sources failed and the reviewer chooses Continue:

```python
DailyStandupDraft(
    standup_date=window.standup_date,
    scan_since=window.yesterday_start,
    scan_until=window.now,
    work_items=[],
    successful_harnesses=[],
    unavailable_harnesses=list(unavailable_harnesses),
    warnings=[coverage_warning_for_all_sources],
)
```

Then reconcile with any same-day previous reviewed draft so manual/reviewer-owned content is not erased merely because sources are temporarily unavailable.

- [ ] **Step 8: Add direct-start support and `iiwi daily`**

Change `run_interactive` to accept `initial_screen=Screen.MAIN`. Before entering the paint loop:

```python
state = _State(screen=initial_screen)
if initial_screen is Screen.DAILY_REVIEW:
    _begin_daily_review(state, actions)
```

Add:

```python
@app.command()
def daily() -> None:
    """Draft yesterday, today and blockers from all enabled coding agents."""
    reporter = ConsoleReporter()
    try:
        _require_a_terminal("daily needs a terminal; run `iiwi daily` from an interactive terminal")
        run_interactive(
            actions=build_interactive_actions(),
            input_source=TerminalInput(),
            console=reporter.console,
            initial_screen=Screen.DAILY_REVIEW,
        )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
```

Import `Screen` without creating a cycle; `cli.py` already imports interactive modules, while `cli_actions.py` keeps imports of `iiwi.cli` inside callbacks.

- [ ] **Step 9: Run workflow/CLI tests and commit**

Run:

```bash
uv run pytest \
  tests/unit/services/test_daily_workflow.py \
  tests/unit/interactive/test_cli_actions.py \
  tests/unit/test_cli.py \
  tests/integration/test_interactive_cli.py -q
uv run ruff check src/iiwi/services/daily_workflow.py src/iiwi/interactive/cli_actions.py src/iiwi/interactive/controller.py src/iiwi/cli.py tests/unit/services/test_daily_workflow.py
uv run pyright
```

Expected: PASS.

Commit:

```bash
git add src/iiwi/services/daily_workflow.py src/iiwi/interactive/cli_actions.py \
  src/iiwi/interactive/controller.py src/iiwi/cli.py tests/unit/services/test_daily_workflow.py \
  tests/unit/interactive/test_cli_actions.py tests/unit/test_cli.py \
  tests/integration/test_interactive_cli.py
git commit -m "feat: wire the daily standup workflow"
```

---

### Task 9: Prove the end-to-end contract and document the feature

**Files:**
- Create: `tests/integration/test_daily_standup.py`
- Create: `docs/daily-standup.md`
- Modify: `README.md`
- Modify: `README.zh-TW.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/evidence-first-quick-review.md`
- Modify: `tests/unit/test_documentation.py`
- Modify: `tests/unit/test_interactive_documentation.py`

**Interfaces:**
- Consumes: the complete Daily workflow from Tasks 1–8.
- Produces: executable acceptance coverage for the approved design and user-facing documentation that does not imply general Quick Review gained persistent drafts.

- [ ] **Step 1: Write integration fixtures that exercise two calendar days and colliding harness ids**

Build test doubles/fake sources with:

- OpenCode session `same-id` containing Yesterday activity;
- Claude Code session `same-id` containing Today activity;
- Codex session containing an unresolved blocker;
- one cross-repository grouped work objective;
- stable timezone `Asia/Taipei` and injected `now=datetime(2026, 8, 13, 11, 42, tzinfo=ZoneInfo("Asia/Taipei"))`.

Use temp Daily state/history/output paths through the existing env overrides plus `IIWI_DAILY_STATE_DIR` from Task 4 so tests never touch real user data.

- [ ] **Step 2: Write acceptance tests for the first run**

Assert the generated/preview draft contract:

- both colliding raw ids survive because harness disambiguates them;
- Yesterday and Today are determined by activity timestamps;
- cross-repository final bullet lists every repository;
- Today actual activity is marked in review but the marker is absent from final Markdown;
- unresolved blocker appears; resolved failures do not;
- final section order is fixed;
- Preview content equals generated file bytes;
- generated filename is `daily-standup-2026-08-13.md`.

- [ ] **Step 3: Write acceptance tests for same-day refresh and overwrite**

After the first reviewed draft:

1. edit one Today statement;
2. exclude one Yesterday candidate;
3. add a manual Blocker;
4. save state;
5. add a new Today activity to the fake source;
6. refresh again on 2026-08-13.

Assert wording/exclusion/manual item/order survive, the new activity appears as `New activity`, evidence refs contain the new activity id, and Generate replaces the same output file rather than raising a report conflict.

- [ ] **Step 4: Write acceptance tests for partial/all failure, zero activity, fallback, and next-day reset**

Pin all approved edge cases:

- one unavailable harness -> normal draft + warning below title in final Markdown;
- all harnesses unavailable -> `DailySourceUnavailableError` until the controller chooses Continue; empty/manual Daily is then possible with coverage warning;
- all successful but zero sessions -> empty normal review, not an error;
- outcome grouping throws `OutcomeSynthesisError` -> `fallback=True` draft, no fatal source error, and no speculative Today plan;
- on 2026-08-14 the workflow loads only `2026-08-14.json`; a 2026-08-13 Today plan by itself is not copied forward.

- [ ] **Step 5: Write acceptance tests for History**

Generate one Daily standup and assert the newest history entry has:

```python
assert entry.kind is HistoryKind.DAILY_STANDUP
assert entry.harnesses == ("opencode", "claude-code", "codex")
assert entry.unavailable_harnesses == ()
assert entry.output_path.is_absolute()
```

For partial failure, successful and unavailable harnesses are recorded separately. Existing old report history fixtures remain readable.

- [ ] **Step 6: Run the Daily integration tests and fix only contract failures**

Run:

```bash
uv run pytest tests/integration/test_daily_standup.py -q
```

Expected: PASS. If a test exposes a missing contract, fix the owning Task 1–8 module rather than adding special-case behavior in the integration test or CLI layer.

- [ ] **Step 7: Add user-facing documentation and failing doc assertions first**

Before editing docs, extend documentation tests to require:

- `iiwi daily` appears in `README.md`, `README.zh-TW.md`, and `docs/cli-reference.md`;
- `docs/daily-standup.md` is linked from the appropriate guide/index location already enforced by documentation tests;
- general Quick Review documentation still says its normal draft is in-memory only, with a sentence that Daily Standup is the explicit persistent same-day exception.

Run:

```bash
uv run pytest tests/unit/test_documentation.py tests/unit/test_interactive_documentation.py -q
```

Expected: FAIL until documentation is updated.

- [ ] **Step 8: Write concise product documentation from the approved contract**

`docs/daily-standup.md` must cover:

```text
iiwi daily
→ scans all enabled harnesses
→ Yesterday / Today / Blockers
→ Quick Review
→ Preview
→ Generate reports/daily-standup-YYYY-MM-DD.md
```

Explain actual Today vs suggested Today labels, partial-source warning behavior, same-day reconcile/persistence, `- None`, and the 30-day local review-state retention. Do not expose internal source-id encoding or implementation-only model names in user docs.

Update README feature bullets and CLI reference without turning Daily into the default/general report command.

- [ ] **Step 9: Run the complete verification suite**

Run all project gates:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

Expected: all tests PASS, Ruff reports no violations, Pyright reports no errors.

Then run the targeted acceptance set one more time so a full-suite failure cannot hide the feature's critical contract:

```bash
uv run pytest \
  tests/integration/test_daily_standup.py \
  tests/unit/services/test_daily_scan.py \
  tests/unit/services/test_daily_projection.py \
  tests/unit/services/test_daily_reconcile.py \
  tests/unit/interactive/test_daily_review_controller.py \
  tests/unit/interactive/test_daily_review_failures.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit the integration coverage and docs**

Commit:

```bash
git add tests/integration/test_daily_standup.py docs/daily-standup.md README.md README.zh-TW.md \
  docs/cli-reference.md docs/evidence-first-quick-review.md tests/unit/test_documentation.py \
  tests/unit/test_interactive_documentation.py
git commit -m "docs: document the daily standup workflow"
```

---

## Final implementation review checklist

Before opening a PR or claiming the implementation is complete, verify every item below against the design spec rather than relying only on green tests:

- [ ] `iiwi daily` and Main → Daily Standup enter the same Daily review flow.
- [ ] No Daily period picker, harness picker, Report type, Detail, Next week, Split, or `--no-review` was added.
- [ ] One timezone-aware union scan covers yesterday local midnight through one captured `now`.
- [ ] Every enabled harness is attempted and subagents are included.
- [ ] Cross-harness source maps never use raw `session_id` alone.
- [ ] The LLM cannot assign activities to Yesterday/Today.
- [ ] Yesterday/Today candidate selection starts at five primary items, with More candidates retained.
- [ ] Today inferred from Yesterday is supported by explicit unfinished/in-progress evidence and is review-labeled as a suggestion.
- [ ] Blockers require unresolved `BLOCKED` evidence and later completion clears them.
- [ ] User-added items need no evidence and are never auto-rewritten.
- [ ] Same-day refresh preserves edit/exclude/order/manual decisions and adds new evidence/candidates.
- [ ] Ambiguous evidence overlap never silently merges two prior reviewed work items.
- [ ] New calendar date does not carry the previous day's Today plan.
- [ ] No-activity path remains a usable empty review.
- [ ] Partial harness failure continues with an artifact-level coverage warning.
- [ ] All-harness failure uses Retry / Continue with empty draft / Back.
- [ ] Synthesis failure uses deterministic fallback rather than the general session-based report fallback.
- [ ] Preview and Generate render byte-identical Daily Markdown from the same reviewed draft.
- [ ] Same-day Generate atomically replaces only that day's Daily output file.
- [ ] Daily state is owner-only where supported, contains references/review state rather than full transcripts, and cleans entries older than 30 days opportunistically.
- [ ] History labels the artifact `Daily Standup`, records successful and unavailable harnesses separately, and still loads every old JSONL fixture.
- [ ] Existing Report Setup, Session Review, standard Outcome Quick Review, History, Settings, and CLI report tests remain green.
- [ ] `uv run pytest`, `uv run ruff check .`, and `uv run pyright` all pass immediately before handoff.
