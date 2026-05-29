# Contributing to claude-provenance

Thanks for the interest. This project ships honest governance machinery; contributions that preserve that honesty are very welcome. Contributions that paper over it are not.

## Before you start

1. **Read [`docs/STATUS.md`](docs/STATUS.md) first.** The per-layer build state names what is `BUILT`, `PARTIAL`, `STARTER`, and `NOT_BUILT`. If your contribution moves a row, the PR description must say so explicitly. If it does not move a row, do not claim it does.
2. **Read [`docs/OVERVIEW.md`](docs/OVERVIEW.md) for the eight-layer model and the design language.** Code and tests cite SPEC IDs of the form `SPEC-L*-S*` and invariants of the form `INV-*`. The normative SPEC document (`SPEC-v0.2`) is not yet committed to this repository; the SPEC IDs in code, test names, and status notes are the source of truth at v0.9.0b1. PRs that conflict with an existing SPEC ID should call that out in the description so the maintainer can resolve it.
3. **The two `NOT_BUILT` foundation rows (Data Classification, Retention/Tombstones) require domain input.** They cannot be fabricated. If you want to close them for your adopter context, propose the taxonomy first in an issue.

## Local development

```bash
git clone https://github.com/jvega017/claude-provenance.git
cd claude-provenance
python -m pip install -e ".[mcp]"
```

No third-party runtime dependencies for the core. The `[mcp]` extra is only needed if you are working on the MCP server.

## Running the test suite

```bash
python -m unittest discover -s tests -v
```

The suite is stdlib unittest. No pytest dependency. The CI matrix runs on Python 3.8 through 3.13; your local run should pass on the version you use day-to-day before you open a PR.

## Running the per-layer status check

```bash
python cli/warrantos_cli.py status
python cli/warrantos_cli.py status --markdown > docs/STATUS.md
```

If your PR changes a layer's build state, regenerate `docs/STATUS.md` and commit the result. CI does not currently fail on drift, but reviewers will check.

## Writing tests

- Tests live in `tests/test_*.py`. One module per logical surface.
- The standing rule: **an internal error must never break the calling session.** Tests verify both correct behaviour AND graceful degradation.
- For deferred features (G4, G5, classifier corpus), the test verifies that the stub raises the documented error. Removing such a stub without writing the real feature is a regression.
- Cross-platform: tests must pass on Linux CI. Use `tempfile.TemporaryDirectory()`, not hard-coded Windows paths.

## Adding a new gate or layer feature

1. Open an issue first using the `feature` template. Name the SPEC ID it addresses (or the new one you want).
2. Write the test first (TDD strongly preferred for any governance-bearing code).
3. Wire it into the pipeline (`cli/warrantos_cli.py`) and the MCP server if relevant (`provenance/mcp_server.py`).
4. Update `docs/STATUS.md` to reflect the new state.
5. Update `CHANGELOG.md` under the appropriate version's "Added", "Changed", or "Deferred" section.
6. The PR description must answer: "what does this guarantee that was not guaranteed before, and what does it still not guarantee".

## Honest documentation rule

- Do not write that a feature "ships in v0.X" when v0.X is the version under development. Either it ships in this PR or it does not.
- Do not soften a `NOT_BUILT` row to `PARTIAL` without changing the code.
- Do not increase a test count in prose; CI is the source of truth.

## Australian English

The author writes in Australian English (`-ise`/`-isation`, `programme`, `organisation`, `behaviour`, `modelling`). Existing docs follow this convention. PRs that re-Americanise existing prose will be reverted; PRs that add new prose in either dialect are fine.

## No em dashes

Trailing house style: no em dashes anywhere in the docs. Use a colon, a comma, or a new sentence. The reviewer will mark them; the linter will eventually catch them.

## Security issues

Do not file as a public PR or issue. See [`SECURITY.md`](SECURITY.md) for the responsible-disclosure process.

## Licence

By contributing, you agree your contribution will be released under the MIT licence that covers the rest of the repository.
