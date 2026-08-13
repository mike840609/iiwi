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

`Daily Standup` is a direct shortcut. It does not enter normal Report Setup or Session Review.

CLI:

```text
iiwi daily
```

`iiwi daily` enters the same Daily Quick Review flow as the interactive main-menu action.

Version one deliberately has no `--no-review`. Today suggestions and blocker candidates require human confirmation before they become a generated artifact.

## Architecture

Daily Standup should extend the existing evidence-first Quick Review architecture rather than create a parallel reporting engine.

```text
All enabled harnesses
        ↓
DailyScanCoordinator
        ↓
one union window: yesterday 00:00 → now
        ↓
existing evidence extraction
        ↓
existing Outcome grouping
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

The current `OutcomeSynthesisService` already groups sessions into evidence-backed outcomes and reconstructs claims from local evidence. Daily Standup must reuse that grouping primitive instead of asking another model to regroup the same work.

Daily-specific synthesis is a projection layer over grouped outcomes and evidence:

1. Determine which source activities fall into Yesterday or Today by timestamp.
2. Produce section-specific standup statements for the same underlying work item.
3. Derive blocker candidates only from unresolved evidence.

The same underlying work may therefore appear in both Yesterday and Today with different wording:

- Yesterday describes progress that already occurred.
- Today describes current activity or a reviewer-confirmable suggested next step.

### DailyScanCoordinator

Do not make the existing single-harness `ScanService` multi-harness.

Add a Daily-specific coordinator that runs the existing `ScanService` independently for every enabled harness, then merges successful results for downstream grouping.

Responsibilities:

- Resolve all enabled harnesses.
- Run the same union period against each harness.
- Preserve per-harness warnings.
- Continue on partial harness failure.
- Distinguish no activity from total source failure.
- Produce one merged set of resolved sessions for grouping.

Harness identity remains evidence provenance, not work-item identity.

### Cross-repository and cross-harness grouping

One standup work item may combine evidence from multiple repositories and multiple harnesses when the existing grouping evidence supports one shared work objective.

Repository equality alone is not sufficient reason to merge work.

Harness equality or difference must not affect grouping identity.

Final standup bullets list all repositories involved, for example:

```markdown
- [api, sdk, web] Finished the authentication migration.
```

The final artifact does not expose harness names.

## Evidence and timestamp projection

Current evidence items carry `source_activity_ids`; activity timestamps live on `SessionActivity`.

Daily section assignment must be deterministic:

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

Persistent Daily reconciliation needs finer provenance than a session id alone because one session may span midnight and may receive new activity later in the same day.

Extend `EvidenceRef` backward-compatibly with activity identity, conceptually:

```python
activity_ids: list[str] = []
```

Existing report consumers may ignore this field.

Daily state can then distinguish evidence already reviewed from newly observed activity in an existing session.

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
├─ id
├─ source_outcome_ids[]
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

- work-item identity;
- section statements;
- source outcome ids;
- evidence references;
- include/exclude state;
- section order;
- reviewer-edited flags;
- user-added items;
- latest scan/generation timestamp;
- reconciliation metadata;
- warnings/source coverage needed to reproduce the current draft.

Create state directories owner-only and state files owner-only where the platform supports permissions.

### Retention

Keep Daily structured state for 30 days.

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

If every enabled harness fails, do not present the condition as "no activity".

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
├─ harnesses[]
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
```

New Daily entries record the harnesses whose data contributed or were attempted according to the final implementation's coverage model; History UI identifies the artifact as `Daily Standup` rather than displaying a fabricated `multiple` harness.

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
- Preserve reviewer wording exactly apart from normal Markdown escaping/formatting required for a valid artifact.

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
6. Partial harness failures continue with explicit warnings; total source failure enters recoverable error.
7. Genuine no-activity periods enter an empty but usable Quick Review.
8. Existing Iiwi-authored synthesis sessions remain excluded through the current scan filtering boundary.
9. Existing evidence extraction and Outcome grouping are reused; Daily does not introduce a second grouping pass.
10. Evidence is projected into Yesterday/Today deterministically by source activity timestamp.
11. One work item can span repositories, harnesses, Yesterday, and Today when evidence supports that identity.
12. Yesterday includes substantive progress, including tangible in-progress work.
13. Today prefers actual Today activity, then supported unfinished-work/next-step suggestions, and otherwise invents nothing.
14. Suggested Today items are visibly distinguished during review.
15. Blockers require unresolved blocker evidence.
16. Yesterday and Today each preselect at most five candidates, with extra candidates available under More candidates.
17. All three sections support manual Add.
18. Daily Quick Review supports include/exclude, statement edit, within-section reorder, Evidence, Add, Preview, Generate, Help, and Back.
19. Preview renders the exact artifact Generate will write without another synthesis call.
20. Generate writes `reports/daily-standup-YYYY-MM-DD.md` and updates that same file on later same-day generations.
21. Same-day reruns restore structured Daily state and reconcile new evidence while preserving reviewer edits, additions, exclusions, and ordering.
22. The next local calendar day does not automatically carry forward the previous day's Today plan.
23. Daily state is owner-private where supported and stores references/state rather than copied transcripts.
24. Daily state older than 30 days is cleaned opportunistically without blocking Daily execution on cleanup failure.
25. Total synthesis failure still provides a deterministic fallback draft for review.
26. The generated Markdown always contains Yesterday, Today, and Blockers, using `- None` for empty sections.
27. Partial or empty-source continuation warnings remain visible in the final Markdown.
28. History records Daily Standup as its own artifact kind while continuing to read legacy single-harness history entries.
29. General Generate Report and its existing Quick Review behavior remain unchanged except for backward-compatible shared model/history extensions required by Daily.

## Testing strategy

Tests should protect both the new Daily behavior and the existing general report behavior.

### Domain/unit tests

- Calendar-boundary calculation, including a DST-observing timezone.
- Evidence activity-id to Yesterday/Today projection.
- One outcome projecting into both Yesterday and Today.
- Today actual-activity priority over Yesterday suggestion.
- No speculative Today candidate without evidence.
- Unresolved versus resolved blocker classification.
- Primary-five versus More candidates independently for Yesterday and Today.
- Cross-repository label preservation.
- User-added item behavior.
- Reviewer edit/exclusion/order preservation during reconciliation.
- New-activity detection on a later same-day scan.
- No cross-day Today carry-over.
- Persistent-state serialization round trip.
- Thirty-day cleanup and non-fatal cleanup errors.
- Legacy `EvidenceRef` payloads without activity ids remain valid.
- Legacy history JSONL remains readable after the History model extension.

### Coordinator/service tests

- All enabled harnesses succeed and merge.
- One harness fails and other harnesses continue with warnings.
- All harnesses fail and trigger recoverable error semantics.
- All harnesses succeed with zero activity and produce an empty draft.
- Existing self-authored Iiwi session filtering remains effective.
- Outcome grouping is called once over the merged Daily evidence set rather than once per section.
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

- General Quick Review retains its current OutcomeReviewDraft interactions.
- General reports retain single-harness Report Setup semantics.
- Existing History entries and History UI remain readable.
- Existing report file conflict behavior remains unchanged outside Daily Standup.
