# Daily Standup Design

Date: 2026-08-13
Status: Approved design

## Goal

Add a high-frequency Daily Standup workflow that turns all enabled coding-agent activity from yesterday and today into one short, evidence-backed standup update.

The workflow optimizes for a daily human review loop rather than a configurable report. It should be fast enough to use every day, preserve reviewer decisions across repeated runs on the same day, and never present inferred plans or incomplete source coverage as facts.

## Product contract

Daily Standup always produces three sections:

```markdown
# Daily Standup — YYYY-MM-DD

## Yesterday
- ...

## Today
- ...

## Blockers
- ...
```

All three sections are always present. An empty section renders `- None`.

The title date is the publication date in the configured report timezone.

Daily Standup has no date-range picker and no harness picker. It automatically scans all enabled harnesses over one union window:

- Yesterday: previous local calendar day `00:00` up to today `00:00`.
- Today: today `00:00` up to generation time.
- Scan window: yesterday `00:00` through generation time.

Calendar boundaries are timezone-aware and use `report.timezone`; they must not be implemented as a fixed 24-hour subtraction.

## Entry points

Interactive main menu:

```text
Review Activity
Daily Standup
Generate Report
History
Check Setup
Settings
```

`Daily Standup` is a direct shortcut. It skips normal Report Setup and Session Review.

CLI:

```text
iiwi daily
```

`iiwi daily` enters the same Daily Quick Review flow as the interactive main-menu action.

Version one deliberately has no `--no-review`. Today suggestions and blocker candidates require human confirmation before they become a generated artifact.

## Architecture

Daily Standup extends the existing evidence-first Quick Review architecture rather than creating a parallel reporting engine.

```text
All enabled harnesses
        ↓
DailyScanCoordinator
        ↓
one union window: yesterday 00:00 → now
        ↓
existing evidence extraction
        ↓
existing Outcome grouping logic
        ↓
activity-timestamp section projection
        ↓
DailyStandupDraft
 ├─ Yesterday[]
 ├─ Today[]
 └─ Blockers[]
        ↓
reconcile persisted daily state
        ↓
Daily Quick Review
        ↓
Preview / Generate
```

### Reuse the existing Outcome grouping boundary

The current `OutcomeSynthesisService` already groups sessions into evidence-backed outcomes and reconstructs claims from local evidence. Daily Standup should reuse that grouping logic instead of asking another model to regroup the same work.

Daily-specific synthesis is a projection layer over grouped outcomes and evidence:

1. Determine which source activities fall into Yesterday or Today by timestamp.
2. Produce section-specific standup statements for the same underlying work item.
3. Derive blocker candidates only from unresolved evidence.

The same underlying work may appear in both Yesterday and Today with different wording:

- Yesterday describes progress that already occurred.
- Today describes current activity or a reviewer-confirmable suggested next step.

### DailyScanCoordinator

Do not make the existing single-harness `ScanService` itself multi-harness.

Add a Daily-specific coordinator that runs the existing `ScanService` independently for every enabled harness, then merges successful results for downstream grouping.

Responsibilities:

- Resolve all enabled harnesses.
- Run the same union period against each harness.
- Preserve per-harness warnings.
- Continue on partial harness failure.
- Distinguish no activity from total source failure.
- Produce one merged set of resolved sessions for grouping.

Harness identity remains evidence provenance, not work-item identity.

## Cross-harness source identity

The current outcome pipeline keys several internal maps only by `session_id`. That is safe in the existing single-harness flow, but Daily merges multiple harnesses and must not assume their raw session ids are globally unique.

Daily grouping therefore requires a collision-safe source identity:

```text
SourceSessionKey = (harness, session_id)
```

Any internal identifier sent through the grouping model may use an opaque composite representation of that pair, but the model must not be allowed to erase or redefine the pair.

The raw `session_id` alone must never be the key for merged cross-harness evidence.

This should be implemented as a backward-compatible extension/refactor of the existing grouping boundary, not as a second Daily-only grouping model.

## Cross-repository and cross-harness grouping

One standup work item may combine evidence from multiple repositories and multiple harnesses when evidence supports one shared work objective.

Repository equality alone is not sufficient reason to merge work. Harness equality or difference must not affect grouping identity.

Final standup bullets list all repositories involved, for example:

```markdown
- [api, sdk, web] Finished the authentication migration.
```

The final artifact does not expose harness names.

## Evidence and timestamp projection

Current evidence items carry `source_activity_ids`; activity timestamps live on `SessionActivity`.

Daily section assignment is deterministic:

```text
EvidenceItem.source_activity_ids
        ↓
SessionActivity.timestamp
        ↓
Yesterday | Today
```

The LLM must never decide which date an activity belongs to.

Timestamp-less activities remain governed by existing scan behavior and warnings; they must not be guessed into Yesterday or Today.

### EvidenceRef extension

Persistent Daily reconciliation needs finer provenance than a session id alone because one session may span midnight, may receive new activity later in the same day, and may collide with a raw session id from another harness.

Extend `EvidenceRef` backward-compatibly with:

```python
harness: str | None = None
activity_ids: list[str] = Field(default_factory=list)
```

Existing general-report data without these fields remains valid.

For Daily-generated evidence refs, `harness` is required by the Daily service contract even if the shared model remains optional for backward compatibility.

The durable evidence identity for reconciliation is therefore based on:

```text
(harness, session_id, activity_id)
```

with `(harness, session_id)` available as a coarser session-level anchor.

## Daily domain model

Daily Quick Review should not overload the existing `OutcomeReviewDraft`, whose responsibilities are general reports, report type/detail, blockers, and next-week text.

Introduce an independent `DailyStandupDraft` that reuses Outcome/Evidence concepts but owns Daily-specific state.

Conceptual shape:

```text
DailyStandupDraft
├─ standup_date
├─ scan_since
├─ scan_until
├─ work_items[]
├─ warnings[]
├─ harness_status[]
└─ reconciliation metadata

DailyStandupWorkItem
├─ id                         # persisted Daily identity
├─ source_outcome_ids[]       # diagnostic, not the durable identity
├─ repository_ids[]
├─ yesterday?
│  ├─ statement
│  ├─ evidence_refs[]
│  ├─ included
│  ├─ rank
│  ├─ user_edited
│  └─ origin
├─ today?
│  ├─ statement
│  ├─ source: activity_today | suggested_from_yesterday | user_added
│  ├─ evidence_refs[]
│  ├─ included
│  ├─ rank
│  └─ user_edited
└─ blocker?
   ├─ statement
   ├─ evidence_refs[]
   ├─ included
   ├─ rank
   ├─ confidence
   └─ user_edited
```

A section projection is independently selectable. A reviewer can keep Yesterday and remove Today for the same underlying work item.

Manual edits change the standup statement, not evidence identity.

### Durable work-item identity

Do not rely on `Outcome.id` as the persisted Daily work-item identity. Existing synthesized outcome ids include model-derived title/session/discriminator inputs and may change when a later scan adds sessions or reorders proposals.

The first time a Daily work item is created, assign it a Daily-local stable id and persist it.

On same-day reconciliation, match newly grouped outcomes back to existing Daily work items by evidence overlap:

1. Prefer overlap in exact `(harness, session_id, activity_id)` evidence refs.
2. Fall back to unambiguous overlap in `(harness, session_id)` when activity-level refs are unavailable.
3. If more than one prior work item could match, do not silently merge them; surface the new result as a candidate requiring review.
4. If no prior evidence overlaps, create a new Daily work item and mark it `New activity`.

When a new grouped outcome matches an existing Daily work item, it inherits the persisted Daily work-item id. The id is never recomputed from model prose.

This lets new evidence extend an existing work item without losing reviewer-owned wording, include/exclude decisions, or ordering.

## Section semantics

### Yesterday

Yesterday includes substantive progress, not only completed work.

Eligible statements describe work that occurred during the Yesterday window. In-progress work is valid when the evidence shows tangible progress.

Do not turn a plan or intention into Yesterday progress.

### Today

Today uses this priority:

1. Actual activity observed in today's window.
2. Explicit unfinished work or next step supported by Yesterday evidence.
3. Nothing, when evidence is insufficient.

A Today statement derived from today's actual activity is factual current work and is labeled `Activity today` in review.

A Today statement inferred from Yesterday is a draft suggestion, labeled `Suggested from yesterday` until a reviewer confirms it.

Inferred Today text must never be invented without a supported unfinished-work or next-step signal.

### Blockers

Blockers are unresolved conditions that impede future work.

Already resolved failures, ordinary debugging errors, transient command failures, and completed fixes are not blockers.

Blocker candidates are automatically proposed, but require human review. Deterministic fallback may include a blocker only when unresolved blocker evidence is explicit.

## Subagents

Always include subagent activity.

Subagent activity aggregates into the same parent work objective when evidence indicates it belongs there. Daily output reports outcomes, not agent topology.

Subagent provenance may appear in Evidence view, but final standup text must not say that a subagent performed the work merely because of session hierarchy.

## Candidate selection and ordering

Yesterday and Today each preselect at most five candidates.

Additional candidates remain under a section-specific `More candidates` disclosure and are not lost.

This is an initial-selection limit, not a hard output cap; reviewers may include more items.

Order by standup importance rather than chronology or repository:

1. Explicit outcome or milestone.
2. Higher-impact substantive progress.
3. In-progress work with tangible progress.
4. Small fixes or maintenance.
5. Low-signal activity.

When the same work appears in Yesterday and Today, keep similar relative placement when practical so the progression is easy to scan.

Blockers are not subject to the five-item quota.

## Daily Quick Review

The Daily review reuses the existing Quick Review keyboard language where the semantics match.

Conceptual layout:

```text
Daily Standup — Aug 13
════════════════════════════════════════

Yesterday                                      4 selected
▶ ● [iiwi] Added Daily Standup architecture
  ● [api, web] Fixed authentication flow
  ▸ More candidates (2)

Today                                          3 selected
  ● [iiwi] Implement Daily Standup draft model
      Activity today
  ● [iiwi] Add reconciliation tests
      Suggested from yesterday
  ▸ More candidates (1)

Blockers                                       1 selected
  ● [infra] Waiting for staging access
      Detected blocker

↑↓ jk │ Space Include │ e Edit │ J/K Reorder │ v Evidence
a Add │ p Preview │ g Generate │ ? Help │ b Back
```

### Review provenance labels

The review may show:

- `Activity today`
- `Suggested from yesterday`
- `Detected blocker`
- `User added`
- `New activity`
- `Fallback draft`

These labels are review-only. They do not appear in final Markdown.

### Actions

Reuse:

- `Space`: include/exclude focused statement.
- `e`: edit focused statement.
- `J/K`: reorder within the current section.
- `v`: expand/collapse evidence.
- `a`: add a manual statement to the current section.
- `p`: preview exact final artifact.
- `g`: generate exact reviewed artifact.
- `b`: return without discarding the current in-memory draft.

Daily does not need Report type, Detail, Next week, or a separate period/harness setup.

Version one also omits Daily `Split`. A bad grouping can be excluded and replaced with a user-added statement; a dedicated Daily split interaction can be introduced later if real usage justifies it.

### Editing

Daily edits operate on one field: the standup statement.

Do not expose internal confidence, source labels, evidence identity, or hidden grouping state in the editor.

Editing a synthesized statement sets its reviewer-owned wording state. Reconciliation must never silently replace reviewer-owned wording.

### Manual Add

Allow `Add` in Yesterday, Today, and Blockers.

A user-added item:

- requires no evidence;
- is labeled `User added` in review;
- is editable, reorderable, and excludable;
- is preserved during same-day reconciliation;
- is never auto-rewritten by synthesis;
- has no technical label in final Markdown.

### Empty sections

An empty section is not a selectable fake item. Quick Review may show `No items` and the Add affordance.

Final Markdown always renders:

```markdown
## Section
- None
```

## Preview and generation

Preview is the final artifact renderer, not another synthesis step.

`p Preview` must render exactly the text that `g Generate` would write for the same in-memory reviewed draft.

Returning from Preview preserves all edits, include/exclude choices, ordering, and manual items.

`g Generate` must not re-run synthesis or rewrite reviewed content. It only writes the artifact and appends history.

Output path for a standup day is fixed:

```text
reports/daily-standup-YYYY-MM-DD.md
```

Repeated generation on the same local standup date updates the same file rather than raising the normal generic report-exists conflict.

Use safe replacement semantics so a failed write cannot leave a partially written standup.

## Persistent same-day state

Daily Standup is intentionally different from general Quick Review: its reviewed draft survives repeated runs during the same day.

Default conceptual location:

```text
<iiwi user data>/daily/YYYY-MM-DD.json
```

Use platform-aware Iiwi data paths rather than hard-coding one operating system's home directory.

State stores structured review state, not full transcripts:

- Daily work-item identity;
- section statements;
- source outcome ids for diagnostics;
- collision-safe evidence references;
- include/exclude state;
- section order;
- reviewer-edited flags;
- user-added items;
- latest scan/generation timestamp;
- reconciliation metadata;
- warnings/source coverage needed to reproduce the current draft.

Create state directories owner-only and state files owner-only where the platform supports permissions.

### Retention

Keep Daily structured state for 30 calendar days.

Perform opportunistic cleanup during Daily execution; no daemon or scheduled background process is required.

Cleanup failure is non-fatal and must not block the current standup.

Generated Markdown is not tied to state retention and is not automatically deleted.

## Same-day reconciliation

Repeated `iiwi daily` runs on the same local date load the existing reviewed draft and reconcile newly observed evidence.

Priority is:

```text
explicit reviewer decision
    > previous reviewed state
    > new synthesis
```

Rules:

- Preserve all user-added items.
- Preserve reviewer-edited wording.
- Preserve reviewer exclusions; a new scan does not silently reselect an excluded statement.
- Preserve reviewer ordering where surviving items can be matched.
- Add new evidence to an existing work item without rewriting reviewer-owned wording.
- Surface genuinely new work as `New activity` candidates.
- A retry or new synthesis may improve untouched machine-owned candidates, but must never overwrite reviewed text silently.
- If new evidence demonstrates completion, internal state may change, but reviewer-owned wording remains authoritative until the reviewer edits or accepts a replacement.
- Ambiguous reconciliation never silently merges two reviewer-owned work items.

## Cross-day behavior

Do not copy the previous day's Today plan into the next day's standup.

Each new standup date starts from actual activity in the new union window. Yesterday content comes from actual previous-day activity; Today is then re-derived from current activity or supported unfinished-work evidence.

A prior day's plan is not evidence that the work happened.

## Failure semantics

### No activity

No activity is a valid standup state, not an error.

Enter the normal three-section Quick Review with no candidates and allow manual Add in all sections.

### Partial harness failure

If at least one enabled harness succeeds, continue with available evidence.

Quick Review must clearly warn that the draft is incomplete and name unavailable harnesses.

The final Markdown also retains a concise warning because missing source coverage materially affects the artifact's completeness.

Place coverage warnings directly below the title so they are not easily missed.

Example:

```markdown
# Daily Standup — 2026-08-13

> Warning: OpenCode activity could not be loaded.

## Yesterday
...
```

### All harnesses fail

If every enabled harness fails, do not present the condition as `no activity`.

Show a recoverable error with:

- Retry
- Continue with empty draft
- Back

Continuing with an empty draft preserves a visible coverage warning in Quick Review and final Markdown.

### Synthesis failure

A total synthesis failure automatically produces a deterministic fallback draft and still enters the same Daily Quick Review.

Fallback rules:

- Yesterday: construct readable progress candidates from extracted deterministic evidence/outcomes.
- Today: include only actual Today activity or an explicit unfinished-work/next-step signal; do not speculate.
- Blockers: include only deterministic unresolved blocker evidence.
- Mark the review as `Fallback draft`; hide that technical marker from final Markdown.

A later retry may replace untouched fallback candidates with normal synthesis, but must not silently overwrite manual edits.

## History integration

Daily Standup is a first-class artifact kind, not a fake single-harness report.

Evolve History in a backward-compatible way, conceptually:

```text
HistoryEntry
├─ kind: report | daily_standup
├─ generated_at
├─ harnesses[]                 # successful source coverage
├─ unavailable_harnesses[]     # attempted but failed
├─ since
├─ until
├─ output_path
├─ repository_count
├─ session_count
└─ report-specific metadata when applicable
```

Old JSONL entries containing a single `harness` continue to load as:

```text
kind = report
harnesses = [harness]
unavailable_harnesses = []
```

New Daily entries record successful contributors separately from unavailable harnesses. If the reviewer explicitly continues after all sources fail, `harnesses` is empty and `unavailable_harnesses` contains all attempted enabled harnesses.

History UI identifies the artifact as `Daily Standup` rather than displaying a fabricated `multiple` harness.

Existing report-only fields such as narrative/detail remain compatible for normal report entries and must not force Daily to pretend it has those settings.

The existing absolute output-path behavior remains in force.

## Final rendering contract

Normal artifact:

```markdown
# Daily Standup — 2026-08-13

## Yesterday
- [iiwi] Designed the Daily Standup architecture.
- [api, web] Fixed the authentication flow.

## Today
- [iiwi] Implement the Daily Standup draft and reconciliation flow.

## Blockers
- None
```

Rendering rules:

- Always show Yesterday, Today, Blockers in that order.
- Use all associated repository labels for multi-repository work.
- Hide harness topology and review provenance labels.
- Hide evidence references from the shareable standup.
- Do not append unconfirmed suggestions outside selected reviewed statements.
- Preserve reviewer wording exactly apart from Markdown escaping/formatting required for a valid artifact.

## Non-goals for version one

- No arbitrary Daily date-range selection.
- No harness picker.
- No `--no-review` unattended generation.
- No automatic carry-over of prior Today plans.
- No separate Daily Report type or Detail setting.
- No Daily manual merge UI.
- No Daily split UI.
- No background cleanup daemon.
- No full transcript persistence in Daily state.
- No LLM-based date classification.

## Acceptance criteria

The first version is complete when all of the following are true:

1. Interactive `Daily Standup` and `iiwi daily` enter the same workflow.
2. The workflow automatically uses Yesterday + Today and presents no period picker.
3. Date boundaries are calculated in `report.timezone` using local calendar boundaries.
4. One union window from yesterday `00:00` through now supplies the Daily workflow.
5. Every enabled harness is scanned automatically.
6. Merged source identity is collision-safe across harnesses; raw `session_id` alone is never treated as globally unique.
7. Partial harness failures continue with explicit warnings; total source failure enters recoverable error.
8. Genuine no-activity periods enter an empty but usable Quick Review.
9. Existing Iiwi-authored synthesis sessions remain excluded through the current scan filtering boundary.
10. Existing evidence extraction and Outcome grouping logic are reused; Daily does not introduce a second grouping model pass.
11. Evidence is projected into Yesterday/Today deterministically by source activity timestamp.
12. One work item can span repositories, harnesses, Yesterday, and Today when evidence supports that identity.
13. Persisted Daily work-item identity survives same-day model title/proposal changes by reconciling on evidence identity rather than `Outcome.id`.
14. Yesterday includes substantive progress, including tangible in-progress work.
15. Today prefers actual Today activity, then supported unfinished-work/next-step suggestions, and otherwise invents nothing.
16. Suggested Today items are visibly distinguished during review.
17. Blockers require unresolved blocker evidence.
18. Yesterday and Today each preselect at most five candidates, with extra candidates available under More candidates.
19. All three sections support manual Add.
20. Daily Quick Review supports include/exclude, statement edit, within-section reorder, Evidence, Add, Preview, Generate, Help, and Back.
21. Preview renders the exact artifact Generate will write without another synthesis call.
22. Generate writes `reports/daily-standup-YYYY-MM-DD.md` and updates that same file on later same-day generations.
23. Same-day reruns restore structured Daily state and reconcile new evidence while preserving reviewer edits, additions, exclusions, and ordering.
24. Ambiguous reconciliation never silently combines reviewer-owned items.
25. The next local calendar day does not automatically carry forward the previous day's Today plan.
26. Daily state is owner-private where supported and stores references/state rather than copied transcripts.
27. Daily state older than 30 days is cleaned opportunistically without blocking Daily execution on cleanup failure.
28. Total synthesis failure still provides a deterministic fallback draft for review.
29. The generated Markdown always contains Yesterday, Today, and Blockers, using `- None` for empty sections.
30. Partial or empty-source continuation warnings remain visible in the final Markdown.
31. History records Daily Standup as its own artifact kind, distinguishes successful and unavailable harness coverage, and continues to read legacy single-harness entries.
32. General Generate Report and its existing Quick Review behavior remain unchanged except for backward-compatible shared model/history extensions required by Daily.

## Testing strategy

Tests should protect both the new Daily behavior and the existing general report behavior.

### Domain/unit tests

- Calendar-boundary calculation, including a DST-observing timezone.
- Cross-harness session-id collision handling.
- Legacy `EvidenceRef` payloads without harness/activity ids remain valid.
- Evidence activity-id to Yesterday/Today projection.
- One outcome projecting into both Yesterday and Today.
- Today actual-activity priority over Yesterday suggestion.
- No speculative Today candidate without evidence.
- Unresolved versus resolved blocker classification.
- Primary-five versus More candidates independently for Yesterday and Today.
- Cross-repository label preservation.
- User-added item behavior.
- Reviewer edit/exclusion/order preservation during reconciliation.
- Reconciliation when the new grouped outcome contains old evidence plus new evidence.
- Ambiguous evidence overlap does not silently merge items.
- New-activity detection on a later same-day scan.
- No cross-day Today carry-over.
- Persistent-state serialization round trip.
- Thirty-day cleanup and non-fatal cleanup errors.
- Legacy history JSONL remains readable after the History model extension.

### Coordinator/service tests

- All enabled harnesses succeed and merge.
- One harness fails and other harnesses continue with warnings.
- All harnesses fail and trigger recoverable error semantics.
- All harnesses succeed with zero activity and produce an empty draft.
- Existing self-authored Iiwi session filtering remains effective.
- Outcome grouping runs over the merged Daily evidence set rather than once per section.
- Cross-harness source keys round-trip through grouping without losing original harness/session provenance.
- Synthesis failure enters deterministic fallback.

### Interactive/rendering tests

- Main menu contains Daily Standup in the approved position.
- `iiwi daily` and main-menu Daily produce equivalent draft flow.
- Fixed section rendering and viewport behavior on narrow/short terminals.
- Review provenance labels appear only in review.
- `a` adds to the focused section.
- `J/K` never crosses section boundaries.
- Preview round trip preserves the same in-memory draft.
- Preview text equals the generated Markdown byte-for-byte for the same draft.
- Empty sections render `- None`.
- Coverage warnings render below the title.
- Same-day generation safely replaces the existing Daily artifact rather than raising generic report-exists behavior.

### Regression tests

- General Quick Review retains its current `OutcomeReviewDraft` interactions.
- General reports retain single-harness Report Setup semantics.
- Existing History entries and History UI remain readable.
- Existing report file conflict behavior remains unchanged outside Daily Standup.
