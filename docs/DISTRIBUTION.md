# Distribution surfaces

Copy-paste snippets for wiring WarrantOS into CI, pre-commit, and one-off
runs. Every surface below installs the published `warrantos` package from
PyPI; none of them requires a source checkout.

## GitHub Action

The repository root ships a composite action (`action.yml`). Reference it
directly by repository and ref. It is **not yet published to the GitHub
Actions Marketplace**, so it will not appear in Marketplace search; the
direct `owner/repo@ref` reference below works regardless.

Minimal workflow (`.github/workflows/warrantos.yml`):

```yaml
name: warrantos
on: [push, pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4
      - uses: jvega017/warrantos@main
```

The default run scans the whole repository for AI scaffold and
conversational residue (`warrantos slop . --fail-over 0`) and fails the job
on any hit. All inputs, with defaults:

```yaml
      - uses: jvega017/warrantos@main
        with:
          paths: "docs drafts"        # files or directories, space-separated (default ".")
          mode: "both"                # "slop" (default), "check", or "both"
          profile: "brief-light"      # boundary profile for check mode
          fail-over: "0"              # slop-score threshold; 0 fails on any residue
          python-version: "3.12"
```

In `check` mode the action runs `warrantos check --ci` per Markdown file,
so the job exits non-zero on a `HOLD`, `BLOCK`, or `NOT_ASSESSABLE`
verdict. Pin the ref to a tag (for example
`jvega017/warrantos@v0.10.0`) once you depend on it.

## pre-commit

The repository ships `.pre-commit-hooks.yaml` with two hooks. Add to your
`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/jvega017/warrantos
    rev: v0.10.0
    hooks:
      - id: warrantos-slop         # blocks scaffold residue in staged Markdown
      - id: warrantos-check        # full pipeline; manual stage, opt-in
      - id: warrantos-tells        # style tells; manual stage, opt-in
```

`warrantos-slop` runs on every commit that stages Markdown and fails when
any scaffold or conversational residue is present (`--fail-over 0`).

`warrantos-check` is registered on the `manual` stage so it never runs
automatically; invoke it deliberately on the draft you are about to ship:

```bash
pre-commit run --hook-stage manual warrantos-check --files YOUR_DRAFT.md
```

## pipx and uvx

For an isolated install of the CLI:

```bash
pipx install warrantos
```

For a zero-install one-off run (uv resolves and caches the package):

```bash
uvx warrantos demo
uvx warrantos slop YOUR_DRAFT.md --fail-over 0
```

## Citation

The repository root ships `CITATION.cff`, which GitHub renders as a "Cite
this repository" button. It points to the software release and notes the
working paper *From Citation to Epistemic Governance* (in preparation) as
the preferred citation once it is available.
