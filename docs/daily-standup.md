# Daily Standup

Daily Standup turns recent coding-agent activity into a short, reviewed update:

```text
iiwi daily
  → all enabled harnesses
  → Yesterday / Today / Blockers
  → Quick Review
  → Preview
  → Generate daily-standup-YYYY-MM-DD.md
```

Run `iiwi daily` in an interactive terminal, or choose **Daily Standup** from
the main menu. Both routes open the same review. Daily has no period or harness
picker: it includes child and subagent sessions from every enabled harness and
uses one local-time window from yesterday at 00:00 through the captured current
time.

## Review the draft

Activity timestamps decide whether evidence belongs under **Yesterday** or
**Today**. An **Activity today** label means work actually occurred today. A
**Suggested from yesterday** label appears only when yesterday contains explicit
unfinished or in-progress evidence; it is a proposal to confirm, edit, or
exclude, not a claim that today's work happened.

Detected command failures can appear under **Blockers**, but start excluded so
an error is never published as a blocker without review. A later successful run
or completion removes a resolved failure. Use `Space` to include or exclude a
statement, `e` to edit, `J/K` to reorder within a section, `v` to inspect its
evidence, and `a Add` to write a manual Yesterday, Today, or Blockers item.
Manual items do not need coding-agent evidence.

The first five Yesterday and Today candidates are shown initially; additional
ones remain under each section's **More candidates** row. Blocker candidates are
not capped. The shareable Markdown always renders the three sections in
Yesterday, Today, Blockers order, and an empty section is always written as
`- None`.

## Refresh and source coverage

Rerunning Daily Standup on the same local date reloads its reviewed state and
reconciles new evidence into it. Reviewer edits, exclusions, ordering, and
manual additions survive; newly observed work is labeled **New activity**.
Starting a new calendar date uses only that date's state, so yesterday's Today
plan is not copied forward merely because it was planned.

If some harnesses cannot be read, review continues with the available sources.
The coverage warning names the missing sources in Quick Review and directly
below the final Markdown title. If every source is unavailable, the recovery
screen offers Retry, Continue with an empty draft, or Back; continuing keeps a
coverage warning and still allows manual Add. If outcome grouping fails, Daily
retries once, then uses a labeled deterministic fallback draft without inventing
a Today plan; a coverage warning names the failure in Quick Review and in the
Markdown, so a report built from raw evidence says so. Refreshing after a
fallback replaces that draft outright unless you had already edited it.

## Preview, generate, and local state

`p Preview` renders the exact reviewed Markdown without writing it. `g Generate`
writes those same bytes to `daily-standup-YYYY-MM-DD.md` in the configured report
directory. Generating again on the same date safely replaces that date's Daily
file; ordinary reports retain their normal file-conflict behavior.

Reviewed Daily state is stored locally with owner-only permissions where the
platform supports them. It contains evidence references and review decisions,
not copied transcripts. Iiwi retains date-keyed Daily state for 30 days and
cleans older files opportunistically. Generated Daily Standups also appear in
History with successful and unavailable harness coverage recorded separately.
