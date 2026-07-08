# WarrantOS: CI for claims

Every factual claim in an AI-assisted document ships with a source, a `[CITE NEEDED]` tag, or a logged BLOCK. No warrant, no ship.

*`claude-provenance` on GitHub and as the legacy Claude Code plugin; `warrantos` on PyPI and the CLI.*

[![ci](https://github.com/jvega017/claude-provenance/actions/workflows/ci.yml/badge.svg)](https://github.com/jvega017/claude-provenance/actions/workflows/ci.yml)
[![layers: 20B / 0P](https://img.shields.io/badge/layers-20B%20%2F%200P-brightgreen)](docs/STATUS.md)
![version: 0.10.0](https://img.shields.io/badge/version-0.10.0-orange)
![python: 3.11--3.13](https://img.shields.io/badge/python-3.11--3.13-blue)
![deps: stdlib only](https://img.shields.io/badge/deps-stdlib%20only-green)

## Ten seconds

```text
$ warrantos demo
WarrantOS honest demo
---------------------
Checking a synthetic AI-style draft that deliberately contains
unsupported factual claims and conversational scaffold residue.
Expect a BLOCK verdict.

warrantos check
  run id:        run_6e466f721f8a
  profile:       final-prose
  claims detected: 6
  claims supported: 0
  claims unsupported: 6
  boundary: blocked (7 violations)
  overrides on record: 0

VERDICT: BLOCK
  - BLOCK: boundary violation [assistant_opener severity=high] line 9: Certainly!
  - BLOCK: boundary violation [hedge_provenance severity=medium] line 15: Based on the information provided
  - BLOCK: boundary violation [scaffold_placeholder severity=high] line 17: [TODO: add the figures from the evaluation once the team sen
  - BLOCK: boundary violation [assistant_closer severity=high] line 19: I hope this helps
```

Real output, trimmed. The full run lists all seven violations and the paths of the audit artefacts it wrote.

## Install

```bash
pipx install warrantos      # isolated CLI install
uvx warrantos demo          # zero-install trial run
pip install warrantos       # plain pip works too
```

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

```bash
pip install "warrantos[mcp]"
warrantos-mcp                # stdio MCP server for Claude Code / Claude Desktop
```

The Claude Code Stop hook (`warrantos-verify-hook`) checks what the model wrote before the turn ends: stdlib only, no network, never breaks the session. Wiring instructions in [`docs/MCP-CONFIG.md`](docs/MCP-CONFIG.md); the hook surfaces live in [`warrantos/hooks/`](warrantos/hooks/).

## Audit trail for governance

```bash
warrantos attest final.md --run-dir .warrant/runs/<id> --out final.warrant
warrantos verify-external final.warrant --prose final.md   # exits non-zero on any failure
```

Every checked run can be sealed into a portable `.warrant` bundle that a third party verifies offline: no access to your ledger, no network call, fail-closed, with a zero-backend browser verifier (`web/verify.html`) for readers who have only the file. Details in [`docs/VERIFICATION.md`](docs/VERIFICATION.md); the control mapping to ISO/IEC 42001 and the NIST AI RMF is in [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md).

## How it works

WarrantOS reads one document at the writer's desk, before it ships.
It detects factual claim sentences and checks each for a source in the same sentence or the line directly below, or an explicit `[CITE NEEDED]`.
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

## What this does not do

WarrantOS does not detect truth, and it does not try to. The claim detector is a heuristic and will produce false positives and false negatives. Offline verification checks token overlap, not meaning. A correctly sourced claim can still be misleading or selectively cited. What the tool guarantees is narrower and operational: an unsourced or unchecked claim becomes expensive instead of invisible, and the miss goes on the record. It does not replace human review and does not claim to. The full list is in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Licence

MIT. Built by Juan Vega, Prometheus Policy Lab, in a personal capacity. Not associated with, funded by, or endorsed by any employer or government.
