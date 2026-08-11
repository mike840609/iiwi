### Task 7: End-to-end Compatibility, Documentation, and Final Verification

**Files:**
- Modify: `tests/integration/test_interactive_cli.py`
- Modify: `tests/integration/test_cli.py`
- Modify: `tests/unit/test_documentation.py`
- Modify: `tests/unit/test_interactive_documentation.py`
- Modify: `README.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/configuration.md`
- Create: `docs/evidence-first-quick-review.md`

**Interfaces:**
- Consumes: the complete Quick Review flow from Tasks 1–6.
- Produces: executable user documentation and full-suite proof that legacy CLI behavior remains compatible.

- [ ] **Step 1: Add end-to-end interactive tests**

Use a deterministic synthesis runner and temporary output directory. Drive this complete flow:

```text
New report → Review sessions → Generate outcomes → exclude one outcome
→ edit another → add manual outcome → set Blockers/Next week
→ Preview → Back → Generate → Result
```

Assert the file contains the reviewed order and edits, omits the excluded outcome, labels the user-added outcome, contains the optional gaps, and contains no unsupported Impact.

Add a second flow for a 20-line terminal with six candidates, More candidates, expanded evidence, Preview failure, return, and successful retry.

- [ ] **Step 2: Add non-interactive compatibility tests**

In `tests/integration/test_cli.py`, preserve the existing command shape and assert both:

```python
runner.invoke(app, ["run", "--detail", "brief"])
runner.invoke(app, ["run", "--detail", "full"])
```

still generate the session-based report without invoking outcome synthesis. Assert the prior narrative and structured detail differences remain intact.

- [ ] **Step 3: Run integration tests and confirm documentation is the remaining failure**

Run: `uv run pytest tests/integration/test_interactive_cli.py tests/integration/test_cli.py -q`

Expected: PASS for behavior. Documentation tests added in the next step still fail until copy is updated.

- [ ] **Step 4: Document only shipped behavior**

Update README and docs with:

- Outcome-first explanation and the 30–60 second target.
- Manager vs Engineering and Brief vs Full responsibility table.
- Keys: Space, e, J/K, v, s, a, p, g, b.
- More candidates and Ungrouped candidates behavior.
- User-added outcomes and optional Blockers/Next week.
- Explicit synthesis retry/session-report fallback.
- `report.quick_review_report_type` configuration and environment variable.
- Version-one exclusions, including no persistent drafts and no manual merge.

Make documentation tests assert the exact config key and the `p Preview`/`g Generate` distinction so stale docs fail visibly.

- [ ] **Step 5: Run static checks and the full suite**

Run: `uv run ruff check .`

Expected: no diagnostics.

Run: `uv run pyright`

Expected: 0 errors.

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Manually verify the viewport and fallback**

Run: `uv run iiwi`

Verify in terminals at 20, 24, and 30 rows:

- the focused row and key help stay visible;
- long Impact/evidence truncates before screen controls disappear;
- More candidates can replace a primary outcome;
- Preview Back preserves all edits;
- a forced synthesis failure exposes Retry and session-based fallback;
- the final report matches Report type and Detail.

- [ ] **Step 7: Commit documentation and integration proof**

```bash
git add README.md docs/cli-reference.md docs/configuration.md docs/evidence-first-quick-review.md tests/integration/test_interactive_cli.py tests/integration/test_cli.py tests/unit/test_documentation.py tests/unit/test_interactive_documentation.py
git commit -m "docs: document evidence-first quick review"
```

---

## Final Acceptance Gate

- [ ] Related sessions produce one traceable outcome; the high-confidence cross-repository fixture merges.
- [ ] Low-confidence or weak-signal cross-repository work remains separate.
- [ ] Up to five outcomes are preselected and every remaining candidate is retained.
- [ ] Include, exclude, edit, reorder, split, add, Blockers, and Next week work from documented keys.
- [ ] Preview and all recoverable errors preserve the in-memory draft.
- [ ] Partial synthesis produces Ungrouped candidates; complete failure supports retry and explicit session-report fallback.
- [ ] Manager/Engineering and Brief/Full combinations render correctly.
- [ ] Narrative and structured session-based reports both honor Detail.
- [ ] The 20–30 line terminal matrix keeps focus and action help visible.
- [ ] Existing non-interactive CLI and `--detail brief|full` remain compatible.
