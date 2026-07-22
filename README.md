# WarrantOS: CI for claims

Every citation-trigger in an AI-assisted document ships with a source, a `[CITE NEEDED]` tag, or a logged BLOCK. No warrant, no ship.

*`claude-provenance` on GitHub and as the legacy Claude Code plugin; `warrantos` on PyPI and the CLI.*

[![ci](https://github.com/jvega017/warrantos/actions/workflows/ci.yml/badge.svg)](https://github.com/jvega017/warrantos/actions/workflows/ci.yml)
[![maturity: local release candidate](https://img.shields.io/badge/maturity-local%20release%20candidate-yellow)](docs/RELEASE-TRUTH.md)
![version: 0.11.0b2 local rc.1](https://img.shields.io/badge/version-0.11.0b2%20local%20rc.1-yellow)
![python: 3.11--3.13](https://img.shields.io/badge/python-3.11--3.13-blue)
![deps: stdlib only](https://img.shields.io/badge/deps-stdlib%20only-green)

> **Release truth:** this checkout is candidate `warrantos-0.11.0b2-local-rc.1`, not a tagged or
> production-qualified release. `release-manifest.json` is canonical; see
> [`docs/RELEASE-TRUTH.md`](docs/RELEASE-TRUTH.md).
>
> **Support vocabulary:** the legacy CLI label `claims supported` means a
> citation token was present. New records call that `citation_present`.
> Exact byte/range verification produces `passage_reproduced`, an
> evidence-only state. The legacy `--reviewer` and `--verdict` inputs cannot
> mint `support_verified`; standalone WarrantOS does not authenticate semantic
> review proof.
## Ten seconds

```text
$ warrantos demo --output warrantos-demo
WarrantOS honest demo
---------------------
Checking a synthetic AI-style draft that deliberately contains
unsupported factual claims and conversational scaffold residue.
Expect a BLOCK verdict.

warrantos check
  run id:        run_6e466f721f8a
  profile:       final-prose
  claims detected: 7
  claims supported: 0
  claims unsupported: 7
  boundary: blocked (7 violations)
  overrides on record: 0

VERDICT: BLOCK
  - BLOCK: boundary violation [assistant_opener severity=high] line 9: Certainly!
  - BLOCK: boundary violation [hedge_provenance severity=medium] line 15: Based on the information provided
  - BLOCK: boundary violation [scaffold_placeholder severity=high] line 17: [TODO: add the figures from the evaluation once the team sen
  - BLOCK: boundary violation [assistant_closer severity=high] line 19: I hope this helps
```

Real output, trimmed. The full run lists all seven violations, retains the
draft and run directory, creates `demo.warrant`, verifies it against the exact
draft bytes, and prints a repeatable verification command.

## Install the current candidate safely

The public 0.10.0 package and GitHub Action are **not recommended**. They are
affected by the P0 artefact-binding advisory in [`SECURITY.md`](SECURITY.md).
Do not use an unversioned package-index command, `uvx` trial, pre-commit ref or
the 0.10.0 Action as a current WarrantOS acquisition path.

The only recommended adopter path today is the **authenticated 0.11.0b2
candidate bundle** distributed with Vega Runtime. Obtain `install.ps1`,
`artifact-manifest.json`, the expected installer SHA-256 and the expected
manifest SHA-256 through the named release channel. Authenticate the installer
in the parent PowerShell process before it runs:

```powershell
$expectedInstallerSha256 = "<out-of-band install.ps1 SHA-256>"
$expectedManifestSha256 = "<out-of-band artifact-manifest.json SHA-256>"
if ((Get-FileHash -LiteralPath .\install.ps1 -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedInstallerSha256) { throw "Untrusted installer bytes" }
.\install.ps1 -ExpectedManifestSha256 $expectedManifestSha256
.\.vega-venv\Scripts\warrantos --version
.\.vega-venv\Scripts\warrantos demo --output .\warrantos-demo
```

The installer re-authenticates the signed manifest and both wheel digests before
creating the environment. Running it without the parent-shell hash check is not
an authenticated bootstrap. There is currently no `v0.11.0b2` tag. macOS and
Linux adopters should wait for the tagged public promotion rather than treating
an unauthenticated wheel or source checkout as a supported release.

### Evidence binding and production verification

The installed `warrantos-evidence` command creates content-addressed source
snapshots, binds exact claim and source character ranges, and independently
reproduces their digests before recording a review verdict. A citation detected
by `warrantos check` remains only `citation_present` until this explicit path is
completed.

Production-facing verification uses `warrantos-evidence verify-release` with a
deployment-owned `warrantos-trust-root/v1` file. WarrantOS intentionally ships
no production key. See [`docs/PRODUCTION-DEPLOYMENT.md`](docs/PRODUCTION-DEPLOYMENT.md).

## Lint your docs for AI slop

```bash
warrantos slop docs/ README.md         # scan paths for scaffold residue and unsourced claims
warrantos slop --json docs/            # machine-readable output
warrantos slop --badge docs/           # emit a badge URL for your README
warrantos slop --fail-over 0 docs/     # CI mode: non-zero exit above the threshold
```

Catches the tells that an AI draft shipped unedited: assistant openers and sign-offs, identity disclaimers, delivery framing, stray TODO placeholders, and factual sentences with no source in reach. The full pattern list lives in one place, [`context_admissibility`](warrantos/provenance/context_admissibility.py), so a `slop` finding and a `check` violation are always explained by the same rule. Fenced code blocks are skipped by default because they usually quote deliberate examples; scan them with `--include-fences`.

Then go one layer deeper with `warrantos tells`, the opinionated sibling: it flags prose that is residue-free but still reads machine-written (contrastive negation of the "not X, but Y" family, stacked hedges, em-dash punctuation, AI filler phrases, a drumbeat of formulaic paragraph-openers). House style is a judgement call, so `tells` lives in its own command and its own score; the philosophy and limits are in [`docs/TELLS.md`](docs/TELLS.md).

```
warrantos tells docs/                  # TELL SCORE plus per-finding pattern and category
```

This repository holds itself to both: the docs scan slop-free and tells-clean.

## Gate your agent

The candidate contains the MCP and Claude Code integration code, but the
authenticated bundle installer does not install the optional MCP transport.
Treat MCP setup as developer evaluation only until 0.11.0b2 is publicly
promoted; do not resolve the advisory-affected public extra. The Claude Code
Stop hook (`warrantos-verify-hook`) checks what the model wrote before the turn
ends: stdlib only, no network, never breaks the session. Wiring and development
instructions live in [`docs/MCP-CONFIG.md`](docs/MCP-CONFIG.md); the hook
surfaces live in [`warrantos/hooks/`](warrantos/hooks/).

## Audit trail for governance

```bash
warrantos attest final.md --run-dir .warrant/runs/<id> --out final.warrant
warrantos verify-external final.warrant --prose final.md   # exits non-zero on any failure
```

Every checked run can be sealed into a portable `.warrant` bundle that a third party verifies offline: no access to your ledger, no network call, fail-closed, with a zero-backend browser verifier (`web/verify.html`) for readers who have only the file. Wheel installs also include it under the environment's `share/warrantos/web/` directory. Details in [`docs/VERIFICATION.md`](docs/VERIFICATION.md); the control mapping to ISO/IEC 42001 and the NIST AI RMF is in [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md).

## How it works

WarrantOS reads one document at the writer's desk, before it ships.
It detects citation-trigger patterns (years, percentages, magnitude, statutory references, attribution, causal language, superlatives, etc.) and records a nearby source token as `citation_present`, or an explicit `[CITE NEEDED]`. It does not call that semantic support verification.
It scans for chat scaffold and process residue that bled into the artefact.
It returns one verdict (`PASS`, `HOLD`, `BLOCK`, or `NOT_ASSESSABLE`) and writes every miss to an append-only, tamper-evident ledger you can hand an auditor.
Stdlib only, MIT, no API, no account.

| Doc | What it covers |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | Five-minute tour with each output line explained |
| [`docs/SPEC.md`](docs/SPEC.md) | The normative specification |
| [`docs/STATUS.md`](docs/STATUS.md) | Per-layer build-state dashboard |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | Known failure modes, stated plainly |
| [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md) | ISO/IEC 42001 and NIST AI RMF self-assessment mapping |
| [`docs/VERIFICATION.md`](docs/VERIFICATION.md) | Offline `.warrant` verification in full |
| [`docs/FULL-OVERVIEW.md`](docs/FULL-OVERVIEW.md) | The pre-0.10 README body: full narrative, tooling map, release history |
| [`PRIVACY.md`](PRIVACY.md) | Local data handling, telemetry and opt-in network paths |
| [`SUPPORT.md`](SUPPORT.md) | Support boundary and safe issue-reporting requirements |
| [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md) | Supported runtimes, schemas and deprecation policy |
| [`docs/RELEASE-PROCESS.md`](docs/RELEASE-PROCESS.md) | Tagged build-once promotion through TestPyPI and PyPI |

## What this does not do

WarrantOS does not detect truth, and it does not try to. The claim detector is a heuristic and will produce false positives and false negatives. Offline verification checks token overlap, not meaning. A correctly sourced claim can still be misleading or selectively cited. What the tool guarantees is narrower and operational: an unsourced or unchecked claim becomes expensive instead of invisible, and the miss goes on the record. It does not replace human review and does not claim to. The full list is in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Licence

MIT. Built by Juan Vega, Prometheus Policy Lab, in a personal capacity. Not associated with, funded by, or endorsed by any employer or government.
