# Contributing to WarrantOS

WarrantOS is governance machinery. Contributions must state the control they
enforce, the executable evidence for it, and what remains outside the claim.

## Before you start

1. Read [status](docs/STATUS.md), [limitations](docs/LIMITATIONS.md) and the
   [stack](docs/STACK.md).
2. Open an issue for a new governance-bearing feature or schema change.
3. Do not move a control from implemented to enforced, evaluated or production
   qualified without the corresponding evidence.
4. Do not add sensitive material, credentials or private source content to a
   fixture.

## Local development

WarrantOS supports CPython 3.11 through 3.13.

```bash
git clone https://github.com/jvega017/warrantos.git
cd warrantos
python -m pip install -e ".[attestation,mcp]"
python -m unittest discover -s tests -v
python tools/check_release_truth.py --publication local
```

The core runtime is standard-library only. Extras are needed only for the
features they name.

## Test and documentation contract

- Tests live under `tests/test_*.py` and use `unittest`.
- Use `tempfile.TemporaryDirectory()` for filesystem tests.
- Add hostile cases for fail-closed controls, not only happy paths.
- Run `warrantos status` to inspect the generated layer status.
- Update `CHANGELOG.md`, `release-manifest.json` and affected truth surfaces.
- Release-truth CI checks version and control claims. A public promotion also
  requires the GitHub Action lock and Claude plugin versions to equal the
  release version.
- Test copy-paste commands from a clean directory. Do not document a path or
  script that the package does not ship.

## Pull request evidence

The PR description must answer:

1. What control or adopter outcome changed?
2. Which command or test demonstrates it?
3. Which failure mode is now blocked?
4. What still is not guaranteed?
5. Does this change a schema, release surface or compatibility promise?

## Style and safety

- Use Australian English where practical.
- Avoid em dashes in documentation.
- Never log or reproduce secret values.
- Do not weaken an existing gate to make a test pass without documenting the
  policy change.
- Preserve append-only audit semantics.

Report vulnerabilities through [SECURITY.md](SECURITY.md), not a public issue
or pull request.

By contributing, you agree that your contribution is released under the MIT
licence.
