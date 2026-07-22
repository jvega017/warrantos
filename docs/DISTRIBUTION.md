# Distribution surfaces

The public distribution surfaces are temporarily **not recommended**. Their
immutable public version is 0.10.0, which is affected by the P0 artefact-binding
advisory. The only recommended current adopter path is the **authenticated
0.11.0b2 candidate bundle** described in [Quickstart](QUICKSTART.md).

The sections below document the blocked surfaces and what must change at
promotion. They deliberately contain no runnable 0.10.0 acquisition snippets.

## GitHub Action

The repository root ships a composite action (`action.yml`), but its immutable
public package lock is the advisory-affected release. Do not reference the
Action from a governance workflow until the 0.11.0b2 promotion updates the
Action source, hash lock and release manifest together. It is also not yet
published to the GitHub Actions Marketplace.

In `check` mode the action runs `warrantos check --ci` per Markdown file,
so the job exits non-zero on a `HOLD`, `BLOCK`, or `NOT_ASSESSABLE`
verdict. Paths are newline-delimited, so a path containing spaces remains one
path. The public-release gate refuses promotion until the Action lock matches
the release version and the acquisition block is removed.

## pre-commit

The repository ships `.pre-commit-hooks.yaml`, but there is no currently
recommended immutable public ref. Wait for the 0.11.0b2 promotion before adding
the hook to a repository.

`warrantos-slop` runs on every commit that stages Markdown and fails when
any scaffold or conversational residue is present (`--fail-over 0`).

`warrantos-check` is registered on the `manual` stage so it never runs
automatically; invoke it deliberately on the draft you are about to ship:

```bash
pre-commit run --hook-stage manual warrantos-check --files YOUR_DRAFT.md
```

## Package-index tools

Do not use an unversioned package-index or zero-install command while 0.10.0 is
the latest public distribution. After 0.11.0b2 promotion, this page will publish
exact version-pinned `pipx`, `uvx` and ordinary installer commands only after
the three-OS public-package smoke matrix passes.

## Citation

The repository root ships `CITATION.cff`, which GitHub renders as a "Cite
this repository" button. It points to the software release and notes the
working paper *From Citation to Epistemic Governance* (in preparation) as
the preferred citation once it is available.
