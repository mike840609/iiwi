# Evidence-first Quick Review Second-wave Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the four scoped evidence-first Quick Review findings, remove the tracked internal artifact, clean the documentation diff, verify the known baseline, commit the branch, and write the required ignored report.

**Architecture:** Keep model synthesis as a proposal boundary and enforce authorization/rendering decisions deterministically from local state. Make cross-repository checks repository-local, make Brief narrative rendering section-allowlisted and evidence-line conservative, make review reuse depend on effective output semantics, and extract commits only from explicit revision context.

**Tech Stack:** Python 3.12, Pydantic, Jinja2, pytest, Ruff, Pyright, uv.

## Global Constraints

- Work only in `/workspace/iiwi/.worktrees/evidence-first-quick-review` on `feat/evidence-first-quick-review` at base `ab9be51`.
- Do not reset, rebase, or modify the five known baseline-failing assertions.
- For every finding, add the regression first, observe its intended failure, implement the smallest fix, and rerun the covering test.
- Preserve high-confidence and allowed-kind merge rules, existing required headings, independent Detail behavior, unchanged-identity draft reuse, and existing public behavior outside the findings.
- Do not track `.superpowers/` reports.

---

### Task 1: Repository-grounded cross-repository linkage

**Files:**
- Modify: `tests/unit/services/test_outcomes.py`
- Modify: `src/iiwi/services/outcomes.py`

**Interfaces:**
- Consumes: `_ProposedOutcome`, selected `SessionEvidence`, and `local_texts_by_session`.
- Produces: `_may_merge_cross_repository(...) -> bool` that authorizes only signal kinds whose exact value is observed in every participating repository.

- [ ] Add tests where branch/direct-reference values are distributed across repositories and where a shared-work ID appears in only one repository; both must split.
- [ ] Run those tests and confirm they fail because the current aggregate corpus authorizes one merged outcome.
- [ ] Group selected evidence by `repository_id`; retain a signal only when `_value_is_observed` succeeds for every repository group; preserve high-confidence and kind-set rules.
- [ ] Run the focused service tests and confirm GREEN.

### Task 2: Deterministic report type and strict Brief rendering

**Files:**
- Modify: `tests/unit/renderers/test_outcome_markdown.py`
- Modify: `tests/unit/renderers/test_narrative.py`
- Modify: `src/iiwi/templates/outcomes.md.j2`
- Modify: `src/iiwi/renderers/markdown.py`

**Interfaces:**
- Consumes: `ReportType`, `DetailLevel`, outcome report data, and model narrative text.
- Produces: deterministic audience focus text independent of Detail; Brief narrative containing only Outcomes, In Progress, Blockers, Next Week, and trusted appended warnings, with no evidence/usage lines.

- [ ] Add a four-combination report type/detail matrix that requires audience-specific focus and proves Evidence/Usage remain Detail-owned.
- [ ] Add adversarial Brief tests for session IDs, paths, commands and fences, branches and commits, Usage, and an unexpected technical section.
- [ ] Run the renderer tests and confirm expected focus/leak failures.
- [ ] Add explicit Manager/Engineering focus text to the outcome template.
- [ ] Replace narrative heading denylisting with exact allowed-section parsing and conservative sensitive-line/fence filtering.
- [ ] Run the renderer tests and confirm GREEN.

### Task 3: Detail-aware Quick Review reuse

**Files:**
- Modify: `tests/unit/interactive/test_outcome_review_controller.py`
- Modify: `src/iiwi/interactive/controller.py`

**Interfaces:**
- Consumes: selected session IDs and the effective `ReportDraft` Detail semantics.
- Produces: a stable reuse identity that preserves the current draft when semantics match and resynthesizes after setup Detail changes.

- [ ] Add a controller flow that opens review, returns to setup, changes Detail, re-enters with the same sessions, and requires the replacement synthesis draft.
- [ ] Run that test and confirm it fails with only one synthesis and the stale draft.
- [ ] Extend the reuse identity with effective Detail and override state; keep the identity synchronized when Quick Review changes report type/default Detail in place.
- [ ] Run focused controller tests and confirm GREEN, including unchanged-selection preservation.

### Task 4: Contextual commit extraction

**Files:**
- Modify: `tests/unit/services/test_outcomes.py`
- Modify: `src/iiwi/services/outcomes.py`

**Interfaces:**
- Consumes: extracted local evidence text.
- Produces: `EvidenceRef.commit` only for a 7–40 hex hash following explicit commit/revision/SHA wording or a commit-oriented git command.

- [ ] Add one test proving an arbitrary hex identifier does not become a commit and one proving `git show <hash>` does.
- [ ] Run both tests and confirm the arbitrary identifier test fails under the bare-hex pattern.
- [ ] Restrict `_COMMIT_PATTERN` to contextual matches and return its named hash group.
- [ ] Run focused service tests and confirm GREEN.

### Task 5: Cleanup, verification, commit, and report

**Files:**
- Delete from Git: `.superpowers/sdd/2026-08-10-evidence-first-quick-review/final-fix-report.md`
- Modify: `docs/evidence-first-quick-review.md`
- Create ignored: `.superpowers/sdd/2026-08-10-evidence-first-quick-review/second-wave-fix-report.md`

**Interfaces:**
- Consumes: completed code/test diff and fresh command output.
- Produces: one coherent branch commit and a detailed ignored repair report.

- [ ] Remove the tracked final-fix report and normalize the documentation EOF.
- [ ] Run the required focused pytest command, `ruff check .`, `pyright`, full pytest, and `git diff --check`; record exact outputs and the five baseline failures.
- [ ] Inspect `git diff`, status, and staged scope; commit the coherent change on the current branch.
- [ ] Write the ignored second-wave report with status, commit, per-finding RED/GREEN evidence, all verification results, and concerns.
