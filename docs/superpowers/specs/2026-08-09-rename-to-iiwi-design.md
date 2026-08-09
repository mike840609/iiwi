# Rename Agent Worklog to Iiwi — Design

**Status:** Approved · **Date:** 2026-08-09

Rename the project from `agent-worklog` to `iiwi` across the Python package, the
runtime identity, packaging, CI, documentation and assets. The naming rationale
is settled elsewhere; this document specifies what changes, in what order, and
how each step is verified.

## Name forms

| Context | Form |
|---|---|
| Distribution, CLI, URLs, application directories | `iiwi` |
| Python package, imports, coverage target | `iiwi` |
| Prose | `Iiwi` |
| Environment prefix | `IIWI_` |
| Error base class | `IiwiError` |

Pronounced `/ˈiː.wiː/` — "ee-wee". Both READMEs must state it on the first
content line; the name is not guessable from its spelling.

Version continues at **0.9.0**. The changelog history is real and the code is
the same maturity, so restarting the version would misrepresent it.

## What is deliberately not renamed

- `output_directory: Path("reports")` — describes the artifact, not the product.
- Harness identifiers `opencode`, `codex`, `claude_code`.
- `# Engineering Worklog`, the H1 inside `templates/worklog.md.j2`, and the
  generated filename `reports/worklog-<dates>.md`. These name the document the
  tool produces, which is still accurately a worklog. Only the product is being
  renamed. The template filename `worklog.md.j2` stays for the same reason.
- Historical records, listed under [Frozen records](#frozen-records).

## Rejected alternatives

**Eight commits split by file category.** Only two atomicity constraints exist:
the package move must ship with its import rewrite, and the three application
directory literals must change together. Everything else is independently safe,
so a finer split buys review granularity nobody will use — the diff is roughly
two thousand mechanical substitutions across a hundred and fifty files, and
bisecting a rename has no value. It costs seven extra full test runs and leaves
seven intermediate commits where the repository-wide sweep is non-zero.

**A clean break with no state migration.** `agent-worklog` 0.8.0 is live on PyPI
with ten releases and 1,007 downloads in the last month. That number is probably
dominated by mirrors, but it cannot be distinguished from real installs. The
costs are asymmetric: the migration is one eight-line function and three call
sites, deletable in one release, while being wrong means a user silently loses
their settings and history with no error and no warning.

**Freezing only `docs/plans/`.** That draws the boundary at a directory rather
than at what the documents are. Thirteen files directly under `docs/` are dated
design records of exactly the same kind as the plans.

## PyPI name claim

Nothing in this repository needs PyPI credentials. The package move, the import
rewrite, `uv build`, `uv run iiwi` and the whole test suite touch PyPI not at
all. `update.py` issues an unauthenticated GET that will return 404 until 0.9.0
ships; `urlopen` raises `HTTPError`, a subclass of `OSError`, which the existing
error path already handles.

Claiming the name is a separate question, and PyPI offers no cheap way to do it.
A pending publisher does not reserve anything — PyPI creates neither project nor
name until something is actually published, and another upload of the same name
invalidates the pending publisher outright. So the only claim mechanism is
uploading a real distribution.

This repository publishes through Trusted Publishing: `release.yml` grants
`id-token: write` and calls `pypa/gh-action-pypi-publish` with no password. No
API token exists anywhere in the release path. A placeholder upload therefore
means minting an account-scoped token — project-scoped is impossible before the
project exists — purely to hold a name.

**Decision: skip the placeholder.** `iiwi` is an obscure Hawaiian bird name, not
a word anyone is racing for, and the exposure lasts only from the first commit
until 0.9.0 publishes. If the branch is going to sit for a month or more before
release, upload `0.8.1.dev0` with a temporary token and revoke it afterwards.
Verified free (HTTP 404) on 2026-08-09; re-verify before releasing either way.

npm is also free but not claimed. A Python tool does not need it.

## Required before the first release

Trusted publishing has no project to authenticate against until `iiwi` exists on
PyPI, so a **pending publisher** must be registered or the publish job in
`release.yml` fails outright:

| Field | Value |
|---|---|
| PyPI project name | `iiwi` |
| Repository | `mike840609/iiwi` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Register it after the GitHub repository is renamed and before tagging 0.9.0. The
OIDC claim carries whatever the repository is called at the moment the workflow
runs, and GitHub's redirect of the old URL does not rewrite that claim — a
pending publisher pointing at `mike840609/agent-worklog` would not match.

## Commit 1 — Code

These four changes ship together. Splitting them leaves either a tree that
cannot import, or user state silently divided across two application
directories.

### Package move and import rewrite

```bash
git mv src/agent_worklog src/iiwi
rg -l '\bagent_worklog\b' src tests | xargs perl -pi -e 's/\bagent_worklog\b/iiwi/g'
```

`sed -i` is not usable here. The plan this design supersedes used GNU syntax
throughout; this is macOS, where BSD `sed -i` requires a backup-suffix argument
and fails otherwise. Every substitution in this document uses `perl -pi -e`.

File contents are otherwise untouched, so git still detects the renames rather
than recording delete-plus-add.

### Runtime identity

| File | Line | Change |
|---|---|---|
| `config.py` | 85 | `env_prefix="IIWI_"` |
| `config_store.py` | 18, 19 | `ENV_PREFIX`, `CONFIG_FILE_VARIABLE` |
| `config_store.py` | 32 | `user_config_dir("iiwi")` |
| `config_store.py` | 133 | docstring naming the config-file variable |
| `history.py` | 17, 42 | `HISTORY_FILE_VARIABLE`, `user_data_dir("iiwi")` |
| `state.py` | 23, 32 | `STATE_FILE_VARIABLE`, `user_data_dir("iiwi")` |
| `cli.py` | 171 | f-string `IIWI_HARNESSES__{harness.name}__ENABLED` |
| `cli_actions.py` | 221, 226 | `IIWI_REPORT__EXCLUDE_REPOSITORIES` |
| `update.py` | 20, 22, 71 | `LATEST_URL`, `UPGRADE_COMMAND`, User-Agent |

Every documented environment variable derives from the prefix, so this changes
the whole user-facing configuration surface — for instance
`AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` becomes
`IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY`.

`update.py` deserves particular care. Left pointing at the old project, `iiwi`
would poll an abandoned PyPI entry forever and report wrong versions, with no
visible symptom.

```python
LATEST_URL = "https://pypi.org/pypi/iiwi/json"
UPGRADE_COMMAND = "pipx upgrade iiwi"
headers={"User-Agent": f"iiwi/{current_version()} (version check)"}
```

### Legacy state adoption

New module `src/iiwi/paths.py`:

```python
def adopt_legacy(new_path: Path, legacy_path: Path) -> Path:
    """Take over state left behind by the pre-rename name.

    Delete this and its three call sites one release after 0.9.0.
    """

    if not new_path.exists() and legacy_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        legacy_path.rename(new_path)
    return new_path
```

The three path resolvers share one shape: an environment override first, then a
`platformdirs` default. Only the default branch is wrapped, so the override
path — which every existing test uses — is untouched.

| Call site | Wraps |
|---|---|
| `config_store.py:32` | `user_config_dir` / `config.env` — user settings |
| `history.py:42` | `user_data_dir` / `history.jsonl` — report history |
| `state.py:32` | `user_data_dir` / `state.json` — session-selection memory |

Both paths sit under the same user directory, so `rename` stays within one
filesystem. The `not new_path.exists()` guard means an existing new file always
wins, and makes the function idempotent. Two concurrent processes racing on the
same file is possible and harmless: the loser's `rename` either succeeds
identically or fails on an already-moved source, and the data is the same
either way.

### Error class

```bash
rg -l '\bAgentWorklogError\b' src tests | xargs perl -pi -e 's/\bAgentWorklogError\b/IiwiError/g'
```

Fourteen occurrences: `errors.py` (5), `interactive/controller.py` (7),
`update.py` (2).

### User-facing strings

| File | Line | String |
|---|---|---|
| `interactive/render.py` | 384, 400 | main-menu title, both the wide and narrow-terminal branches |
| `logging.py` | 143, 189 | `Table(title=...)` for settings and scan |
| `services/report.py` | 194 | report title passed to the summarizer — reaches generated output |
| `interactive/cli_actions.py` | 239 | `"Undo with: iiwi config unset report.exclude_repositories"` |
| `summarizers/opencode_run.py` | 183 | temp-directory prefix |
| `security/secure_files.py` | 19 | temp-directory prefix |
| `interactive/__init__.py`, `interactive/models.py`, `interactive/render.py`, `config.py` | 1, 1, 1, 82 | module and class docstrings |

The menu banner needs no re-padding. `render.py:386` computes padding from
`console.size.width` and the rule is `_RULE_CHAR * console.size.width`, so a
shorter title cannot misalign either.

The subtitle `"Turn coding-agent sessions into engineering reports"` contains no
product name and stays.

### Verification

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check . && uv run pyright
rg -i 'agent[-_ ]?worklog' src tests    # only the paths.py/test_paths.py legacy-adoption lines
```

`refactor: rename the package and runtime identity to iiwi`

## Commit 2 — Packaging, CI, documentation

### Packaging and CI

```toml
name = "iiwi"
description = "Agent Session Intelligence for engineering work"

[project.scripts]
iiwi = "iiwi.cli:app"
```

- `.github/workflows/ci.yml:38` and `release.yml:36` — `--cov=iiwi`. Left alone,
  the coverage gate reports 0% against a package name that no longer exists and
  fails the build.
- `.codex/environments/environment.toml` — display name and the same coverage flag.
- `uv lock` — the lockfile records the root package name.

Artifact check:

```bash
uv build
python -c "import zipfile,glob; print(sorted({n.split('/')[0] for n in zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist()}))"
uv run iiwi --version && uv run iiwi doctor
```

### Documentation

Living documents only — `README.md` (46), `README.zh-TW.md` (41),
`SECURITY.md` (3), and seven files under `docs/`:

```bash
rg -l -i 'agent[-_ ]?worklog' README.md README.zh-TW.md SECURITY.md \
  docs/configuration.md docs/guides.md docs/privacy.md docs/releasing.md \
  docs/cli-reference.md docs/limitations.md docs/usage-statistics.md \
| xargs perl -pi -e 's/agent-worklog/iiwi/g; s/agent_worklog/iiwi/g; s/Agent Worklog/Iiwi/g; s/AGENT_WORKLOG_/IIWI_/g'
```

Then, by hand:

- Badge and link URLs in both READMEs (lines 3–9) point at
  `github.com/mike840609/agent-worklog` and `deepwiki.com/mike840609/agent-worklog`.
  Repoint to `mike840609/iiwi`. GitHub redirects once the repository is renamed,
  but the badges should read correctly regardless.
- Add under the H1 of both READMEs:

  ```
  Iiwi · /ˈiː.wiː/ "ee-wee" — Agent Session Intelligence for engineering work

  Probe coding-agent sessions. Surface the work that matters.
  ```

  Plus one sentence noting the ʻiʻiwi is a scarlet Hawaiian honeycreeper and
  that the project uses an anglicised pronunciation. It is a real word from a
  living language and one sentence covers it.
- `docs/releasing.md` describes the release procedure by name. Read it end to
  end rather than trusting the substitution.

### Documentation tests

`tests/unit/test_documentation.py` asserts exact literals against the shipped
documentation and is the safety net for the whole rename. Update its assertions
one at a time, not by substitution — a blind rewrite would make the tests agree
with whatever the docs happen to say.

Twenty occurrences across lines 7–10, 51, 81–83, 98, 109, 121–122, 132, 135,
137, 162, 168–169, 185, 201, 210, 224.

Add one regression test. The pronunciation line is the mitigation for the name's
one real weakness and should not silently disappear:

```python
def test_readmes_state_the_pronunciation() -> None:
    for path in ("README.md", "README.zh-TW.md"):
        assert "ee-wee" in Path(path).read_text(encoding="utf-8")
```

`build: rename the distribution, CI and documentation to iiwi`

## Commit 3 — Assets and changelog

```bash
git mv docs/assets/agent-worklog-overview.png docs/assets/iiwi-overview.png
rg -l 'agent-worklog-overview' README.md README.zh-TW.md docs \
| xargs perl -pi -e 's/agent-worklog-overview/iiwi-overview/g'
```

Both READMEs load assets through
`raw.githubusercontent.com/mike840609/agent-worklog/refs/heads/main/...`; the
owner path needs repointing too.

`docs/assets/architecture.mmd` feeds `architecture.svg` through
`render-architecture.sh`. If the diagram labels the CLI, edit the `.mmd` and
re-run the script — do not hand-edit the SVG.

New changelog entry; existing entries stay as written.

```markdown
## [0.9.0]

### Changed

- Renamed the project from Agent Worklog to Iiwi. The command is now `iiwi`,
  the distribution is `iiwi` on PyPI, environment variables use the `IIWI_`
  prefix, and settings, history and session-selection state move to the `iiwi`
  application directories. State left by the previous name is adopted
  automatically on first run.
```

`chore: rename assets and record the rename in the changelog`

## Frozen records

These keep the old name. Rewriting dated records would falsify them, and the
review surface would triple for no reader benefit.

- `docs/plans/**` — 895 occurrences across 15 dated files
- Thirteen design records directly under `docs/` — 190 occurrences:
  `mvp-design.md`, `p0-interactive-ux-implementation-plan.md`,
  `p0-interactive-ux-design.md`, `interactive-menu-design.md`,
  `opencode-sanitize-default-design.md`, `opencode-run-report-engine-design.md`,
  `v0.4.0-release-design.md`, `claude-code-adapter-design.md`,
  `codex-adapter-design.md`, `main-menu-version-design.md`,
  `cli-progress-feedback-design.md`, `2026-08-08-session-density-design.md`,
  `report-scan-detail-levels-design.md`
- Existing `CHANGELOG.md` entries — 13 occurrences

## Verification

After every commit:

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Final sweep. The first returns only the seven known legacy-adoption references
in `paths.py`/`test_paths.py`; the second must return nothing:

```bash
rg -i --hidden -g '!.git/**' -g '!docs/**' -g '!CHANGELOG.md' -g '!uv.lock' \
  'agent[-_ ]?worklog' .

rg -i 'agent[-_ ]?worklog' docs/configuration.md docs/guides.md docs/privacy.md \
  docs/releasing.md docs/cli-reference.md docs/limitations.md docs/usage-statistics.md
```

The first excludes `docs/` wholesale and the second names the seven living
documents. Two plain commands beat one clever glob, and the explicit list is
also the definition of which documents are living.

`--hidden` is required: `rg` skips dotted directories by default, which would
leave `.github/workflows/` and `.codex/` unswept — the two places a leftover
`--cov=agent_worklog` could hide. `-g '!.git/**'` then keeps the reflog and
worktree metadata, which carries the old name permanently and correctly, out of
the results.

## Testing

`adopt_legacy` is the only new behaviour, so it is the only thing needing new
tests beyond the documentation regression above.

| Scenario | Expected |
|---|---|
| Legacy exists, new absent | File moves; contents preserved; legacy gone |
| Both exist | New file untouched; legacy left alone |
| Neither exists | No move, no directory created |
| Called twice | Second call is a no-op |
| Each of the three call sites, with `user_data_dir` / `user_config_dir` monkeypatched | Resolves to the `iiwi` directory and adopts the `agent-worklog` one |
| Environment override set | Override wins; no filesystem move attempted |

The last row matters most. Every existing test of these three resolvers uses the
override, so a migration that fired before the override check would corrupt the
whole suite in a way that looks like an unrelated failure.

## Out-of-repository work

Do all of this after the pull request merges. Renaming the repository mid-flight
retargets the open pull request's base and disturbs the branch.

1. Settings → Repository name → `iiwi`. GitHub redirects the old URLs, including
   clone and raw asset paths, so nothing breaks immediately.
2. `git remote set-url origin https://github.com/mike840609/iiwi`
3. Confirm the CI, Release and DeepWiki badges render. DeepWiki may need
   re-indexing under the new path.
4. Update the repository description and topics to the new positioning.
5. Register the PyPI pending publisher for `iiwi` against the now-renamed
   repository, per [Required before the first release](#required-before-the-first-release).
6. Tag and release 0.9.0. This upload is what claims the name on PyPI.
7. Publish a final `agent-worklog` 0.8.1 whose description says only that the
   project continues as `iiwi`, with the install command. **Do not yank the
   earlier releases** — yanking breaks pinned installs for anyone who already
   has them and gains nothing.

## Risks

| Risk | Mitigation |
|---|---|
| A partial application-directory rename splits user state silently | All three literals and the adoption helper land in Commit 1; `rg 'user_(config\|data)_dir\("' src` confirms |
| `update.py` left pointing at the old PyPI project — wrong versions forever, no symptom | Explicit step in Commit 1; verify with `uv run iiwi update` |
| `--cov=agent_worklog` left in CI reports 0% and trips the 80% gate | Commit 2; CI catches it on first push |
| Blind substitution rewrites the 28 frozen records | Every substitution names its files explicitly; none globs `docs/` |
| `sed -i` from a GNU-flavoured runbook fails on macOS | Every command here uses `perl -pi -e` |
| Migration fires ahead of the environment override and corrupts the test suite | Only the `platformdirs` branch is wrapped; a dedicated test covers the override |
| `iiwi` claimed on PyPI by someone else mid-rename | Accepted. Exposure ends when 0.9.0 publishes; upload a placeholder only if the branch will sit for a month or more |
| `release.yml` publish job fails because trusted publishing has no project to authenticate against | Pending publisher registered after the repository rename, before tagging |
