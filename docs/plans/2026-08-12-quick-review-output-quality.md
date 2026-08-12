# Quick Review Output Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Quick Review from reporting iiwi's own `opencode run` sessions as work, and stop it from rendering eleven-clause fallback titles.

**Architecture:** Two independent changes. A new predicate in `iiwi/sessions/filtering.py` recognises the titles iiwi writes to OpenCode and `ScanService.scan()` drops those sessions at its existing per-session chokepoint, so every screen and report excludes them together. Separately, `_supported_title` in `iiwi/services/outcomes.py` changes from an all-or-nothing corpus check to a 0.8 proportional threshold, and `_fallback_title` stops joining every session title when a group shares one repository.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, Ruff, Pyright, `uv`.

Design record: `docs/2026-08-12-quick-review-output-quality-design.md`.

## Global Constraints

- Branch from `main`. This work does not depend on PR #87 and does not touch the functions it changes.
- Every verification command is prefixed `uv run --extra dev`. A bare `uv run ruff` fails: the tooling lives in the `dev` extra, not a dependency group.
- Full gate before any task is marked complete: `uv run --extra dev ruff check .`, `uv run --extra dev pyright`, `uv run --extra dev pytest -q`.
- `_supported_status` and `_supported_impact` must not change. The title is the only gate this plan loosens.
- Legacy iiwi titles are matched **exactly**, never by prefix. A human session named `Iiwi main menu rework` must survive.
- No new warning when a self-authored session is dropped.
- Comments only where intent is non-obvious. Match the surrounding file's density.

## File Structure

| File | Responsibility |
|---|---|
| `src/iiwi/sessions/filtering.py` | Owns "does this session belong in a report". Gains `is_iiwi_authored`. |
| `src/iiwi/services/scan.py` | Calls the predicate at its existing per-session chokepoint (line 144). |
| `src/iiwi/services/outcomes.py` | Writes the synthesis session title; owns `_supported_title` and `_fallback_title`. |
| `src/iiwi/services/report.py` | Writes the narrative session title. |
| `tests/unit/sessions/test_filtering.py` | Predicate rules, including the must-not-drop case. |
| `tests/integration/test_scan_service.py` | Proves the filter sits at the chokepoint. |
| `tests/unit/services/test_outcomes.py` | Threshold boundary, anchor selection, fallback shape, title/predicate coupling. |

---

### Task 1: The `is_iiwi_authored` predicate

**Files:**
- Modify: `src/iiwi/sessions/filtering.py`
- Test: `tests/unit/sessions/test_filtering.py`

**Interfaces:**
- Consumes: `iiwi.models.session.AgentSession`.
- Produces: `is_iiwi_authored(session: AgentSession) -> bool`, and the module constant `IIWI_SESSION_TITLE_PREFIX: str = "iiwi-internal: "`. Tasks 2 and 3 both import these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/sessions/test_filtering.py`:

```python
import pytest

from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX, is_iiwi_authored


def _titled(title: str | None) -> AgentSession:
    return AgentSession(harness="opencode", session_id="s1", title=title)


@pytest.mark.parametrize(
    "title",
    [
        "iiwi-internal: outcome synthesis",
        "iiwi-internal: narrative 2026-08-05 to 2026-08-12",
        "Iiwi outcome synthesis",
        "Iiwi narrative summary",
        "Iiwi - 2026-08-05 to 2026-08-12",
    ],
)
def test_titles_iiwi_writes_are_recognized(title: str) -> None:
    assert is_iiwi_authored(_titled(title)) is True


@pytest.mark.parametrize(
    "title",
    [
        "Iiwi main menu rework",
        "Iiwi outcome synthesis rewrite",
        "iiwi-internal notes",
        "agent-worklog 更名 iiwi 進度整理",
        "Iiwi - not a date range",
        "Iiwi - 2026-08-05 to yesterday",
    ],
)
def test_human_titles_are_not_dropped(title: str) -> None:
    assert is_iiwi_authored(_titled(title)) is False


@pytest.mark.parametrize("title", [None, "", "   "])
def test_absent_titles_are_not_iiwi_authored(title: str | None) -> None:
    assert is_iiwi_authored(_titled(title)) is False


def test_prefix_constant_matches_what_the_predicate_accepts() -> None:
    assert is_iiwi_authored(_titled(f"{IIWI_SESSION_TITLE_PREFIX}anything")) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/sessions/test_filtering.py -q`
Expected: FAIL with `ImportError: cannot import name 'IIWI_SESSION_TITLE_PREFIX'`.

- [ ] **Step 3: Write the implementation**

Add to the top of `src/iiwi/sessions/filtering.py`, after the existing imports:

```python
import re

IIWI_SESSION_TITLE_PREFIX = "iiwi-internal: "
# Titles iiwi wrote before the prefix existed. Matched exactly, never by
# prefix, so a human session named "Iiwi main menu rework" still counts as
# work. "Iiwi narrative summary" is not a string iiwi's code emits — it came
# from iiwi's own runner during diagnostics with a non-default title — but the
# sessions it matches are iiwi machinery, which is what this predicate is for.
_LEGACY_IIWI_TITLES = frozenset(
    {"Iiwi outcome synthesis", "Iiwi narrative summary"}
)
_LEGACY_IIWI_NARRATIVE = re.compile(
    r"^Iiwi - \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}$"
)
```

Add the predicate at the end of the module:

```python
def is_iiwi_authored(session: AgentSession) -> bool:
    """Return whether iiwi's own `opencode run` created this session."""

    title = (session.title or "").strip()
    if not title:
        return False
    return (
        title.startswith(IIWI_SESSION_TITLE_PREFIX)
        or title in _LEGACY_IIWI_TITLES
        or _LEGACY_IIWI_NARRATIVE.match(title) is not None
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/sessions/test_filtering.py -q`
Expected: PASS, including the pre-existing `filter_session_to_period` tests.

- [ ] **Step 5: Run the full gate**

```bash
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run --extra dev pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/sessions/filtering.py tests/unit/sessions/test_filtering.py
git commit -m "feat: recognize the sessions iiwi's own opencode runs leave behind"
```

---

### Task 2: Mark iiwi's own runs with the new prefix

**Files:**
- Modify: `src/iiwi/services/outcomes.py` (the `title=` argument at the `self._runner.run(...)` call inside `synthesize`)
- Modify: `src/iiwi/services/report.py` (the `title=` argument at the `self._opencode_runner.run(...)` call inside `_narrative_report`)
- Test: `tests/unit/services/test_outcomes.py`

**Interfaces:**
- Consumes: `IIWI_SESSION_TITLE_PREFIX` and `is_iiwi_authored` from Task 1; `StaticRunner` and `one_scan` already defined at the top of `tests/unit/services/test_outcomes.py`.
- Produces: no new callable. After this task every title iiwi writes satisfies `is_iiwi_authored`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/services/test_outcomes.py`:

```python
from iiwi.models.session import AgentSession
from iiwi.sessions.filtering import is_iiwi_authored


def test_the_synthesis_session_title_is_filtered_back_out() -> None:
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(one_scan())

    title = runner.calls[0]["title"]
    assert is_iiwi_authored(
        AgentSession(harness="opencode", session_id="x", title=title)
    ), title
```

- [ ] **Step 2: Run the test and expect it to pass already**

Run: `uv run --extra dev pytest tests/unit/services/test_outcomes.py::test_the_synthesis_session_title_is_filtered_back_out -q`
Expected: PASS. This is the one test in the plan that is green before its implementation, because the legacy exact match from Task 1 already covers `Iiwi outcome synthesis`. It earns its place as the guard that a future title change cannot silently escape the filter — verify that by temporarily changing the title in `synthesize` to `"anything else"`, watching the test fail, and reverting.

- [ ] **Step 3: Change both titles**

In `src/iiwi/services/outcomes.py`, inside `synthesize`, replace:

```python
                title="Iiwi outcome synthesis",
```

with:

```python
                title=f"{IIWI_SESSION_TITLE_PREFIX}outcome synthesis",
```

and add to that module's imports:

```python
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
```

In `src/iiwi/services/report.py`, inside `_narrative_report`, replace:

```python
            title=(
                f"Iiwi - {self._period.since.date().isoformat()} "
                f"to {self._period.until.date().isoformat()}"
            ),
```

with:

```python
            title=(
                f"{IIWI_SESSION_TITLE_PREFIX}narrative "
                f"{self._period.since.date().isoformat()} "
                f"to {self._period.until.date().isoformat()}"
            ),
```

and add to that module's imports:

```python
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
```

- [ ] **Step 4: Write the narrative-side coupling test**

No test today asserts the title `report.py` produces — `tests/unit/summarizers/test_opencode_run.py:67` passes a title *into* the runner as an input, so it is unaffected by this change and needs no edit.

Assert on the title the service actually emits, not on a string rebuilt by hand. `FakeOpenCodeRunner` at `tests/integration/test_report_service.py:70` already records `calls[i]["title"]`, and `narrative_service(...)` at line 122 builds the service. Append to that file:

```python
def test_the_narrative_session_title_is_filtered_back_out(tmp_path: Path) -> None:
    runner = FakeOpenCodeRunner()
    service = narrative_service(FakeSource(), tmp_path / "report.md", runner=runner)

    service.generate()

    title = runner.calls[0]["title"]
    assert is_iiwi_authored(
        AgentSession(harness="opencode", session_id="x", title=title)
    ), title
```

Add to that file's imports:

```python
from iiwi.models.session import AgentSession
from iiwi.sessions.filtering import is_iiwi_authored
```

If `service.generate()` needs arguments in this file's other tests, match how they call it.

The design record placed this test under `tests/unit/summarizers/`. It belongs here instead: the title is composed by `services/report.py`, and the summarizer only forwards whatever string it is handed, so a summarizer-level test could not catch a services-level title change.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/services/test_outcomes.py tests/integration/test_report_service.py -q`
Expected: PASS. If an existing test asserted the old `Iiwi - <date> to <date>` title verbatim, it fails here and its expected string is what you update — do not weaken the assertion to a substring check.

- [ ] **Step 6: Run the full gate**

```bash
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run --extra dev pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/services/outcomes.py src/iiwi/services/report.py tests/
git commit -m "feat: title iiwi's own opencode runs so they can be filtered back out"
```

---

### Task 3: Drop self-authored sessions at the scan chokepoint

**Files:**
- Modify: `src/iiwi/services/scan.py` (the per-session loop around line 144)
- Modify: `docs/limitations.md` (under `## General`)
- Modify: `docs/evidence-first-quick-review.md` (under `## Start the review`)
- Modify: `CHANGELOG.md` (the existing `## Unreleased` section)
- Test: `tests/integration/test_scan_service.py`

**Interfaces:**
- Consumes: `is_iiwi_authored` from Task 1; `FakeSource`, `StaticResolver`, `period`, and `TZ` already defined at the top of `tests/integration/test_scan_service.py`.
- Produces: no new callable. After this task no `ScanResult` contains an iiwi-authored session.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_scan_service.py`:

```python
class IiwiAuthoredSource:
    """One human session beside two sessions iiwi's own runs left behind."""

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return [
            SessionDescriptor(harness="opencode", session_id="human"),
            SessionDescriptor(harness="opencode", session_id="synthesis"),
            SessionDescriptor(harness="opencode", session_id="narrative"),
        ]

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        titles = {
            "human": "Add weekly report generation",
            "synthesis": "iiwi-internal: outcome synthesis",
            "narrative": "Iiwi - 2026-07-20 to 2026-07-27",
        }
        return AgentSession(
            harness="opencode",
            session_id=descriptor.session_id,
            title=titles[descriptor.session_id],
            activities=[
                SessionActivity(
                    activity_id=f"{descriptor.session_id}:a1",
                    activity_type=ActivityType.USER_MESSAGE,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="Add weekly report generation",
                )
            ],
        )


def test_scan_excludes_the_sessions_iiwi_itself_created() -> None:
    result = ScanService(
        source=IiwiAuthoredSource(),
        resolver=StaticResolver(),
        period=period(),
    ).scan()

    assert [item.session.session_id for item in result.resolved_sessions] == ["human"]
    assert result.loaded_session_count == 1
    assert result.warnings == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/integration/test_scan_service.py::test_scan_excludes_the_sessions_iiwi_itself_created -q`
Expected: FAIL — three sessions are resolved, not one.

`ScanService.__init__` is keyword-only and takes `source`, `period`, `resolver`, plus optional `progress`, `excluded_repository_ids`, and `runner` (`src/iiwi/services/scan.py:91`), so the construction above is correct as written.

- [ ] **Step 3: Write the implementation**

In `src/iiwi/services/scan.py`, add to the imports:

```python
from iiwi.sessions.filtering import filter_session_to_period, is_iiwi_authored
```

(replacing the existing single-name import of `filter_session_to_period`).

In the per-session loop, immediately before the existing `filtered = filter_session_to_period(...)` line, insert:

```python
                # iiwi's own opencode runs are machinery, not the user's work.
                if is_iiwi_authored(session):
                    continue
```

Place it before the `filter_session_to_period` call and after the warning appends, so a session iiwi wrote contributes no warnings either.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/integration/test_scan_service.py -q`
Expected: PASS, including every pre-existing scan test.

- [ ] **Step 5: Document the behaviour**

In `docs/limitations.md`, under `## General`, add a bullet matching the surrounding style:

```markdown
- Sessions iiwi's own `opencode run` creates are excluded from every scan, so
  generating a report never adds to the activity the next one reports on.
```

In `docs/evidence-first-quick-review.md`, under `## Start the review`, add a sentence at the end of the section:

```markdown
Quick Review never sees the sessions iiwi's own `opencode run` leaves behind;
they are dropped during the scan, so generating a report does not add to the
activity the next report describes.
```

In `CHANGELOG.md`, add a bullet to the existing `## Unreleased` list:

```markdown
- Iiwi no longer reports on itself. Every `opencode run` iiwi invokes leaves a
  session in the OpenCode store, and the next scan was picking those up as
  work — fifteen of them in one real 30-day window. They are dropped during the
  scan now, so they are absent from Quick Review, Browse Activity, the
  session-based report, and every session count.
```

- [ ] **Step 6: Run the full gate**

```bash
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run --extra dev pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/services/scan.py tests/integration/test_scan_service.py docs/ CHANGELOG.md
git commit -m "fix: stop reporting iiwi's own opencode runs as work"
```

---

### Task 4: Proportional title support threshold

**Files:**
- Modify: `src/iiwi/services/outcomes.py` (`_supported_title`)
- Test: `tests/unit/services/test_outcomes.py`

**Interfaces:**
- Consumes: `_supported_title`, `_corpus`, and the `SessionEvidence` fixtures already in the test module.
- Produces: module constant `_TITLE_SUPPORT_RATIO: float = 0.8`. `_supported_title` keeps its signature `(proposed: str, selected: list[SessionEvidence], local_texts_by_session: dict[str, list[str]]) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/test_outcomes.py`:

```python
from iiwi.models.evidence import EvidenceItem
from iiwi.services.outcomes import _fallback_title, _supported_title


def _corpus_evidence(words: list[str]) -> SessionEvidence:
    return SessionEvidence(
        session_id="ses-corpus",
        repository_id="repo-a",
        title="Session corpus",
        goals=[EvidenceItem(text=" ".join(words), source_activity_ids=["a1"])],
    )


def _support(proposed: str, corpus_words: list[str]) -> str:
    evidence = _corpus_evidence(corpus_words)
    return _supported_title(proposed, [evidence], {})


def test_a_fully_supported_title_is_kept() -> None:
    assert _support("render viewport flicker", ["render", "viewport", "flicker"]) == (
        "render viewport flicker"
    )


def test_exactly_eighty_percent_support_is_kept() -> None:
    # four of five words longer than two characters are in the corpus
    proposed = "render viewport flicker margin polish"
    assert _support(proposed, ["render", "viewport", "flicker", "margin"]) == proposed


def test_below_eighty_percent_support_falls_back() -> None:
    # three of four words: 75%
    proposed = "render viewport flicker polish"
    assert _support(proposed, ["render", "viewport", "flicker"]) != proposed


def test_three_word_titles_still_need_every_word() -> None:
    # two of three is 66.7%
    proposed = "render viewport polish"
    assert _support(proposed, ["render", "viewport"]) != proposed


def test_two_word_titles_still_need_every_word() -> None:
    proposed = "render polish"
    assert _support(proposed, ["render"]) != proposed


def test_a_title_with_no_long_words_falls_back() -> None:
    assert _support("a an of", ["render"]) != "a an of"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/services/test_outcomes.py -q -k "support"`
Expected: FAIL on `test_exactly_eighty_percent_support_is_kept` — the all-or-nothing gate rejects it. The other five already pass and are regression guards.

- [ ] **Step 3: Write the implementation**

In `src/iiwi/services/outcomes.py`, add beside the other module constants:

```python
# Measured, not guessed: across one live synthesis the all-or-nothing gate
# refused five of ten proposals at 84.6%, 66.7%, 85.7%, 90.9% and 90.0% word
# support, and the words that missed were "improvements", "wave", "polish" and
# "housekeeping" — summarizing vocabulary, not claims about the work. Status and
# impact keep their own, stricter gates.
_TITLE_SUPPORT_RATIO = 0.8
```

Replace the body of `_supported_title`:

```python
def _supported_title(
    proposed: str,
    selected: list[SessionEvidence],
    local_texts_by_session: dict[str, list[str]],
) -> str:
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", proposed.casefold())
        if len(word) > 2
    ]
    if not words:
        return _fallback_title(selected)
    corpus = _corpus(selected, local_texts_by_session)
    supported = sum(1 for word in words if word in corpus)
    if supported / len(words) >= _TITLE_SUPPORT_RATIO:
        return proposed
    return _fallback_title(selected)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/services/test_outcomes.py -q`
Expected: PASS. Any pre-existing test that asserted a partially-supported title falls back now fails — read it, and if its title clears 80% the correct fix is to update that test's expectation, not to change the threshold.

- [ ] **Step 5: Run the full gate**

```bash
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run --extra dev pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/services/outcomes.py tests/unit/services/test_outcomes.py
git commit -m "fix: accept a title the evidence substantively supports"
```

---

### Task 5: Readable fallback titles for grouped outcomes

**Files:**
- Modify: `src/iiwi/services/outcomes.py` (`_fallback_title`)
- Modify: `CHANGELOG.md` (the existing `## Unreleased` section)
- Test: `tests/unit/services/test_outcomes.py`

**Interfaces:**
- Consumes: `_fallback_title` and `SessionEvidence`; `EvidenceItem` imported in Task 4.
- Produces: `_fallback_title(selected: list[SessionEvidence]) -> str` keeps its signature. New private helper `_evidence_weight(evidence: SessionEvidence) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/services/test_outcomes.py`:

```python
def _weighted(
    session_id: str,
    title: str,
    *,
    files: int = 0,
    goals: int = 0,
    repository_id: str = "repo-a",
) -> SessionEvidence:
    return SessionEvidence(
        session_id=session_id,
        repository_id=repository_id,
        title=title,
        files_changed=[
            EvidenceItem(text=f"src/module_{index}.py", source_activity_ids=["a1"])
            for index in range(files)
        ],
        goals=[
            EvidenceItem(text=f"goal {index}", source_activity_ids=["a1"])
            for index in range(goals)
        ],
    )


def test_one_session_keeps_its_own_title() -> None:
    assert _fallback_title([_weighted("ses-a", "Fix the viewport")]) == "Fix the viewport"


def test_a_group_sharing_one_repository_names_its_anchor_and_counts_the_rest() -> None:
    group = [
        _weighted("ses-a", "Small follow-up", goals=1),
        _weighted("ses-b", "The real work", goals=8),
        _weighted("ses-c", "Another follow-up", goals=1),
    ]

    assert _fallback_title(group) == "The real work and 2 more sessions"


def test_a_group_of_two_uses_the_singular() -> None:
    group = [
        _weighted("ses-a", "The real work", goals=4),
        _weighted("ses-b", "Follow-up", goals=1),
    ]

    assert _fallback_title(group) == "The real work and 1 more session"


def test_the_anchor_is_the_richest_session_not_the_widest_one() -> None:
    group = [
        _weighted("ses-sweep", "Rename sweep", files=50),
        _weighted("ses-feature", "The feature", files=3, goals=8),
    ]

    # 50 evidence items versus 11, so a ref count would pick the sweep
    assert _fallback_title(group).startswith("Rename sweep")

    richer = [
        _weighted("ses-sweep", "Rename sweep", files=4),
        _weighted("ses-feature", "The feature", files=3, goals=8),
    ]
    assert _fallback_title(richer).startswith("The feature")


def test_ties_take_the_first_session_in_the_group() -> None:
    group = [
        _weighted("ses-a", "First", goals=3),
        _weighted("ses-b", "Second", goals=3),
    ]

    assert _fallback_title(group) == "First and 1 more session"


def test_a_titleless_anchor_falls_back_to_its_session_id() -> None:
    group = [
        _weighted("ses-a", "", goals=5),
        _weighted("ses-b", "Other", goals=1),
    ]

    assert _fallback_title(group) == "ses-a and 1 more session"


def test_a_cross_repository_group_still_names_its_repositories() -> None:
    group = [
        _weighted("ses-a", "One", repository_id="repo-a"),
        _weighted("ses-b", "Two", repository_id="repo-b"),
    ]

    assert _fallback_title(group) == "repo-a / repo-b"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/services/test_outcomes.py -q -k "fallback or anchor or group or session"`
Expected: FAIL on the single-repository group tests — they currently render `Small follow-up / The real work / Another follow-up`. `test_one_session_keeps_its_own_title` and `test_a_cross_repository_group_still_names_its_repositories` already pass and pin the branches that must not change.

- [ ] **Step 3: Write the implementation**

In `src/iiwi/services/outcomes.py`, replace `_fallback_title` and add the helper above it:

```python
def _evidence_weight(evidence: SessionEvidence) -> int:
    """Count everything extraction found, as a proxy for how substantive a session is.

    Not the evidence-reference count: references are one per changed file, so a
    rename sweep across fifty files would outrank the feature work beside it.
    """

    return sum(
        len(collection)
        for collection in (
            evidence.goals,
            evidence.commands,
            evidence.files_changed,
            evidence.errors,
            evidence.outcomes,
        )
    )


def _fallback_title(selected: list[SessionEvidence]) -> str:
    if len(selected) == 1:
        return selected[0].title or selected[0].session_id
    repositories = sorted({item.repository_id for item in selected})
    if len(repositories) > 1:
        return " / ".join(repositories)
    anchor = max(selected, key=_evidence_weight)
    others = len(selected) - 1
    plural = "session" if others == 1 else "sessions"
    return f"{anchor.title or anchor.session_id} and {others} more {plural}"
```

`max` returns the first maximum it meets, which is the tie rule the design asks for.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/services/test_outcomes.py -q`
Expected: PASS. Any pre-existing test asserting a slash-joined multi-session title fails here; update its expected string to the new shape.

- [ ] **Step 5: Record the change**

In `CHANGELOG.md`, add two bullets to the existing `## Unreleased` list:

```markdown
- A grouped outcome's title reads as one line. When the model's proposed title
  is not supported by the evidence, the fallback used to join every session
  title in the group with slashes, so a group of eleven rendered as eleven
  clauses. It now names the session with the most extracted evidence and counts
  the rest: `The real work and 10 more sessions`.
- A proposed title survives when the evidence substantively supports it. The
  check required every word longer than two characters to appear in the
  evidence; across one real synthesis that refused five of ten proposals over
  words like `polish` and `housekeeping` while every substantive term matched.
  Eighty percent of the words now suffice. Status and impact keep their
  existing, stricter checks.
```

- [ ] **Step 6: Run the full gate**

```bash
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run --extra dev pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/services/outcomes.py tests/unit/services/test_outcomes.py CHANGELOG.md
git commit -m "fix: name a grouped outcome after its largest session"
```

---

### Task 6: Verify against the real store

**Files:** none modified. This task produces evidence, not code.

**Interfaces:**
- Consumes: everything Tasks 1-5 produced, plus a local OpenCode store with at least one week of sessions.

- [ ] **Step 1: Confirm the scan drops iiwi's own sessions**

```bash
uv run python -c "
from datetime import timedelta
from iiwi import cli
from iiwi.models.time_range import DateRange
from iiwi.sessions.filtering import is_iiwi_authored
s = cli._load_settings(); now = cli._now_in_timezone(s.report.timezone)
p = DateRange(since=now - timedelta(days=30), until=now)
scan = cli._build_scan_service(s, p, False, harness=cli.Harness.OPENCODE, sanitize=False).scan()
leaked = [r.session.title for r in scan.resolved_sessions if is_iiwi_authored(r.session)]
print('sessions:', len(scan.resolved_sessions), '| iiwi-authored still present:', len(leaked))
"
```

Expected: `iiwi-authored still present: 0`. Before this plan the same window held fifteen.

- [ ] **Step 2: Confirm grouped titles read as one line**

Run a real synthesis over a week and read the grouped outcome titles:

```bash
uv run python -c "
from datetime import timedelta
from iiwi import cli
from iiwi.models.time_range import DateRange
from iiwi.process import CommandRunner
from iiwi.services.outcomes import OutcomeSynthesisService
from iiwi.summarizers.opencode_run import OpenCodeRunner
s = cli._load_settings(); now = cli._now_in_timezone(s.report.timezone)
p = DateRange(since=now - timedelta(days=7), until=now)
scan = cli._build_scan_service(s, p, False, harness=cli.Harness.OPENCODE, sanitize=False).scan()
c = s.harnesses.opencode.cli
service = OutcomeSynthesisService(
    OpenCodeRunner(runner=CommandRunner(timeout_seconds=c.run_timeout_seconds),
                   executable=c.executable, model=c.model),
    max_evidence_bytes=s.report.quick_review_max_evidence_bytes,
)
for outcome in service.synthesize(scan).outcomes:
    if outcome.bucket.value != 'ungrouped':
        print(f'[{outcome.status.value}] {outcome.title}')
"
```

Expected: no title containing more than one ` / ` separator, and no title naming `Iiwi outcome synthesis`. This call invokes the local model and takes several minutes; if it exceeds a ten-minute shell timeout, run it in the background and read the output file.

- [ ] **Step 3: Record the result**

Paste both outputs into the pull request description under a `## Live verification` heading. Numbers from a real store are what justified the 0.8 threshold, and the same evidence is what shows it worked.

---

## Notes for the implementer

- Task 2's Step 2 is the one place a test is green before its implementation lands, and the step says how to prove it still has teeth. Every other test in this plan must be seen failing first.
- If Task 3 turns any pre-existing scan test red because its fixture titles happen to start with `Iiwi`, rename the fixture rather than loosening the predicate.
- Tasks 1-3 and Tasks 4-5 are independent. If one half needs to be abandoned, the other still ships.
