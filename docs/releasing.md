# Releasing Iiwi

Iiwi publishes wheels and source distributions to PyPI through GitHub Actions and PyPI Trusted Publishing. No long-lived PyPI API token is stored in GitHub.

The repository's default and release branch is `main`.

## One-time PyPI setup

Create a Pending Trusted Publisher on PyPI with these exact values:

| Field | Value |
|---|---|
| PyPI project name | `iiwi` |
| GitHub owner | `mike840609` |
| Repository | `iiwi` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Then create a GitHub repository environment named `pypi` under **Settings → Environments**. Adding required reviewers is recommended so production releases require explicit approval.

## Verify a release without publishing

Run the `Release` workflow manually from GitHub Actions. A manual run builds and validates the distributions, but the `publish` and `release` jobs are skipped.

The build job runs:

```bash
uv sync --locked --extra dev
uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
uv tool run twine check dist/*
```

## Publish a version

1. Update `[project].version` in `pyproject.toml` **and `__version__` in `src/iiwi/__init__.py`**. Both hold the version; `tests/unit/test_version.py` fails when they disagree.
2. Regenerate and commit `uv.lock` with `uv lock`.
3. Merge the version change into `main`.
4. Create an annotated tag that exactly matches the package version.
5. Push the tag.

For version `0.1.0`:

```bash
git checkout main
git pull --ff-only
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

The workflow verifies that `v0.1.0` matches `version = "0.1.0"`, builds the package, publishes it through OIDC, and then creates a GitHub Release containing the same distributions. PyPI publication and GitHub Release creation run as separate sequential jobs.

PyPI versions are immutable. A corrected release must use a new version such as `0.1.1`; an existing file or version cannot be overwritten.

## Recover after PyPI succeeds

If the `publish` job succeeds but the later `release` job fails, diagnose the failure and confirm that PyPI contains the version before retrying. Do not create another tag, rerun the whole workflow, or rerun the `publish` job. Rerun only failed jobs in the original workflow run:

```bash
version=0.1.0
gh run view RUN_ID --repo mike840609/iiwi --json jobs \
  --jq '.jobs[] | [.name, .conclusion] | @tsv'
curl -fsS "https://pypi.org/pypi/iiwi/${version}/json" |
  uv run python -c 'import json, sys; print(json.load(sys.stdin)["info"]["version"])'
gh run rerun RUN_ID --repo mike840609/iiwi --failed
gh run watch RUN_ID --repo mike840609/iiwi --exit-status
```

Proceed only when `publish` is recorded as successful, `release` as failed, and the PyPI query prints the requested version. `--failed` then reruns only the separate `release` job. That job downloads the original `distributions` artifact and creates the missing GitHub Release. It creates the release as a draft, replaces both assets, and publishes only after both uploads succeed. On retry, it reuses any existing draft; if the preceding attempt published successfully before the runner reported failure, it verifies that both assets exist.

If the job conclusions do not have that exact shape, or PyPI does not contain the expected version, stop and diagnose the state instead of using this recovery path. Never move or replace the tag.

## Install after publication

```bash
pip install iiwi
```

For the CLI, isolated installation is preferred:

```bash
pipx install iiwi
# or
uv tool install iiwi
```
