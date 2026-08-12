# Quick Review Output Quality: Group Titles and Self-Authored Sessions

**Date:** 2026-08-12

## Summary

A live Quick Review over 172 real OpenCode sessions produced a report nobody
would send. Two independent defects account for it, and both were invisible
until the compact synthesis payload widened coverage from 17 sessions to 103.

**Unreadable group titles.** `_supported_title` accepts the model's proposed
title only when *every* word longer than two characters appears in the evidence
corpus. Half the proposals fail that gate, and the fallback joins every session
title in the group with `" / "`, so an eleven-session group renders as an
eleven-clause title.

**Iiwi reporting on itself.** Every `opencode run` iiwi invokes leaves a session
in the OpenCode store. The next scan picks those up and reports them as work. A
30-day scan of 175 sessions contained 15 of them.

This design loosens the title gate to a measured proportional threshold, gives
the fallback a readable shape, and excludes iiwi's own sessions at the scan
chokepoint.

## Measurements

Both fixes are calibrated against the local OpenCode store, not estimated.

**Title rejections.** Instrumenting `_supported_title` across one live synthesis:

| proposals | accepted | rejected |
|---|---|---|
| 10 | 5 | 5 |

Word hit rates of the five rejections: 84.6%, 66.7%, 85.7%, 90.9%, 90.0%. The
words that missed were `selection`, `improvements`, `feature`, `wave`, `polish`,
`bars`, `housekeeping` — the vocabulary of summarizing. Every substantive term
(`DateRange.current_week`, `choose_period`, `flicker`, `viewport`,
`superpowers`) hit the corpus.

Prefix and stem matching was measured as an alternative and rejects seven of the
same eight words, so morphology is not the cause and stemming is not the fix.

**Self-authored sessions.** A 30-day scan holds 175 sessions, 15 of them written
by iiwi, in three title forms: `Iiwi outcome synthesis`, `Iiwi narrative
summary`, and `Iiwi - <date> to <date>`. No human-authored session in that
window begins with `Iiwi`, though one mentions the name mid-title
(`agent-worklog 更名 iiwi 進度整理`).

## Goals

- A grouped outcome carries a title a reader can scan in one line.
- The model's proposed title survives when it is substantively supported.
- Iiwi's own runs never appear as work, in any screen or report.
- The evidence boundary holds: status and impact gates are untouched.

## Non-goals

- No change to `_supported_status` or `_supported_impact`. The title is the only
  surface this loosens.
- No change to the multi-repository fallback. Repository counts are small and
  joining two or three identifiers stays readable.
- No stemming, lemmatization, or synonym matching in the corpus check.
- No warning when self-authored sessions are dropped. They were never the user's
  work, so their absence needs no explanation.

## Design

### 1. Excluding self-authored sessions

**Marker.** Every title iiwi writes to an OpenCode session gains an
`iiwi-internal: ` prefix:

```
iiwi-internal: outcome synthesis
iiwi-internal: narrative 2026-08-05 to 2026-08-12
```

ASCII, readable in OpenCode's own session list, and it preserves the period the
narrative title already carried — the two dates are the report period's `since`
and `until` in ISO form, as today. A human typing that prefix is not a case
worth designing for.

**Predicate.** `sessions/filtering.py` gains:

```python
def is_iiwi_authored(session: AgentSession) -> bool
```

That module already owns the question "does this session belong in a report" —
`filter_session_to_period` lives there — so the new predicate sits beside it
rather than in a service.

**Rules.** A session is iiwi-authored when its title:

- starts with `iiwi-internal: `, or
- equals `Iiwi outcome synthesis`, or
- equals `Iiwi narrative summary`, or
- matches `^Iiwi - \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}$`

Legacy titles are matched **exactly**, never by prefix, so a future
human-authored session named `Iiwi main menu rework` survives. `Iiwi narrative
summary` is not a string iiwi's code emits; it was produced by iiwi's own runner
during diagnostics with a non-default title argument. It is listed because the
predicate's purpose is "is this iiwi machinery", not "is this a string the code
contains", and the sessions it matches are machinery. The code carries a comment
saying so.

**Placement.** `ScanService.scan()` calls the predicate in its existing
per-session loop, beside `filter_session_to_period` (`services/scan.py:144`).
One chokepoint, so Quick Review, Browse Activity, the session-based report, and
every session count exclude them together.

This changes behaviour shipped in 0.10.0: the session-based narrative report
stops seeing these sessions. That is the intent.

### 2. Title support threshold

`_supported_title` changes from all-or-nothing to a proportion:

```python
_TITLE_SUPPORT_RATIO = 0.8
```

Acceptance becomes `hits / len(words) >= 0.8`. Everything else holds: only words
longer than two characters count, matching stays a substring test against the
corpus, and an empty word list still falls back.

Short titles keep needing full support as a side effect — three words need
three hits, two words need two — which is the conservative direction.

Against the measured data the threshold accepts four of the five rejections and
still refuses the 66.7% case, taking the fallback rate from five in ten to one
in ten.

The words this admits are editorial (`polish`, `wave`, `housekeeping`), not
factual claims. Status remains gated by `_supported_status`, which requires
high-confidence completed evidence, and impact remains gated by
`_supported_impact`, which still requires the whole string in the corpus.

### 3. Fallback title shape

`_fallback_title` keeps its single-session and multi-repository branches. The
multi-session, single-repository branch becomes:

```
<anchor title> and 7 more sessions
```

with the singular `and 1 more session` at N = 1.

**Anchor.** The session with the most extracted evidence items, counting
`goals + commands + files_changed + errors + outcomes`. Ties resolve to whichever
comes first in the `selected` list `_fallback_title` was given, which preserves
the caller's order and keeps the result deterministic.

Total evidence items rather than evidence-reference count: `_evidence_refs`
emits one reference per changed file, so ranking by references means "the
session that touched the most files", and a rename sweep across fifty files
would outrank the feature work beside it.

First-in-list rather than most-recent for ties: `SessionEvidence` carries no
timestamp, so recency would mean threading the `started_at` map through three
call sites to break a rare tie.

## Data flow

```
ScanService.scan()
  └─ per session: filter_session_to_period
                  is_iiwi_authored          ← new, drops the session
       ↓
  ResolvedSession[]  (no iiwi-authored sessions anywhere downstream)
       ↓
OutcomeSynthesisService.synthesize
  └─ _supported_title (≥80%)  ─── accepted ──→ model's title
                              └─ rejected ───→ _fallback_title
                                                 └─ anchor + "and N more sessions"
```

## Error handling

Neither change introduces a failure mode. `is_iiwi_authored` is a string test,
the threshold is arithmetic, and the fallback is string assembly — no I/O, no
new exception type, no new error path. A `None` or empty title is not
iiwi-authored.

The one behavioural risk is a false positive dropping real work, and exact
matching on legacy titles is what contains it.

## Testing

Requirement-driven, one or more cases per rule above.

**`tests/unit/sessions/test_filtering.py`**

- Each of the four title forms is recognised: the new prefix, both legacy
  constants, and the dated narrative pattern.
- A human title beginning with `Iiwi ` but not matching exactly is **not**
  dropped. This is the reason exact matching exists and must be pinned.
- `None` and empty titles are handled without raising.

**`tests/integration/`**

- A scan containing iiwi-authored sessions returns none of them, and the session
  count drops accordingly — proving the filter sits at the chokepoint rather
  than in one consumer.

**`tests/unit/services/test_outcomes.py`**

- Hit rates of 100%, exactly 80%, and 79% — the boundary in both directions.
- Two-word and three-word titles still require every word.
- An empty word list falls back.
- A multi-session single-repository group renders `<anchor> and N more
  sessions`, with the singular form at N = 1.
- The anchor is the session with the most evidence items, pinned by a case where
  a fifty-file session with one evidence item loses to a three-file session with
  eight.
- Single-session and multi-repository fallbacks are unchanged.

**`tests/unit/summarizers/`**

- The two titles iiwi writes satisfy `is_iiwi_authored`. This is the only
  coupling between the runner and the filter, and it is exactly the thing a
  future title change would silently break.
