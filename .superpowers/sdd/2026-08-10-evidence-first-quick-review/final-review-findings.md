# Final whole-branch review findings at `f38ebee`

Overall verdict: Not ready. No Critical findings. The following Important findings must be addressed in the single final fix wave.

## Important findings

1. Evidence trust boundary accepts ungrounded claims and merge authorization.
   - `src/iiwi/services/outcomes.py:40-48,167-199` copies model title/status/Impact/confidence/linkage values without validating claim support or signal values against extracted evidence.
   - Production discards claim-level provenance such as changed files, so file/commit evidence is not populated.
   - Existing tests manufacture compliant JSON for activity-free sessions; unsupported Impact is only tested with an empty value.
   - Consequence: hallucination/prompt injection can fabricate completion, Impact, or a cross-repository merge.

2. Candidate IDs and split recovery are unreliable.
   - Duplicate proposals can share an ID derived only from normalized title + session IDs; mutations target the first match.
   - Source groups exist only for cross-repository merges, so same-repository multi-session merges cannot be split.
   - Split copies aggregate parent Impact to every child without child-level support.
   - Consequence: review actions can target the wrong candidate and split can duplicate unsupported claims.

3. Setup Generate/Preview bypasses Quick Review and re-entry discards edits.
   - Setup `g`/Enter scans, synthesizes, and immediately previews/writes instead of showing `OUTCOME_REVIEW`; tests currently lock in this bypass.
   - Returning and re-entering synthesis unconditionally replaces the existing draft even when scan/selection are unchanged.
   - Consequence: claims can be written unseen and in-process edits/order/manual/gaps can disappear.

4. More candidates cannot visibly become/reorder among primary outcomes.
   - Space only changes `included`; rank changes do not change bucket; renderer always renders PRIMARY before MORE.
   - Consequence: visible reviewed order diverges from generated order and a promoted candidate remains collapsed.

5. Complete failure and fallback recovery are incomplete.
   - All extraction failures return an Ungrouped-only success rather than raising into Retry/session fallback.
   - Synthesis temp-file I/O can raise `OSError`, but only `OpenCodeRunError` is translated.
   - Fallback notice is cleared after an initial conflict, so `Overwrite once` publishes an unlabeled session fallback.

6. Report type and Detail parity are incomplete.
   - Manager/Engineering differ only by heading; sections/tone are otherwise identical and synthesis prompt is engineering-only.
   - Brief narrative relies only on prompt; renderer emits model body verbatim, so session/file/command/usage details can leak into Brief.
   - Tests lack the complete four-combination matrix and deterministic Brief narrative enforcement.

7. Quick Review omits required reporting period.
   - Renderer receives no period and header shows only `Quick Review` plus selected count.

8. Sensitive synthesis data persists indefinitely.
   - Quick Review constructs `OpenCodeRunner` without a caller-owned work directory; `iiwi-report-*` transcript/summary temp data is never removed, conflicting with `docs/privacy.md`.

9. Reviewed no-overwrite guarantee is race-prone.
   - `secure_write_text` checks existence, writes a temporary, then unconditionally `os.replace`s; a destination created after the check is overwritten with `force=False` and some conflicts surface as generic output errors rather than `ReportAlreadyExistsError`.

## Minor findings

- Empty Impact is hidden instead of visibly marked optional/unsupported.
- Truncated wrapped Impact/evidence lacks a continuation indicator.
- Ungrouped raw titles/IDs are rendered without the redaction applied by existing session screens.
- `docs/evidence-first-quick-review.md` contains trailing whitespace/extra blank-line formatting that makes `git diff --check` fail.
- Live resize with expanded evidence is untested.

## Verification baseline

- At `f38ebee`: ruff passed; pyright 0 errors; pytest `747 passed, 5 failed, 4 skipped`.
- Exact known baseline failures: `tests/unit/interactive/test_render.py` x4 ANSI assertions and `tests/unit/test_logging.py` x1.
- Physical TTY, live SIGWINCH, real model quality, Windows/non-root skipped paths, and a real concurrent overwrite reproduction were not verified.
