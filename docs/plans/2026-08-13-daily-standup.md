# Daily Standup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class `iiwi daily` workflow that automatically scans all enabled coding-agent harnesses, drafts a short Yesterday / Today / Blockers standup from evidence, lets the user review it, preserves reviewer decisions across same-day reruns, previews the exact Markdown that will be written, and records the generated artifact in History.

**Architecture:** Extend the existing evidence-first Quick Review boundary rather than creating another reporting engine. First make evidence identity safe when multiple harnesses share a raw session id. Then scan each enabled harness independently with the existing `ScanService`, merge the successful scans, reuse `OutcomeSynthesisService` for work grouping, project the grouped evidence into Daily sections deterministically by activity timestamp, reconcile that fresh projection with a persisted Daily-local draft, and expose the result through a Daily-specific Quick Review / Markdown / History path. General Report Setup, Session Review, and `OutcomeReviewDraft` remain independent.

**Tech Stack:** Python 3.11+, Pydantic 2, Typer, Rich, platformdirs, pytest, Ruff, Pyright, existing `ScanService`, `OutcomeSynthesisService`, `extract_evidence`, `atomic_secure_write`, append-only History JSONL, and the existing interactive state-machine controller.

## Global Constraints

- Spec: `docs/2026-08-13-daily-standup-design.md`.
- Final Markdown always contains `Yesterday`, `Today`, `Blockers` in that order; an empty section renders `- None`.
- Title date and boundaries use `report.timezone`. Derive local calendar midnights; never define “yesterday” as a fixed 24-hour subtraction.
- One union scan covers yesterday local `00:00` through one captured `now`.
- Daily scans every enabled harness automatically and always includes subagents. There is no Daily harness picker.
- Partial harness failure continues with explicit coverage warnings. All enabled harnesses failing is a recoverable source error, not “no activity.”
- Successful scans with zero activity produce an empty Daily Quick Review and still allow manual Add in all sections.
- Reuse the existing outcome-grouping model call. Do not add a second model call to regroup or classify the same work for Daily.
- Cross-harness source identity is `(harness, session_id)`; raw `session_id` alone must never key merged evidence.
- Reconciliation identity is exact `(harness, session_id, activity_id)`, with unambiguous `(harness, session_id)` overlap as the only coarser fallback.
- The LLM never decides Yesterday versus Today. Section assignment uses `SessionActivity.timestamp` and half-open local-day boundaries only.
- Yesterday includes substantive progress, including in-progress work with tangible evidence.
- Today prefers actual Today activity. A Yesterday-derived Today suggestion requires explicit in-progress/unfinished evidence and remains visibly marked as a suggestion during review.
- Blocker candidates require unresolved blocker evidence. A resolved failed command is not a blocker; generic command-failure candidates are never auto-included in v1 and require reviewer confirmation.
- Yesterday and Today initially include at most five primary candidates each. Additional candidates remain under section-specific More candidates; five is not a final-output cap.
- Final bullets are standup-first and list all related repositories, for example `[api, sdk, web]`; final Markdown never exposes harness topology or review provenance labels.
- Review-only provenance includes `Activity today`, `Suggested from yesterday`, `Detected blocker`, `User added`, `New activity`; a global `Fallback draft` indicator is shown when deterministic fallback is active.
- Daily Quick Review reuses `Space`, `e`, `J/K`, `v`, `a`, `p`, `g`, `b`. v1 has no Report type, Detail, Next week, Split, period picker, harness picker, or `--no-review`.
- `p Preview` and `g Generate` consume the same in-memory reviewed draft. Generate never re-runs synthesis or silently rewrites reviewed prose.
- Output path is `<report.output_directory>/daily-standup-YYYY-MM-DD.md`. Same-day Generate intentionally replaces that one file atomically; it does not use the generic report-exists conflict flow.
- Same-day reruns preserve user-added items, reviewer wording, exclusions, and ordering. Fresh evidence may extend a work item but cannot silently overwrite reviewer-owned wording.
- Persist a Daily-local stable work-item id. Never persist `Outcome.id` as the durable Daily identity.
- A new local calendar day never carries the previous day’s Today plan forward merely because it was planned.
- Daily review state lives under Iiwi’s user-data directory, owner-only where supported, stores references/review state rather than full transcripts, and is opportunistically cleaned after 30 days. Cleanup failure is non-fatal.
- Total outcome-synthesis failure automatically falls back to deterministic local evidence and still enters Daily Quick Review.
- History remains backward-compatible with old JSONL entries and represents Daily as `daily_standup`, with successful and unavailable harnesses separate.
- Existing general Report Setup, Session Review, standard Quick Review, History, Settings, and CLI report semantics must remain green.
- No new runtime dependency.

## Planned file boundaries

**New files**

- `src/iiwi/models/daily.py`
- `src/iiwi/services/daily_scan.py`
- `src/iiwi/services/daily_projection.py`
- `src/iiwi/services/daily_reconcile.py`
- `src/iiwi/services/daily_report.py`
- `src/iiwi/services/daily_workflow.py`
- `src/iiwi/daily_state.py`
- `src/iiwi/renderers/daily_markdown.py`
- `src/iiwi/interactive/daily_review.py`
- `docs/daily-standup.md`
- focused unit/integration tests named in each task below.

**Existing boundaries reused rather than replaced**

- `src/iiwi/services/scan.py` stays single-harness.
- `src/iiwi/services/outcomes.py` stays the work-grouping boundary.
- `src/iiwi/security/secure_files.py:atomic_secure_write` stays the atomic/0600 write primitive.
- `src/iiwi/interactive/controller.py` stays the screen state machine; Daily gets dedicated state/handlers rather than overloading `OutcomeReviewDraft`.

---

### Task 1: Make evidence and outcome grouping collision-safe across harnesses

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

**Interfaces**

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

`EvidenceRef` additions are optional/defaulted for backward compatibility. Production `extract_evidence()` always fills `SessionEvidence.harness` from `ResolvedSession.session.harness`.

The model-facing grouping contract becomes:

```python
class _CompactSession(BaseModel):
    source_id: str
    repository_id: str
    # title/branch/goal/outcome unchanged


class _ProposedOutcome(BaseModel):
    # existing fields unchanged
    source_ids: list[str]
```

A source id is collision-safe and opaque:

```python
def _source_id(evidence: SessionEvidence) -> str:
    return json.dumps(
        [evidence.harness, evidence.session_id],
        separators=(",", ":"),
        ensure_ascii=False,
    )
```

No code parses or semantically trusts a source id returned by the model; it is accepted only by exact dictionary lookup.

- [ ] **Step 1: Write failing provenance/backward-compatibility tests**

Add:

```python
def test_extract_evidence_keeps_harness(resolved_session) -> None:
    resolved_session.session.harness = "claude-code"
    assert extract_evidence(resolved_session).harness == "claude-code"


def test_old_evidence_ref_payload_remains_valid() -> None:
    ref = EvidenceRef.model_validate(
        {"session_id": "s1", "repository_id": "repo"}
    )
    assert ref.harness is None
    assert ref.activity_ids == []
```

Update direct `SessionEvidence(...)` fixtures in `tests/unit/services/test_outcomes.py` to include an explicit harness.

- [ ] **Step 2: Run and confirm the new tests fail**

```bash
uv run pytest tests/unit/extraction/test_pipeline.py tests/unit/models/test_outcome.py -q
```

Expected: FAIL because the fields do not exist.

- [ ] **Step 3: Add model fields and extraction provenance**

Populate `harness=resolved.session.harness` in `extract_evidence`. Do not change evidence text/status rules in this step.

- [ ] **Step 4: Write the cross-harness raw-id collision test before refactoring grouping**

Build two resolved sessions with raw `session_id="same-id"`, one OpenCode and one Claude Code. Use a fake `OpenCodeRunner` response containing two distinct `source_ids`. Assert:

```python
assert len(result.outcomes) == 2
assert {ref.harness for o in result.outcomes for ref in o.evidence_refs} == {
    "opencode",
    "claude-code",
}
assert all(ref.activity_ids for o in result.outcomes for ref in o.evidence_refs)
```

Also inspect the transcript sent to the fake runner and assert it contains two distinct `source_id` values despite identical raw session ids.

- [ ] **Step 5: Run and confirm the current raw-id maps fail the collision test**

```bash
uv run pytest tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py -q
```

Expected: FAIL until raw-id-keyed maps and prompt fields are replaced.

- [ ] **Step 6: Refactor every grouping correlation map to opaque source ids**

Rename model payload fields to `source_id` / `source_ids`. Key `evidence_by_source`, `compact_by_source`, `local_texts_by_source`, `started_at`, `sent_by_source`, used-id sets, proposal signatures, and synthesized-id inputs by `_source_id(evidence)`. Update prompt wording/tests so the model echoes only `source_ids` it was given.

Never use `session_id` alone to correlate merged evidence after extraction.

- [ ] **Step 7: Enrich generated evidence refs with source activity ids**

Use a stable union over all evidence items selected for that session:

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

Every `_evidence_refs(evidence)` result gets `harness=evidence.harness` and `activity_ids=_activity_ids(evidence)` while retaining existing commit/file behavior.

- [ ] **Step 8: Verify and commit**

```bash
uv run pytest \
  tests/unit/extraction/test_pipeline.py \
  tests/unit/models/test_outcome.py \
  tests/unit/services/test_outcomes.py \
  tests/unit/summarizers/test_outcome_prompt.py -q
uv run ruff check src/iiwi/models src/iiwi/extraction src/iiwi/services/outcomes.py src/iiwi/summarizers/outcome_prompt.py
uv run pyright
```

Commit:

```bash
git add src/iiwi/models src/iiwi/extraction/pipeline.py src/iiwi/services/outcomes.py \
  src/iiwi/summarizers/outcome_prompt.py tests/unit/extraction tests/unit/models \
  tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py
git commit -m "refactor: make outcome sources harness-safe"
```

---

### Task 2: Add timezone-aware Daily windows and multi-harness scan coordination

**Files:**
- Create: `src/iiwi/services/daily_scan.py`
- Modify: `src/iiwi/errors.py`
- Create: `tests/unit/services/test_daily_scan.py`

**Interfaces**

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


class DailyScanCoordinator:
    def __init__(
        self,
        *,
        window: DailyWindow,
        scanners: Mapping[str, Scanner],
    ) -> None: ...

    def scan(self) -> DailyScanResult: ...
```

The all-source error preserves the exact attempted window so Continue cannot cross midnight and silently change the standup date:

```python
class DailySourceUnavailableError(IiwiError):
    unavailable_harnesses: tuple[str, ...]
    standup_date: date
    since: datetime
    until: datetime
```

- [ ] **Step 1: Write local-midnight tests including DST**

```python
def test_daily_window_uses_calendar_midnights_across_dst() -> None:
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 3, 9, 10, 30, tzinfo=tz)
    window = daily_window(now)
    assert window.yesterday_start == datetime(2026, 3, 8, 0, 0, tzinfo=tz)
    assert window.today_start == datetime(2026, 3, 9, 0, 0, tzinfo=tz)
    assert window.period == DateRange(since=window.yesterday_start, until=now)
```

Also assert naive `now` raises `ValueError("now must be timezone-aware")`.

- [ ] **Step 2: Write coordinator tests for full success, partial failure, all failure, and successful zero activity**

A harness counts as successful when `scan()` returns, even if the scan has zero sessions. Only `HarnessSourceError` marks the harness unavailable.

Pin merged counts/warnings and all-source error context:

```python
with pytest.raises(DailySourceUnavailableError) as caught:
    coordinator.scan()
assert caught.value.unavailable_harnesses == ("opencode", "claude-code")
assert caught.value.standup_date == window.standup_date
assert caught.value.since == window.yesterday_start
assert caught.value.until == window.now
```

- [ ] **Step 3: Run and confirm missing-module failures**

```bash
uv run pytest tests/unit/services/test_daily_scan.py -q
```

- [ ] **Step 4: Implement local-day derivation**

Use local dates, not elapsed-hour subtraction:

```python
today = now.date()
today_start = datetime.combine(today, time.min, tzinfo=now.tzinfo)
yesterday_start = datetime.combine(
    today - timedelta(days=1),
    time.min,
    tzinfo=now.tzinfo,
)
```

- [ ] **Step 5: Implement deterministic scan merging without modifying `ScanService`**

Iterate scanners in insertion order for stable warnings. Catch `HarnessSourceError` per harness. For successful scans, concatenate `resolved_sessions`, sum counts, concatenate warnings, and recompute `sessions_by_repository` with `group_resolved_sessions(merged_sessions)`. The merged `ScanResult.period` is always `window.period`.

If no scanner returns successfully, raise `DailySourceUnavailableError` with all unavailable names and the captured window.

- [ ] **Step 6: Verify existing scan behavior and commit**

```bash
uv run pytest tests/unit/services/test_daily_scan.py tests/integration/test_scan_service.py -q
uv run ruff check src/iiwi/services/daily_scan.py src/iiwi/errors.py tests/unit/services/test_daily_scan.py
uv run pyright
```

Commit:

```bash
git add src/iiwi/services/daily_scan.py src/iiwi/errors.py tests/unit/services/test_daily_scan.py
git commit -m "feat: coordinate daily scans across harnesses"
```

---

### Task 3: Model Daily review state and project grouped evidence into three sections

**Files:**
- Create: `src/iiwi/models/daily.py`
- Modify: `src/iiwi/models/__init__.py`
- Create: `src/iiwi/services/daily_projection.py`
- Create: `tests/unit/models/test_daily.py`
- Create: `tests/unit/services/test_daily_projection.py`

**Interfaces**

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
    warnings: list[str] = Field(default_factory=list)            # review/local warnings
    coverage_warnings: list[str] = Field(default_factory=list)   # final-artifact warnings
    successful_harnesses: list[str] = Field(default_factory=list)
    unavailable_harnesses: list[str] = Field(default_factory=list)
    repository_count: int = 0
    session_count: int = 0
    fallback: bool = False
```

`DailyStandupDraft` owns:

```python
def ordered_items(self, section: DailySection) -> list[tuple[DailyStandupWorkItem, DailySectionItem]]: ...
def toggle_included(self, section: DailySection, work_item_id: str) -> None: ...
def move(self, section: DailySection, work_item_id: str, delta: int) -> None: ...
def edit(self, section: DailySection, work_item_id: str, statement: str) -> None: ...
def add_user_item(self, section: DailySection, statement: str) -> DailyStandupWorkItem: ...
```

Projection entry points:

```python
def project_daily_standup(
    *,
    daily_scan: DailyScanResult,
    outcomes: list[Outcome],
) -> DailyStandupDraft: ...


def build_daily_fallback(*, daily_scan: DailyScanResult) -> DailyStandupDraft: ...
```

- [ ] **Step 1: Write model mutation tests first**

Pin section-local edit/reorder/include behavior and no-evidence user adds:

```python
def test_edit_marks_only_the_target_section_reviewer_owned() -> None:
    draft = sample_daily_draft()
    draft.edit(DailySection.TODAY, "w1", "Finish the renderer")
    assert draft.work_items[0].today.statement == "Finish the renderer"
    assert draft.work_items[0].today.user_edited is True
    assert draft.work_items[0].yesterday.user_edited is False
```

A More item promoted with Space becomes included/PRIMARY. `move()` never crosses sections.

- [ ] **Step 2: Write timestamp-projection tests**

Build one session spanning local midnight with activity `y1` in Yesterday and `t1` in Today. An Outcome whose refs contain both ids must become one Daily-local work item with both projections:

```python
assert work.yesterday.source is DailyStatementSource.ACTIVITY_YESTERDAY
assert work.today.source is DailyStatementSource.ACTIVITY_TODAY
assert work.yesterday.statement == outcome.title
assert work.today.statement == outcome.title
```

The same Daily-local id owns both section items.

- [ ] **Step 3: Write Today-suggestion tests**

A Yesterday-only Outcome creates Today only when:

- `outcome.status is OutcomeStatus.IN_PROGRESS`, and
- the source evidence has a Yesterday-window `EvidenceStatus.IN_PROGRESS` goal/outcome signal.

Then source is `SUGGESTED_FROM_YESTERDAY`. A completed outcome, a plan with no evidence, or an item whose supporting activity has no timestamp produces no Today suggestion.

- [ ] **Step 4: Write blocker tests that distinguish candidates from final blockers**

Normal extraction marks observed command failures `EvidenceStatus.BLOCKED`, so v1 must treat them as review candidates, not truth.

Pin:

- an unresolved failed command associated with an in-progress outcome creates `DETECTED_BLOCKER` but `included is False`;
- a later `COMPLETED` evidence item in the same `(harness, session_id)` removes that blocker candidate;
- a completed grouped outcome does not produce a blocker candidate from an earlier failure;
- completion in a different source session does not resolve it;
- blockers are not capped at five.

This preserves “auto candidates + human confirmation” without shipping ordinary debugging failures by default.

- [ ] **Step 5: Write primary/More selection tests**

Yesterday and Today ranks 0–4 start `PRIMARY` + included; rank 5+ start `MORE` + excluded. Blocker candidate inclusion follows the blocker rule above, not the five-item quota.

- [ ] **Step 6: Run and confirm missing-module failures**

```bash
uv run pytest tests/unit/models/test_daily.py tests/unit/services/test_daily_projection.py -q
```

- [ ] **Step 7: Implement deterministic activity indexing/partitioning**

Build exact activity timestamps once:

```python
activity_times: dict[tuple[str, str, str], datetime] = {}
for resolved in daily_scan.scan.resolved_sessions:
    source = (resolved.session.harness, resolved.session.session_id)
    for activity in resolved.session.activities:
        if activity.timestamp is not None:
            activity_times[(*source, activity.activity_id)] = activity.timestamp
```

Classify only:

```python
window.yesterday_start <= ts < window.today_start
window.today_start <= ts < window.now
```

Never guess timestamp-less activities.

- [ ] **Step 8: Implement projection and fallback without another model call**

Normal section statement starts from the already evidence-gated `Outcome.title`; Daily does not invent a second summary. Repository labels come from all outcome refs. Assign a fresh `uuid4().hex` Daily-local id the first time the item is created; `source_outcome_ids` are diagnostic only.

For deterministic fallback, extract evidence locally per resolved session and choose the best evidence-backed statement in this order: relevant outcome/assistant claim, meaningful goal, redacted session title, repository display name. Reuse the same timestamp and blocker rules. Set `draft.fallback=True`; keep each item’s ordinary source (`ACTIVITY_*`, `SUGGESTED_FROM_YESTERDAY`, `DETECTED_BLOCKER`) so the review can still distinguish actual activity from suggestions. `Fallback draft` is a global review indicator derived from `draft.fallback`, not a section-item source.

Populate `coverage_warnings=list(daily_scan.coverage_warnings)`, normal scan/synthesis warnings in `warnings`, and counts from the merged scan.

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest tests/unit/models/test_daily.py tests/unit/services/test_daily_projection.py -q
uv run ruff check src/iiwi/models/daily.py src/iiwi/services/daily_projection.py tests/unit/models/test_daily.py tests/unit/services/test_daily_projection.py
uv run pyright
```

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

**Interfaces**

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

- [ ] **Step 1: Write state path/round-trip/corruption/permission/retention tests**

Use `IIWI_DAILY_STATE_DIR` for isolation. Pin `YYYY-MM-DD.json`, JSON round trip, 0600 file / 0700 directory on POSIX, and corrupt JSON returning a visible `DailyStateLoadResult(... warning=...)` rather than raising or silently discarding review state.

Cleanup removes only valid date-named files older than 30 days; exactly 30 days old remains. Nonmatching files and cleanup `OSError`s are ignored.

- [ ] **Step 2: Write reconciliation tests for reviewer priority**

Pin:

- reviewer-edited wording survives fresh machine wording;
- excluded stays excluded;
- user-added survives with no evidence;
- prior relative order survives among matched items;
- new activity refs are unioned into the matched item and set `new_activity=True`;
- unmatched fresh work appends as `New activity`;
- previous reviewed items missing from a partial fresh scan remain rather than disappearing.

Example:

```python
merged = reconcile_daily_draft(previous, fresh)
assert merged.work_items[0].today.statement == "My wording"
assert merged.work_items[0].today.user_edited is True
assert merged.work_items[0].today.new_activity is True
```

- [ ] **Step 3: Write exact/coarse/ambiguous/no-overlap identity tests**

Match priority:

1. exact `(harness, session_id, activity_id)` overlap;
2. otherwise exactly one unambiguous `(harness, session_id)` overlap;
3. two possible previous matches is ambiguous: preserve both previous items and add fresh as a new candidate rather than silently merging;
4. no overlap creates a new Daily-local id.

Include identical raw session ids from different harnesses and assert they never match.

- [ ] **Step 4: Run and confirm missing-module failures**

```bash
uv run pytest tests/unit/services/test_daily_reconcile.py tests/unit/test_daily_state.py -q
```

- [ ] **Step 5: Implement evidence-key matching without prose similarity**

Aggregate section refs for each work item. Exact keys:

```python
(ref.harness, ref.session_id, activity_id)
```

Coarse keys:

```python
(ref.harness, ref.session_id)
```

Ignore refs with `harness is None` for cross-harness matching; they may exist only for backward-compatible old payloads. Never match by title or model prose.

Matched fresh items inherit the previous Daily-local `id`. Preserve reviewer statement when `user_edited` or `source is USER_ADDED`, preserve included/excluded, merge evidence refs, and preserve the previous ordering for surviving items.

- [ ] **Step 6: Implement Daily state persistence using the existing secure writer**

Default directory is `Path(user_data_dir("iiwi")) / "daily"`; no legacy migration because this feature is new. Create/chmod directory 0700 on POSIX. Save with:

```python
atomic_secure_write(
    destination,
    draft.model_dump_json(indent=2) + "\n",
    force=True,
)
```

Do not copy/reimplement atomic-write logic.

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest tests/unit/services/test_daily_reconcile.py tests/unit/test_daily_state.py tests/unit/test_state.py -q
uv run ruff check src/iiwi/services/daily_reconcile.py src/iiwi/daily_state.py tests/unit/services/test_daily_reconcile.py tests/unit/test_daily_state.py
uv run pyright
```

Commit:

```bash
git add src/iiwi/services/daily_reconcile.py src/iiwi/daily_state.py \
  tests/unit/services/test_daily_reconcile.py tests/unit/test_daily_state.py
git commit -m "feat: preserve reviewed daily standup state"
```

---

### Task 5: Render exact Daily Markdown and write the same-day file safely

**Files:**
- Create: `src/iiwi/renderers/daily_markdown.py`
- Create: `src/iiwi/services/daily_report.py`
- Create: `tests/unit/renderers/test_daily_markdown.py`
- Create: `tests/unit/services/test_daily_report.py`

**Interfaces**

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
    def preview(self, draft: DailyStandupDraft) -> DailyReportResult: ...
    def generate(self, draft: DailyStandupDraft, *, output_path: Path) -> DailyReportResult: ...
```

Counts come from `DailyStandupDraft.repository_count/session_count`; renderer/report service does not rescan.

- [ ] **Step 1: Write exact Markdown contract tests**

Pin title, artifact-level coverage warning location, fixed section order, repo labels, exclusion, manual items, and empty sections:

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

Only `draft.coverage_warnings` enters final Markdown. `draft.warnings` is review-only. Review labels and `Fallback draft` must not appear in final output.

A user-added item with no repositories renders `- Manual statement`, never `- [] Manual statement`.

- [ ] **Step 2: Write preview/generate parity and same-day overwrite tests**

```python
preview = service.preview(draft)
generated = service.generate(draft, output_path=path)
assert preview.content == generated.content == path.read_text(encoding="utf-8")
```

Pre-create `path` and assert Generate replaces it without `ReportAlreadyExistsError`. Propagate `ReportOutputError` on write failure.

- [ ] **Step 3: Run and confirm missing-module failures**

```bash
uv run pytest tests/unit/renderers/test_daily_markdown.py tests/unit/services/test_daily_report.py -q
```

- [ ] **Step 4: Implement one pure renderer and one write boundary**

Repository prefix:

```python
repositories = sorted(set(work.repository_ids))
prefix = f"[{', '.join(repositories)}] " if repositories else ""
```

Only included items render. `daily_output_path` is:

```python
output_directory / f"daily-standup-{standup_date:%Y-%m-%d}.md"
```

Generate performs exactly one atomic write:

```python
atomic_secure_write(output_path, content, force=True)
```

No synthesis/projection/reconcile/state mutation is allowed in this service.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/unit/renderers/test_daily_markdown.py tests/unit/services/test_daily_report.py tests/unit/security/test_secure_files.py -q
uv run ruff check src/iiwi/renderers/daily_markdown.py src/iiwi/services/daily_report.py tests/unit/renderers/test_daily_markdown.py tests/unit/services/test_daily_report.py
uv run pyright
```

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
- Modify: `tests/unit/test_logging.py`
- Modify: `tests/unit/interactive/test_render.py`
- Modify: `tests/integration/test_cli.py`

**Interfaces**

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

General report call sites keep `harness`, `narrative`, `detail`. Daily uses `kind=DAILY_STANDUP`, no fabricated single harness, successful `harnesses`, unavailable `unavailable_harnesses`, and `narrative/detail=None`.

- [ ] **Step 1: Write backward-compatible old-line and Daily round-trip tests**

Old JSON without new fields reads as:

```python
assert entry.kind is HistoryKind.REPORT
assert entry.effective_harnesses == ("opencode",)
assert entry.unavailable_harnesses == ()
```

Daily round trip pins kind, successful/unavailable harnesses, nullable report-only metadata, and absolute output path.

- [ ] **Step 2: Write failing human/interactive rendering tests**

History table/TUI row must say `Daily Standup`, never fake `multiple`. Existing report rows retain normal harness labels. `history --json` includes normalized `kind`, `harnesses`, `unavailable_harnesses` for both old and new entries.

- [ ] **Step 3: Run and confirm failures**

```bash
uv run pytest tests/unit/test_history.py tests/unit/test_logging.py tests/unit/interactive/test_render.py tests/integration/test_cli.py -q
```

- [ ] **Step 4: Implement tolerant decoding without rewriting previous JSONL**

Normalize missing fields in `read_history()`; preserve corrupt-line containment and current absolute-path handling. Do not migrate old lines on disk.

`effective_harnesses` returns explicit `harnesses`, otherwise `(harness,)` for a legacy/general report with a single harness, otherwise `()`.

- [ ] **Step 5: Update display code and ordinary report constructors**

Branch display on `HistoryKind`. Existing `_record_history`, interactive `_generate`, and `_generate_reviewed` continue writing `REPORT` entries. Only adapt constructor calls for the new optional/default fields; do not change report behavior.

Daily append is wired in Task 8 after a successful file write.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/unit/test_history.py tests/unit/test_logging.py tests/unit/interactive/test_render.py tests/integration/test_cli.py -q
uv run ruff check src/iiwi/history.py src/iiwi/logging.py src/iiwi/interactive/render.py src/iiwi/cli.py src/iiwi/interactive/cli_actions.py
uv run pyright
```

Commit:

```bash
git add src/iiwi/history.py src/iiwi/logging.py src/iiwi/interactive/render.py \
  src/iiwi/cli.py src/iiwi/interactive/cli_actions.py tests/unit/test_history.py \
  tests/unit/test_logging.py tests/unit/interactive/test_render.py tests/integration/test_cli.py
git commit -m "feat: record daily standups in history"
```

---

### Task 7: Add Daily Quick Review rendering and controller interactions

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

**Row/screen interfaces**

```python
@dataclass(frozen=True)
class DailyReviewRow:
    kind: str                      # section | item | more
    section: DailySection
    work_item_id: str | None = None


YESTERDAY_MORE_SECTION = "__daily_yesterday_more__"
TODAY_MORE_SECTION = "__daily_today_more__"


def visible_daily_review_rows(
    draft: DailyStandupDraft,
    expanded: set[str],
) -> list[DailyReviewRow]: ...
```

Add:

```python
Screen.DAILY_REVIEW
Screen.DAILY_RESULT
```

Extend `_State` with Daily draft/cursor/message/evidence expansion/result fields, kept separate from `outcome_review`.

Extend `InteractiveActions` with:

```python
start_daily: Callable[[DailyStandupDraft | None], DailyStandupDraft]
continue_daily_empty: Callable[[DailySourceUnavailableError, DailyStandupDraft | None], DailyStandupDraft]
persist_daily: Callable[[DailyStandupDraft], str | None]
preview_daily: Callable[[DailyStandupDraft], InteractiveReportResult]
generate_daily: Callable[[DailyStandupDraft], InteractiveReportResult]
edit_daily_statement: Callable[[str], str | None]
add_daily_statement: Callable[[DailySection], str | None]
```

`persist_daily` returns `None` on success or a warning string on non-fatal state-write failure.

- [ ] **Step 1: Write row-visibility tests first**

Fixed section order is Yesterday → Today → Blockers. Yesterday/Today More rows are independent disclosures; opening Today More cannot reveal Yesterday More. Blockers are not capped. Empty sections still have a section row so Add has an unambiguous destination.

- [ ] **Step 2: Write rendering tests for labels and viewport safety**

Render a mixed draft and assert review text contains relevant labels:

```text
Activity today
Suggested from yesterday
Detected blocker
User added
New activity
Fallback draft
```

`Fallback draft` appears once from `draft.fallback`, not on every item.

Hints contain only approved Daily keys; no `s Split`, Report type, Detail, or Next week. Narrow-width/short-height regression tests must prove summary rows use no-wrap/ellipsis and the cursor/hints remain visible.

- [ ] **Step 3: Write controller mutation tests**

Pin:

- Space toggles focused item and persists;
- `e` edits focused statement, marks reviewer ownership via model method, then persists;
- `J/K` reorder only inside the current section, then persist;
- `v` toggles evidence UI state only (no persistence required);
- `a` adds to the focused section, including an empty section, then persists;
- `b` returns Main;
- `p` calls `preview_daily`, sets `preview_return_screen=DAILY_REVIEW`, and opens existing `REPORT_PREVIEW` without mutating the draft;
- `g` calls `generate_daily` and opens `DAILY_RESULT`;
- Daily Result offers Main and report path, not generic “Generate another report.”

- [ ] **Step 4: Write all-source/preview/write failure tests**

`DailySourceUnavailableError` becomes recoverable error kind `daily-source`, storing the error object itself on `_ErrorState` so its original `standup_date/since/until` survive:

```text
Retry
Continue with empty draft
Back
```

Retry calls `start_daily(current_daily_review)`. Continue calls `continue_daily_empty(error.daily_source_error, current_daily_review)`. Back returns Main.

Daily preview/write errors return to Daily Review rather than Outcome Review.

- [ ] **Step 5: Run and confirm failures**

```bash
uv run pytest \
  tests/unit/interactive/test_daily_review.py \
  tests/unit/interactive/test_daily_review_render.py \
  tests/unit/interactive/test_daily_review_controller.py \
  tests/unit/interactive/test_daily_review_failures.py -q
```

- [ ] **Step 6: Implement Daily row derivation and viewport-safe renderer**

Keep row derivation in `interactive/daily_review.py`. Reuse render.py’s viewport primitives and block-window approach; do not add bare wrapping `console.print(Text(...))` rows. Evidence view may show repository, harness, session, commit/file refs; final Markdown remains separate.

- [ ] **Step 7: Implement separate Daily handlers without changing Outcome Review**

Add `_begin_daily_review`, `_daily_review_key`, `_generate_daily_review`, `_daily_result_key`. Every reviewer mutation follows:

```python
mutate(state.daily_review)
state.daily_message = actions.persist_daily(state.daily_review)
```

A persistence warning never rolls back in-memory review state.

`_begin_daily_review` catches `DailySourceUnavailableError`; it does not handle `OutcomeSynthesisError` because Task 8’s workflow converts synthesis failure to fallback before returning.

- [ ] **Step 8: Insert Daily in the main menu after Review Activity**

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

Use a one-line description such as `"Draft yesterday, today and blockers"`. Update menu index/dispatch tests so existing options remain correct after insertion.

- [ ] **Step 9: Verify full interactive unit suite and commit**

```bash
uv run pytest tests/unit/interactive -q
uv run ruff check src/iiwi/interactive tests/unit/interactive
uv run pyright
```

Commit:

```bash
git add src/iiwi/interactive tests/unit/interactive
git commit -m "feat: add daily quick review"
```

---

### Task 8: Wire Daily workflow/state/history and expose `iiwi daily`

**Files:**
- Create: `src/iiwi/services/daily_workflow.py`
- Modify: `src/iiwi/interactive/cli_actions.py`
- Modify: `src/iiwi/interactive/controller.py`
- Modify: `src/iiwi/cli.py`
- Create: `tests/unit/services/test_daily_workflow.py`
- Modify: `tests/unit/interactive/test_cli_actions.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/integration/test_interactive_cli.py`

**Workflow interface**

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
    ) -> DailyStandupDraft: ...
```

One refresh does:

1. capture `now` once;
2. derive `DailyWindow`;
3. opportunistically cleanup old Daily state, swallowing cleanup-only failures;
4. use supplied in-memory previous draft, otherwise load only this standup date’s state;
5. scan all enabled harnesses;
6. try `OutcomeSynthesisService.synthesize(merged_scan)` exactly once when there is activity;
7. on `OutcomeSynthesisError`, call deterministic `build_daily_fallback`;
8. on normal synthesis, call `project_daily_standup`;
9. append state-load warning to `draft.warnings`, never `coverage_warnings`;
10. reconcile fresh with previous and return the draft.

`DailySourceUnavailableError` is not swallowed; the controller needs it for Retry / Continue / Back.

- [ ] **Step 1: Write workflow tests for one clock read, normal synthesis, fallback, no activity, and state reconcile**

Pin `now_factory` called once. Normal path calls outcome synthesis once. Zero-activity successful scan bypasses model synthesis and returns an empty normal draft. `OutcomeSynthesisError` returns `fallback=True` rather than escaping. A prior reviewer edit survives reconcile.

Advance `now_factory` to the next local date and assert the service loads only the new date state file; yesterday’s Today plan is not imported.

- [ ] **Step 2: Write cli-action wiring tests proving all enabled harnesses use the same window**

Monkeypatch `_enabled_harnesses` to OpenCode, Claude Code, Codex and `_build_scan_service` to record arguments. All calls must use the same `window.period` and `root_only=False`.

OpenCode sanitize uses its configured default; Claude/Codex remain unsanitized because they do not expose the OpenCode export option.

- [ ] **Step 3: Write `iiwi daily` CLI tests before implementation**

```python
result = runner.invoke(app, ["daily", "--help"])
assert result.exit_code == 0
assert "standup" in result.output.casefold()
```

Pin non-TTY refusal. In a forced-terminal test monkeypatch `run_interactive` and assert:

```python
captured["initial_screen"] is Screen.DAILY_REVIEW
```

Help must not expose `--harness`, `--period`, `--days`, or `--no-review`.

- [ ] **Step 4: Run and confirm failures**

```bash
uv run pytest \
  tests/unit/services/test_daily_workflow.py \
  tests/unit/interactive/test_cli_actions.py \
  tests/unit/test_cli.py \
  tests/integration/test_interactive_cli.py -q
```

- [ ] **Step 5: Implement the workflow below the controller**

Keep fallback/reconcile/state-loading here so UI actions remain thin. `warnings` and `coverage_warnings` stay separate. Let `DailySourceUnavailableError` propagate with its original captured window.

- [ ] **Step 6: Wire Daily actions**

`build_interactive_actions()` adds the seven Task 7 callbacks.

`_persist_daily` catches state-write `OSError` / expected Iiwi write errors and returns a concise review warning; it never prints under the TUI.

`_preview_daily` calls `DailyReportService.preview` only.

`_generate_daily` sequence is strict:

1. resolve `daily_output_path(settings.report.output_directory, draft.standup_date)`;
2. write through `DailyReportService.generate`;
3. save latest Daily draft state;
4. append one `HistoryKind.DAILY_STANDUP` entry with `draft.successful_harnesses` and `draft.unavailable_harnesses`;
5. suppress/history-report bookkeeping failure exactly as the existing interactive report flow does;
6. return `InteractiveReportResult`.

No rescan/synthesis happens in preview or generate.

- [ ] **Step 7: Implement Continue with empty draft from the original source-error window**

`continue_daily_empty(error, previous)` constructs the empty fresh draft using exactly:

```python
standup_date=error.standup_date
scan_since=error.since
scan_until=error.until
successful_harnesses=[]
unavailable_harnesses=list(error.unavailable_harnesses)
coverage_warnings=[all_sources_unavailable_warning]
```

Then load/reuse same-day previous review state and call `reconcile_daily_draft(previous, empty_fresh)`. This preserves manual/reviewer-owned work even when all sources are temporarily unavailable and prevents a midnight crossing from changing the date.

- [ ] **Step 8: Add direct-start support to `run_interactive` and the Typer command**

```python
def run_interactive(
    *,
    actions: InteractiveActions,
    input_source: KeySource,
    console: Console,
    initial_screen: Screen = Screen.MAIN,
) -> None:
    state = _State(screen=initial_screen)
    if initial_screen is Screen.DAILY_REVIEW:
        _begin_daily_review(state, actions)
    ...
```

Add:

```python
@app.command()
def daily() -> None:
    """Draft yesterday, today and blockers from all enabled coding agents."""
    reporter = ConsoleReporter()
    try:
        _require_a_terminal(
            "daily needs a terminal; run `iiwi daily` from an interactive terminal"
        )
        run_interactive(
            actions=build_interactive_actions(),
            input_source=TerminalInput(),
            console=reporter.console,
            initial_screen=Screen.DAILY_REVIEW,
        )
    except ConfigurationError as exc:
        _handle_expected_error(exc, code=3)
```

Keep `iiwi` with no subcommand starting at Main.

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest \
  tests/unit/services/test_daily_workflow.py \
  tests/unit/interactive/test_cli_actions.py \
  tests/unit/test_cli.py \
  tests/integration/test_interactive_cli.py -q
uv run ruff check src/iiwi/services/daily_workflow.py src/iiwi/interactive/cli_actions.py src/iiwi/interactive/controller.py src/iiwi/cli.py
uv run pyright
```

Commit:

```bash
git add src/iiwi/services/daily_workflow.py src/iiwi/interactive/cli_actions.py \
  src/iiwi/interactive/controller.py src/iiwi/cli.py tests/unit/services/test_daily_workflow.py \
  tests/unit/interactive/test_cli_actions.py tests/unit/test_cli.py \
  tests/integration/test_interactive_cli.py
git commit -m "feat: wire the daily standup workflow"
```

---

### Task 9: Prove the end-to-end contract and document Daily Standup

**Files:**
- Create: `tests/integration/test_daily_standup.py`
- Create: `docs/daily-standup.md`
- Modify: `README.md`
- Modify: `README.zh-TW.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/evidence-first-quick-review.md`
- Modify: `tests/unit/test_documentation.py`
- Modify: `tests/unit/test_interactive_documentation.py`

- [ ] **Step 1: Build integration fixtures for two days, three harnesses, and raw-id collision**

Use temp output/history/state locations and injected `Asia/Taipei` clock. Fixtures include:

- OpenCode session `same-id` with Yesterday activity;
- Claude Code session `same-id` with Today activity;
- Codex session with unresolved failed-command blocker candidate;
- cross-repository work that the grouping fake returns as one outcome;
- one resolved failure followed by completion.

- [ ] **Step 2: Test the first run end to end**

Assert:

- both same raw ids survive because harness disambiguates them;
- timestamps alone decide Yesterday/Today;
- cross-repo final bullet lists every repository;
- actual Today/source labels appear only in review;
- unresolved failure appears as an unselected blocker candidate, resolved failure does not;
- all final sections render in fixed order;
- Preview bytes equal generated file bytes;
- filename is `daily-standup-2026-08-13.md`.

- [ ] **Step 3: Test same-day refresh and overwrite**

After first review, edit Today wording, exclude Yesterday, add manual Blocker, reorder, and persist. Add new Today activity to the fake source and refresh on the same local date.

Assert all reviewer decisions survive, new evidence is attached, fresh work carries `new_activity=True`, and Generate replaces the same output path safely.

- [ ] **Step 4: Test zero/partial/all source failure, synthesis fallback, and next-day behavior**

Pin:

- partial harness failure -> normal review + final coverage warning below title;
- all harnesses fail -> `DailySourceUnavailableError`; Continue uses the original error window and allows empty/manual review with final coverage warning;
- all harnesses succeed with zero sessions -> empty normal review;
- outcome synthesis failure -> `fallback=True` Daily review, no fatal error, no speculative Today plan;
- next local day loads only its own state; prior Today plan is not copied.

- [ ] **Step 5: Test Daily History entry**

After Generate:

```python
assert entry.kind is HistoryKind.DAILY_STANDUP
assert entry.harnesses == ("opencode", "claude-code", "codex")
assert entry.unavailable_harnesses == ()
assert entry.output_path.is_absolute()
```

Partial failure records contributors and unavailable sources separately.

- [ ] **Step 6: Run acceptance tests**

```bash
uv run pytest tests/integration/test_daily_standup.py -q
```

Fix contract failures in the owning Task 1–8 module; do not patch around them in integration fixtures or CLI glue.

- [ ] **Step 7: Add failing documentation assertions first**

Require `iiwi daily` in `README.md`, `README.zh-TW.md`, `docs/cli-reference.md`, and a linked `docs/daily-standup.md`. Require `docs/evidence-first-quick-review.md` to keep the normal Quick Review “in-memory only” statement while naming Daily Standup as the explicit same-day persistent exception.

```bash
uv run pytest tests/unit/test_documentation.py tests/unit/test_interactive_documentation.py -q
```

Expected: FAIL until docs are updated.

- [ ] **Step 8: Write concise user-facing docs from the approved contract**

`docs/daily-standup.md` covers:

```text
iiwi daily
→ all enabled harnesses
→ Yesterday / Today / Blockers
→ Quick Review
→ Preview
→ Generate daily-standup-YYYY-MM-DD.md
```

Explain actual Today vs suggested Today, partial-source warnings, manual Add, same-day reviewed-state reconciliation, fixed `- None`, and 30-day local review-state retention. Do not expose opaque source-id encoding or internal model class names.

- [ ] **Step 9: Run complete verification**

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

Then re-run critical Daily acceptance tests:

```bash
uv run pytest \
  tests/integration/test_daily_standup.py \
  tests/unit/services/test_daily_scan.py \
  tests/unit/services/test_daily_projection.py \
  tests/unit/services/test_daily_reconcile.py \
  tests/unit/interactive/test_daily_review_controller.py \
  tests/unit/interactive/test_daily_review_failures.py -q
```

- [ ] **Step 10: Commit integration coverage/docs**

```bash
git add tests/integration/test_daily_standup.py docs/daily-standup.md README.md README.zh-TW.md \
  docs/cli-reference.md docs/evidence-first-quick-review.md tests/unit/test_documentation.py \
  tests/unit/test_interactive_documentation.py
git commit -m "docs: document the daily standup workflow"
```

---

## Final implementation review checklist

Before opening a PR or claiming completion, verify each item against the design spec:

- [ ] Main → Daily Standup and `iiwi daily` enter the same Daily review flow.
- [ ] No Daily period/harness picker, Report type, Detail, Next week, Split, or `--no-review` exists.
- [ ] One timezone-aware window covers yesterday local midnight through one captured `now`.
- [ ] Every enabled harness is attempted and subagents are included.
- [ ] Merged evidence never keys by raw `session_id` alone.
- [ ] Yesterday/Today assignment is deterministic by activity timestamp.
- [ ] Yesterday/Today expose five initial primary candidates with section-specific More candidates retained.
- [ ] Suggested Today requires explicit unfinished/in-progress evidence and is visibly marked in review.
- [ ] Generic unresolved command failures are blocker candidates but are not auto-included; later completion removes resolved candidates.
- [ ] User-added items require no evidence and are never auto-rewritten.
- [ ] Same-day refresh preserves reviewer edit/exclude/order/manual decisions and can attach new evidence.
- [ ] Ambiguous evidence overlap never silently merges reviewed work items.
- [ ] New calendar date never carries the previous day’s Today plan merely because it was planned.
- [ ] No-activity path remains a usable empty review.
- [ ] Partial source failure continues with an artifact-level coverage warning.
- [ ] All-source failure offers Retry / Continue with empty draft / Back and Continue uses the original attempted window.
- [ ] Outcome synthesis failure uses deterministic Daily fallback, not the general session-based-report fallback.
- [ ] Preview and Generate render byte-identical Markdown from the same reviewed draft.
- [ ] Same-day Generate atomically replaces only that date’s Daily output.
- [ ] Daily state is owner-only where supported, contains references/review state rather than transcripts, and opportunistically cleans files older than 30 days.
- [ ] History labels the artifact Daily Standup, separates successful/unavailable harnesses, and still reads old JSONL fixtures.
- [ ] Existing Report Setup, Session Review, Outcome Quick Review, History, Settings, and CLI report tests remain green.
- [ ] `uv run pytest`, `uv run ruff check .`, and `uv run pyright` all pass immediately before handoff.
