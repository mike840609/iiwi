# SDD ledger — plan: implementation-plan.md

## Setup

- Worktree: `/workspace/iiwi/.worktrees/evidence-first-quick-review`
- Branch: `feat/evidence-first-quick-review`
- Base: `2a85f797e450e9213ca2de52d3a9084eb1103681`
- Baseline: `662 passed, 5 failed, 4 skipped` (`tests/unit/interactive/test_render.py` x4 and `tests/unit/test_logging.py` x1; pre-existing failures)
- Plan scan: no contradictions found between Global Constraints and task requirements.

## Tasks

- [x] Task 1: Outcome and Review-Draft Domain Model
- [x] Task 2: Deterministic Outcome Synthesis Boundary
- [x] Task 3: Reviewed Report Rendering and Detail Parity
- [x] Task 4: Quick Review Actions, Configuration, and Draft Editing
- [x] Task 5: Rendered-line-aware Single-screen TUI
- [x] Task 6: Retry, Partial Failure, and Session-report Fallback
- [x] Task 7: End-to-end Compatibility, Documentation, and Final Verification

Task 1: fix round 1/5 (2 addressed, 0 open — constructor Detail override; split without source groups; commits d7e2c45..cb7b608)
Task 1: complete (commits d7e2c45..cb7b608, review clean)
Task 2: fix round 1/5 (1 addressed, 0 open — blank linkage values; commits f33e5b2..e1c35bd)
Task 2: complete (commits cb7b608..e1c35bd, review clean)
Task 3: fix round 1/5 (1 addressed, 0 open — Brief narrative usage collection; commits b0b4148..fefe69c)
Task 3: complete (commits e1c35bd..fefe69c, review clean)
Task 4: fix round 1/5 (2 addressed, 0 open — blank gap clearing; complete key coverage; commits c6fe165..6014cd5)
Task 4: minor (deferred): four pre-existing ANSI-style assertions remain failing in tests/unit/interactive/test_render.py.
Task 4: complete (commits fefe69c..6014cd5, review clean)
Task 5: fix round 1/5 (2 addressed, 0 open — hard-break line budgeting; controller-renderer integration coverage; commits 8ddcae2..35609dc)
Task 5: minor (deferred): four pre-existing ANSI-style assertions remain failing in tests/unit/interactive/test_render.py.
Task 5: complete (commits 6014cd5..35609dc, review clean)
Task 6: complete (commits 35609dc..2b9af45, review clean)
Task 7: fix round 1/5 (3 addressed, 0 open — real synthesis recovery; named cross-repository split; real narrative run compatibility; commits 6c68d99..f38ebee)
Task 7: minor (deferred): the end-to-end unsupported-Impact assertion proves omission for an excluded outcome but is not by itself evidence-backed synthesis proof.
Task 7: complete (commits 2b9af45..f38ebee, review clean)

## Final review

Final review at f38ebee: not ready (9 Important findings; single final fix wave authorized by SDD).
Final fix wave: commit ab9be51 (7/9 original Important findings addressed; full suite recorded as 772 passed, 5 known baseline failures, 4 skipped).
Final scoped re-review: BLOCKED — evidence trust boundary still permits unshared cross-repository linkage and unrelated evidence to authorize Impact/completion; Manager/Engineering remain structurally equivalent and Brief narrative filtering leaks full-depth evidence; review reuse ignores changed Detail; arbitrary hex-like text can be published as a commit.
Final scoped re-review: minor (deferred): final Markdown publishes an unsupported-Impact placeholder; branch-range diff-check reports docs/evidence-first-quick-review.md EOF whitespace; internal .superpowers final-fix-report.md was accidentally tracked; live resize remains unverified.

## Authorized second wave

Second-wave fixer: commit `89e4475`; focused 70 passed; Ruff and Pyright clean; full suite 779 passed, 5 known baseline failures, 4 skipped; diff-check clean.
Second-wave scoped re-review: findings 1, 3, and 4 addressed; cleanup addressed; finding 2 remains open — Brief narrative filtering does not handle setext headings or evidence lines without a colon, so unexpected technical content can still leak.
Second-wave status: BLOCKED — remaining Brief evidence-boundary finding is load-bearing; no further fix wave dispatched under the current authorization.
