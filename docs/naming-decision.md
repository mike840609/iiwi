# Naming Decision: Agent Worklog → Iiwi

**Status:** Decided · **Date:** 2026-08-09 · **Implementation:** [`docs/plans/2026-08-09-rename-to-iiwi.md`](plans/2026-08-09-rename-to-iiwi.md)

**Outcome:** The project is renamed to **Iiwi**, pronounced `/ˈiː.wiː/` — "ee-wee".

All collision data below was verified on 2026-08-09 against the PyPI JSON API, the npm registry and the GitHub search API. Re-verify before acting on it; short names move fast.

---

## 1. What is being named

A CLI / OSS tool for software engineers that reads coding-agent sessions (OpenCode, Claude Code, Codex), identifies the real engineering work inside them, and produces readable worklogs and reports.

Not a session exporter or chat-history viewer. Closer to **Agent Session Intelligence for engineering work**:

- probe / inspect sessions
- identify meaningful engineering work, filter noise
- extract evidence, reconstruct what was actually done
- summarize across repositories and sessions
- generate worklogs / reports

### A correction to the original framing

The pre-existing tagline was *"Probe coding-agent sessions."* — and Iiwi's metaphor (a curved bill probing flowers for nectar) was built on **probing**.

Reading the actual codebase, the product's distinguishing action is not probing but **separating signal from noise at volume**:

- `fcb76d3 feat: deselect noise sessions by default and label the reason`
- Review Sessions weights each repository by its share of the period (`71% / 24% / 5%`)
- Git worktrees collapse into one repository entry; subagent sessions are kept alongside
- The pipeline is redact → group → summarize

Probing extracts a single point. This tool processes a flow. That distinction drove the candidate generation below, and it is worth preserving if the name is ever revisited.

---

## 2. Naming criteria

1. **Short** — 4–7 letters, 1–2 syllables, comfortable as a CLI command
2. **Pronounceable** — an international developer should roughly know how to say it
3. **Memorable** — distinct shape, strong imagery, mascot potential
4. **Strong metaphor** — need not contain *agent* / *session* / *report* / *log*, but should support one: searching, digging, sifting, observing, collecting, extracting signal from volume
5. **No obvious product collision** — GitHub, PyPI, npm, developer tools, AI tools, major software, Steam games, well-known companies. Not necessarily globally unique, but must not be drowned out on search
6. Real word preferred — animal / plant / natural object is ideal. Not an invented startup name

### Philosophy

A name is not disqualified for failing to describe the product at first glance. Docker, Kubernetes, Ansible and Mole do not either. What matters is whether **name + tagline + README description** together build the product's identity.

Rejected as too descriptive / utility-flavoured: `AgentSessionReporter`, `SessionReporter`, `AgentWorklog`, `RepoReport`, `SessionSummary`, `Session Intelligence Reporter`.

### Rename constraint

No existing users require backward compatibility. A clean rename is available — no alias, no compatibility command, no deprecated package, no migration layer.

---

## 3. Round 0 — previously discussed

| Name | Verdict |
|---|---|
| **SessionBrief** | Clear but too descriptive; reads as a feature name, weak product identity |
| **RepoRecap** | Understandable, but scope skews to *repository*. The product analyses agent sessions → engineering work; repository is only one grouping dimension |
| **Loom** | Good metaphor (weaving scattered threads into coherent work) but software/company collision too strong |
| **Sift** | Metaphor excellent — sift noisy sessions for meaningful work — but too common, high ecosystem collision |
| **Folio** | Portfolio metaphor decent, but positions toward *displaying results*; does not express inspection or intelligence |
| **Wren** | Short, animal, brandable — but metaphor not strongly connected to the product |
| **Wovlet** | Unique, but reads as an invented startup name; violates the real-word preference |
| **Guar**, **Iora**, **Iiwi** | Earlier strong directions; converged on Iiwi as the working name |

---

## 4. Round 1 — exploration at 5–7 characters

Generated against the *separation* metaphor identified in §1.

### Eliminated, with evidence

| Candidate | Evidence |
|---|---|
| **Winnow** | `winnow-rs/winnow` 937★ — the actively maintained successor to `nom`, a core Rust parser library. Updated 2026-08-08 |
| **Vireo** | `twitter/vireo` 957★ video processing; `ni/VireoSDK` LabVIEW runtime |
| **Morel** | `hydromatic/morel` 378★ functional query language (Julian Hyde). Updated 2026-08-09 |
| **Riffle** | Five separate dev projects: `kwonalbert/riffle` 225★, `Factual/riffle` 138★, `zuston/riffle` 70★, `sharkdp/riffle` 46★ (author of `bat`/`fd`/`hyperfine` — same CLI space), `cwensel/riffle` 39★ |
| **Shrike** | `Shrike-Lab/HomeLab-PDU-V1` 811★ and `vicharak-in/shrike` 493★, both created 2025 and growing |
| **Coati** | Coati Software built **Sourcetrail**, a source-code exploration tool — direct domain adjacency |
| **Curlew** | PyPI `curlew` 1.1 updated 2026-04-16 (active). Also begins with `curl`, misread in a CLI context |
| **Pipit** | npm `pipit` 2.0.1 (2026-02-06) is an active *"universal logger"* — collides with the worklog domain itself |
| **Cairn** | Visually and phonetically too close to Cairo / cairo-lang |

### Finalists

| | Sluice | Avocet | Hoopoe |
|---|---|---|---|
| Pronunciation | `sloos`, unambiguous | `AV-uh-set` | `HOO-poo` — carries a snicker risk |
| Metaphor | A sluice box runs the whole stream through; the heavy valuable material settles into the riffles while worthless bulk washes away | Sweeps an upcurved bill side to side through murky water, filtering prey it cannot see | Probes soil with a long bill for hidden grubs |
| PyPI | `0.3.1`, 2015, zfs tool, Bitbucket homepage — dead | `1.0.2`, 2024-09-01 — occupied | `0.0.12`, 2020-12-29 — dead |
| npm | `0.0.2`, 2013 — dead | **free** | **free** |
| GitHub | `sebastianruder/sluice-networks` 155★ (2017 paper), `sagebind/sluice` 103★ | effectively none | all ≤10★ |
| Other | none | **SLB Avocet** enterprise platform, ships an "Avocet SDK" | Hoopoe Technology (AI consultancy) |
| Steam | none | none | none |

**Round 1 recommendation was Sluice** — best metaphor fit, trivially pronounceable, types well. Superseded in Round 2.

---

## 5. Round 2 — the ≤4 character constraint

A hard limit of four characters was then imposed. This eliminated all three Round 1 finalists and materially changed the trade-off.

### Eliminated, with evidence

| Candidate | Evidence |
|---|---|
| **sift** | PyPI `sift` 6.0.0, 2025-05-05 — **Sift Science's official API bindings**, actively maintained |
| **riff** | PyPI `riff` 0.2, **2026-07-04** — *"Run ruff, but only fail on modified lines"*. Same CLI ecosystem, claimed weeks ago |
| **crux** | PyPI `crux` 1.4, 2025-07-30 — Crux Informatics API client |
| **pith** | `mlc-ai/pith-train` 327★, created 2026-03, updated 2026-08-09 — growing AI training system |
| **ibis** | `ibis-project/ibis`, a major Python dataframe library — fatal for a Python tool |
| **tui** | TUI means *terminal user interface*; this project ships one. Self-collision. Also TUI Group |
| **comb** | npm `comb` 2.0.0 (2021) active; Honeycomb.io adjacent in observability |
| **mole** | `tw93/Mole` **62,710★**, created 2025-09-23, updated 2026-08-09 — and it is a **terminal CLI**. The original style reference is gone |
| **lode**, **knot**, **awl** | Homophones of *load*, *not*, *all* — harmful for a command name |
| **adze**, **smew** | Spelling or pronunciation not guessable |
| **bat**, **dig**, **pry**, **pip** | Existing well-known CLIs |
| **kea**, **koa**, **weka**, **wren**, **lark**, **rook**, **kudu**, **lynx** | Existing well-known OSS projects (`lynx` especially bad — a terminal browser) |

### The deciding insight

Every ≤4 candidate that beat Iiwi on pronunciation was absorbed by a **near neighbour** — a far more common word one character away:

| | Namespace | Near neighbour |
|---|---|---|
| **`tody`** | PyPI **free**; npm 1.0.2 (2019, empty stub); GitHub exact none (`TodyNet` 87★, `tody.chat` 13★) | **"today"** — search substitutes it; editor spellcheck rewrites it |
| **`weir`** | PyPI 0.4.0 (2015, ZFS); npm 0.0.5 (2019); GitHub `inconvergent/weir` 638★ **archived** | **"weird"** — heavy noise at 1886★ / 1705★ / 1598★ |
| **`adit`** | PyPI 0.1.3 (2020-07-24); GitHub exact none | **"Aditya" / "Adit"** — common given name, dilutes every search |
| **`iiwi`** | PyPI **free**; npm **free**; GitHub all ≤3★ | **none** — `ii` is essentially unused as an English word opening |

The shorter the name, the less character-space remains to disambiguate it, so **"has no near neighbour" becomes more valuable than "is easy to pronounce"**. At six characters you can have both — an ordinary English word solves pronunciation for free. At four you cannot, and Iiwi is the only candidate scoring full marks on namespace.

This is why the Round 1 recommendation (switch to Sluice) and the Round 2 recommendation (keep Iiwi) differ. The constraint changed, so the trade-off changed.

---

## 6. Decision: Iiwi

The ʻiʻiwi is a scarlet Hawaiian honeycreeper whose long curved bill probes deep into flowers for nectar others cannot reach.

**Why it holds:**

- Only ≤4 candidate free on **PyPI, npm and GitHub simultaneously** — the hardest property to obtain at this length
- No near neighbour: search returns the bird, never a correction
- Visually distinctive; the unusual double-i becomes an asset once learned, as with `nginx`, `tmux`, `jq`
- Strong mascot and logo potential
- CLI commands read cleanly
- Lets meaning accrue to the brand instead of stuffing function into the name

**Known weaknesses, accepted:**

- **Pronunciation is not guessable.** The Hawaiian original is roughly "ee-EE-vee". The project adopts the anglicised **"ee-wee"** and must state it in the first content line of both READMEs. This is standard OSS practice (nginx → "engine-x"). Without it the name fails in conversation.
- **Typing** `i-i-w-i` repeats the same finger three times.
- **At 16px favicon size** a thin curved bill is hard to read; the logo should lean on the scarlet body and silhouette rather than bill detail.

**Runner-up:** `tody` — free on PyPI, immediately pronounceable, and the strongest mascot (a tiny round Caribbean bird, brilliant green with a crimson throat, which reads better than Iiwi at favicon size). Rejected solely because "today" permanently absorbs it in search and spellcheck. If the pronunciation problem ever proves more costly in practice than expected, this is the name to reconsider.

---

## 7. Brand surface

```
Iiwi · /ˈiː.wiː/ "ee-wee" — Agent Session Intelligence for engineering work

Probe coding-agent sessions. Surface the work that matters.
```

```bash
iiwi doctor
iiwi scan
iiwi inspect <session-id>
iiwi report
```

Name forms used throughout the rename:

| Context | Form |
|---|---|
| Distribution, CLI, URLs, application directories | `iiwi` |
| Python package, imports, coverage target | `iiwi` |
| Prose | `Iiwi` |
| Environment prefix | `IIWI_` |
| Error class | `IiwiError` |

---

## 8. Open items

- **Claim `iiwi` on PyPI before starting the rename.** PyPI has no reservation mechanism — the name is claimed by the first upload. Verified free 2026-08-09. `mole` went from unused to a 62.7k★ CLI in eleven months; do not assume the name will wait.
- `iiwi` on npm is also free. Not required for a Python tool; cheap insurance for the brand.
- Decide whether the anglicised pronunciation warrants a one-line acknowledgement of the Hawaiian origin in the README. Recommended — it is a real word from a living language, and one sentence covers it.
