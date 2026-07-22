# WarrantOS full overview

> **Provenance of this page.** This is the README body as it stood before the 0.10 front-page rewrite, preserved so no detail is lost. The repository [`README.md`](../README.md) is now the short front door; this page keeps the fuller narrative, the tooling map, the four-verdict model, the release history, and the configuration reference. The badge row and the limitations paragraph stay in the README.
>
> **ARCHIVED ACQUISITION WARNING:** Commands and release statements on this
> historical page are preserved evidence, not current installation guidance.
> Public 0.10.0 is affected by the P0 artefact-binding advisory. Use only the
> authenticated 0.11.0b2 candidate-bundle path in
> [`QUICKSTART.md`](QUICKSTART.md) until public promotion.

## No claim ships without a warrant.

WarrantOS does not detect truth, and it does not try to. It enforces that every claim in an AI-assisted document carries a warrant: a source, an explicit `[CITE NEEDED]`, or a `BLOCK` on the record. A four-state verdict (`PASS` / `HOLD` / `BLOCK` / `NOT_ASSESSABLE`) gates the output before it ships in `enforce` mode (the default `report` mode logs every miss without blocking), and every miss is written to an append-only ledger, tamper-evident against a previously distributed checkpoint, that you can hand an auditor.

It also catches the other way an AI document betrays itself: **internal scaffold and conversational residue that bleeds from the chat into the final artefact**. For example (quoted patterns fenced so the default self-scan skips them):

```text
Certainly! Here's the revised version
As an AI language model, I cannot verify
based on the information provided
I hope this helps, let me know if you would like me to expand
[TODO: ...]
```

A clean artefact carries its evidence and none of the machinery that produced it. WarrantOS blocks the machinery from shipping.

It governs the artefact, not the model. It runs at the writer's desk, on one document, before it ships, with zero infrastructure: stdlib-only, MIT, no API, no account. Governance platforms watch the system after the fact; WarrantOS gates the output before the fact.

Built in a personal capacity by an independent policy researcher for the people who publish AI-assisted writing under their own name and carry the reputational liability for a fabricated citation: research-integrity, policy, and academic-governance practitioners. It is a personal open-source project, not associated with, funded by, or endorsed by any employer or government. It is informed by the working paper *From Citation to Epistemic Governance* (Prometheus Policy Lab, in preparation): it operationalises that paper's problem framing, the gap between citation as attribution and citation as evidence, rather than its formal model.

**The honest demo, reproducible.** The demo ships inside the package, so you do not have to take an anecdote on trust. After `pip install warrantos`, one command with no setup runs WarrantOS over a bundled AI-style first draft and returns `BLOCK`: 6 claims detected, 0 supported, 7 boundary violations (scaffold and conversational residue).

```bash
warrantos demo
```

The same fixtures live in the repository at `examples/honest-demo/` if you prefer to run the explicit command and inspect the inputs; `tools/run_gallery.py` asserts the identical verdict on every CI push.

```bash
warrantos check examples/honest-demo/draft.md \
  --context examples/honest-demo/context.json \
  --actor-identity examples/honest-demo/actor.json --profile final-prose
```

That is the gate working as designed on an unremediated AI draft: it names the epistemic debt so it can be paid down before the artefact ships, instead of going out silently. A governance tool worth trusting is one anyone can hold to its own standard.

Under the hood, `claude-provenance` wraps AI-assisted writing in an eight-layer pipeline so the final artefact ships clean prose, while a separate audit ledger carries the sources, the feedback, the review history, the transformations, and the structured overrides that produced it. The per-layer status dashboard tells you exactly what is built and what is not.

> **v0.9.5.** Build state: **20 BUILT / 0 PARTIAL** (unchanged at v0.9.5; was 13 BUILT / 3 PARTIAL / 2 STARTER / 2 NOT_BUILT at v0.9.1, reaching 20 BUILT at v0.9.2). All five output-integrity gates (G1-G5) and all eight foundation rows are BUILT. The final three rows closed in v0.9.2: **F-policy** (the normative spec `docs/SPEC.md` and a machine-readable six-role registry are now committed), **F-compliance** (a self-assessment control mapping to ISO/IEC 42001 and the NIST AI RMF in `docs/COMPLIANCE.md`: a documented mapping, explicitly **not** certified conformance), and **F-metrics** (shadow-log aggregation via the `warrantos metrics` command). Adopter-specific configuration (sensitivity tiers, retention windows) and an automated SPEC-ID conformance check remain future work, stated plainly in those docs. See [`STATUS.md`](STATUS.md) before evaluating scope.

## Quickstart

Install from PyPI:

```bash
pip install warrantos          # MCP server extra: pip install "warrantos[mcp]"
```

See it work immediately, no setup (the demo fixtures ship in the package):

```bash
warrantos demo                 # bundled honest demo -> BLOCK verdict
```

Start on your own document:

```bash
warrantos init                 # scaffolds context.json + actor.json templates
warrantos check YOUR_DRAFT.md \
  --context context.json \
  --actor-identity actor.json --profile final-prose
```

To inspect the inputs or run the fuller quickstart example, use a source checkout (it ships the `examples/` directory):

```bash
git clone https://github.com/jvega017/warrantos.git
cd claude-provenance
python -m pip install -e ".[mcp]"

# Per-run artefacts are written under .warrant/runs/
warrantos check examples/quickstart-demo/draft.md \
  --context examples/quickstart-demo/context.json \
  --actor-identity examples/quickstart-demo/actor.json \
  --profile final-prose
```

Expected verdict: `HOLD` with one unsupported load-bearing claim. The bundled command exercises Layer 1 classification, Layer 4 admissibility, Layer 7 G1 (boundary), Layer 7 G2 detection, CBOM assembly, and the four-state verdict consolidator; add `--verify` to run the G2 verifier and `--writer-model`/`--verifier-model` to run G3. G4 (safety and contamination) and G5 (evaluation and calibration) are BUILT but are not exercised by this minimal demo.

| Where to go next | Doc |
|---|---|
| Five-minute tour with explanation of each output line | [`QUICKSTART.md`](QUICKSTART.md) |
| Per-layer conformance dashboard (BUILT / PARTIAL) | [`STATUS.md`](STATUS.md) |
| Whole-repository tour | [`OVERVIEW.md`](OVERVIEW.md) |
| Connect to Claude Code or Claude Desktop as MCP tools | [`MCP-CONFIG.md`](MCP-CONFIG.md) |
| Verify without an Anthropic API key (local LLM, Stop hook) | [`NO-API-KEY.md`](NO-API-KEY.md) |
| Cost model and spend control | [`COST.md`](COST.md) |
| Architecture and layer map | [`STACK.md`](STACK.md) |

## Tooling map

| Entry point | What it does | When to use |
|---|---|---|
| `warrantos` | Full pipeline (classify > admissibility > gates > verdict > CBOM) | Default. This is the one. |
| `warrantos demo` | Run the bundled honest demo (a real BLOCK verdict, zero setup) | First thing to run after install, to see the gate work |
| `warrantos init` | Scaffold `context.json` and `actor.json` starter templates | When starting on your own document, to get the actor schema right |
| `warrantos-mcp` | Stdio MCP server exposing four tools to Claude Code / Claude Desktop | When you want Claude to call the pipeline as tools |
| `warrantos-verify-hook` | Claude Code Stop-hook entry point for in-session verification | When you want the loop closed without a separate API key |
| `warrantos attest` | Bundle a checked run into a portable, signed `.warrant` artefact | When an artefact needs to travel with a verifiable audit proof |
| `warrantos verify-external` | Verify a `.warrant` offline; exits non-zero on failure | In CI, or for any third party with only the file |
| `web/verify.html` | Zero-backend browser verifier for a `.warrant` | When a reader has no install and only the file |
| `provenance` | Legacy v0.3 citation-only CLI | Kept for v0.3 users; new users should use `warrantos` |

## The four-verdict model

| Verdict | Trigger | Action |
|---|---|---|
| `PASS` | No boundary violation, no unsupported load-bearing claim, no contradicted verifier verdict, actor identity present for final-prose | Ship the artefact |
| `HOLD` | Unsupported or unverifiable load-bearing claim, or a same-actor writer/reviewer override on a final-artefact profile (separation of duties) | Add a citation, downgrade the claim, or obtain an independent review |
| `BLOCK` | Boundary violation in final-prose, a contradicted verifier verdict, or a same-actor override on the strict `audit` profile | Rewrite the offending text, or obtain an independent reviewer |
| `NOT_ASSESSABLE` | Final-prose without `--actor-identity` | Supply actor identity or use a non-final-prose profile |

`NOT_ASSESSABLE` is deliberate. Most tools binary-ise into pass/fail. The fourth state names the case where the artefact is missing the metadata required to certify, instead of certifying on incomplete information.

The four verdicts are exercised end-to-end in the [`examples/`](../examples/) gallery: one runnable case per verdict, plus a `tools/run_gallery.py` thesis demo that runs all four and asserts each example produces its documented verdict. CI runs the same demo on every push.

## The honest pitch

`claude-provenance` does not guarantee that AI-assisted writing is correct. No tool can. It guarantees five operational properties instead:

1. **Unsourced claims are expensive, not invisible.** The detector logs every unsupported factual sentence; the ledger keeps the count over time.
2. **Process material cannot leak into final prose silently.** The Layer 7 G1 boundary gate blocks "based on your feedback" and the rest of the lexical-residue pattern set under the `final-prose` profile.
3. **Overrides cannot reach the public artefact without a structured rationale.** Empty `risk_accepted` or `compensating_control` blocks the write; SQLite `BEFORE UPDATE` triggers (INV-004) prevent silent post-hoc edits.
4. **Separation of duties is a verdict-layer property.** When an override records the writer and reviewer as the same actor, `consolidate_verdict()` acts on it: a final-artefact profile (`final-prose`, `paper-full`, `methodology`, `consultation_report`, `audit`) is downgraded to `HOLD`, and the strict `audit` profile to `BLOCK`. An independent reviewer is required to certify `PASS`. Enforced on both the CLI and MCP paths; the helper `enforce_single_actor_rule` and the reader-facing footer surface the flag for a human reader (SPEC-L8-S003).
5. **The four-state verdict refuses to certify on incomplete information.** `NOT_ASSESSABLE` fires when the metadata required to certify is missing, instead of `PASS` masking the gap.

What this does **not** guarantee: that the underlying model produced correct text, or that a cited source is the strongest available source. Data Classification and Retention/Tombstones are now BUILT, but they ship with default tiers and windows: adopters must still configure their own sensitivity taxonomy and retention policy for their domain.

## What landed in v0.9.0b1

User-outcome language; SPEC IDs in [`CHANGELOG.md`](../CHANGELOG.md).

- One CLI runs the full pipeline end-to-end (`warrantos check`).
- Human overrides cannot be recorded without a written risk-acceptance rationale and a compensating-control note. The check is at the write path, so the row does not exist if the rationale is missing. SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers on every ledger table mean recorded rows cannot be silently edited or deleted later (storage-level append-only, installed by default, not application-level discipline). This covers the SQLite ledger the hook writes misses to; the per-run JSON artefacts under `.warrant/runs/` are working output, not the append-only ledger.
- Separation-of-duties helper (`warrantos/provenance/overrides.py::enforce_single_actor_rule`) detects a reviewer-equals-writer pair when an override is recorded and surfaces it in the reader-facing footer. The same check is wired into `consolidate_verdict()` on the CLI and MCP paths: a final-artefact profile is downgraded to `HOLD`, the strict `audit` profile to `BLOCK`.
- MCP server exposes four tools (`warrant_check`, `warrant_classify`, `warrant_record_override`, `warrant_get_run`) callable from any MCP host.
- Shadow-mode observer runs over an already-published artefact in read-only mode. Never blocks. Never modifies production scripts.
- `warrantos status` reports a per-layer build state, and `docs/STATUS.md` carries the rendered table.
- Empirical calibration: the prose-boundary gate ships a `prompt-template` profile after a 10-brief calibration pass produced unactionable false positives under the `brief-light` profile.

## How it works: the Provenance Loop

The Provenance Loop is the original v0.3 mental model: **Extract** the claim, **Bind** a source to it, **Verify** the source supports the claim, **Adjudicate** the verdict, **Ledger** the result. In v0.9 the loop is one component of the eight-layer WarrantOS pipeline, specifically Layer 2 (Ledger) and Layer 7-G2 (Source and Warrant Check). For the full architecture see [`OVERVIEW.md`](OVERVIEW.md); for the loop itself see [`PROVENANCE-LOOP.md`](PROVENANCE-LOOP.md).

## Offline-verifiable warrants

A verdict you have to trust is weaker than one you can recompute. WarrantOS turns a checked run into a portable, tamper-evident `.warrant` bundle that a third party verifies offline, with no access to your ledger and no network call.

- **Tamper-evident ledger.** A deterministic, RFC 6962 style Merkle tree (`warrantos.provenance.merkle`, pure stdlib) over the audit entries. One root digest fixes the entire ledger state: any insert, edit, delete, or reorder changes it.
- **Signed checkpoint and portable bundle.** `create_warrant()` packages the prose digest, the CBOM, the relevant ledger entries, and an Ed25519-signed checkpoint into one `.warrant` file. Signing uses the optional `[attestation]` extra; the integrity check needs nothing beyond the standard library.
- **Fail-closed verification.** `warrantos verify-external` recomputes the Merkle root and matches the checkpoint. An unsigned or signature-unavailable bundle is overall `INVALID` unless `--allow-unsigned` is passed explicitly. A client-side browser verifier (`web/verify.html`) is validated against the Python verifier by a differential test over the supported value domain, and renders all untrusted fields as inert text under a strict CSP.

```bash
warrantos attest final.md --run-dir .warrant/runs/<id> --out final.warrant
warrantos verify-external final.warrant --prose final.md      # exits non-zero on any failure
```

Full detail in [`VERIFICATION.md`](VERIFICATION.md). The envelope is project-defined, with a DSSE/COSE migration under consideration.

## Why this exists

This tool is an operational companion to a working paper, *From Citation to
Epistemic Governance* (Prometheus Policy Lab, in preparation). It takes the
paper's problem framing and burden-of-proof stance, not its formal apparatus:
the provenance tuple, the five-valued confidence scale, and the warrant-decay
model are the paper's contribution, not this tool's. The argument is that the
AI failures that matter most in high-stakes work are often not model-capability
failures but epistemic ones: the model states something with confidence and no
traceable source, a human under time pressure ships it, and the error was
never about model size. The fix is a loop that refuses to let an unsourced or
unverified claim pass silently.

## Two axes: detection and verification

`claude-provenance` separates two questions that most tools conflate.

**Axis 1, detection (in-session, stdlib only, zero network).** The hook reads
what the model wrote and classifies each factual sentence as **supported** (a
source is present in its own sentence or the line directly below it),
**tagged** (an explicit `[CITE NEEDED]`, treated as honest), or
**unsupported** (nothing). A source two or more sentences away does not rescue
a claim: that bleed was the v0 false negative and is closed by design. This
axis stays a fast tripwire that never does network I/O and never breaks the
session.

**Axis 2, verification (out of band).** The verifier takes a detected claim,
fetches the cited URL, and assigns one of: **verified**, **contradicted**,
**not_addressed**, **unverifiable** (a citation exists but cannot be
machine-checked, for example an `(Author, Year)` with no URL), **skipped**, or
**error**. By default this uses an offline token-overlap heuristic. If
`ANTHROPIC_API_KEY` is set it uses an LLM grader, and on any failure it falls
back to the heuristic. The verifier is never called from the blocking hook.

The detector catches the cheap, common failure. The verifier targets the
expensive one: a claim that is confidently cited and wrong. Detecting an
outright `contradiction`, as opposed to mere non-support, needs a configured
LLM grader; the offline default flags `unsupported` and `unverifiable` but
never emits `contradicted`.

## Install as a Claude Code plugin (legacy v0.3 hook)

The Claude Code plugin currently wires the **legacy v0.3** in-session Stop hook (`warrantos/hooks/provenance_check.py`), not the WarrantOS surfaces. It remains a fast, stdlib-only citation tripwire for live Claude Code sessions. For the v0.9 WarrantOS pipeline (CLI + MCP server + per-layer dashboard + four-state verdict) use the source install above; the WarrantOS plugin wiring is a v0.10 design item.

```
/plugin marketplace add /path/to/claude-provenance
/plugin install claude-provenance
```

The plugin install gives you the in-session Stop hook and slash commands (`/provenance-report`, `/provenance-verify`). Requires Python 3.11+ on `PATH`. No third-party packages for the core; the `[mcp]` extra adds the `mcp` SDK.

## Configuration

Environment variables. See [`COST.md`](COST.md) for spend-control flags and [`NO-API-KEY.md`](NO-API-KEY.md) for local-LLM and Stop-hook configuration.

| Variable                            | Values                     | Default                       |
|-------------------------------------|----------------------------|-------------------------------|
| `PROVENANCE_MODE`                   | `report`, `enforce`, `off` | `report`                      |
| `PROVENANCE_DB`                     | path to SQLite file        | `./.provenance/provenance.db` |
| `WARRANTOS_DB`                      | path to SQLite file        | `./.warrant/provenance.db`    |
| `ANTHROPIC_API_KEY`                 | API key                    | unset (verifier stays offline)|
| `PROVENANCE_GRADER_MODEL`           | model id                   | `claude-haiku-4-5-20251001`   |
| `PROVENANCE_LOCAL_GRADER_URL`       | URL                        | unset (use heuristic)         |
| `PROVENANCE_LOCAL_GRADER_MODEL`     | model name                 | `llama3.2`                    |

`PROVENANCE_MODE` controls the legacy Stop hook: **report** logs every run and prints a summary, non-blocking; **enforce** blocks the end of a turn or a file write when an unsupported factual claim is present; **off** disables the hook. The Stop hook is loop-safe and never blocks the same turn twice. With no API key the verifier degrades to the offline heuristic with no error.

## Legacy v0.3 CLI

The `provenance` entry point is kept for users on the v0.3 mental model (citations only). New users should use `warrantos` instead, which wraps detection, verification, admissibility, gates, and the override ledger as one pipeline. The legacy CLI runs the detection-and-verification loop over a file, a directory, or stdin, outside a live session:

```
provenance path/to/draft.md             # offline detection
provenance --verify path/to/draft.md    # fetch and grade
provenance --ci docs/                   # exit 1 on a miss
provenance --cbom --context context.json final.md
```

`--ci` exits 1 if any claim is `contradicted` or `unsupported`. `--json` emits machine-readable output. CBOM mode (`--cbom`) classifies context material and scans final prose for process leakage such as "based on your feedback".

In a Claude session, `/provenance-report` summarises the ledger and `/provenance-verify` runs the verification stage.

## Governance: epistemic debt

The ledger is the point, not a side effect. `warrantos/provenance/ledger.py` computes an
**epistemic-debt** metric (load-bearing unsupported claims, normalised, with a
direction over the last runs) and exports an evidence matrix to Markdown or
CSV. Load-bearing is scored by `warrantos/provenance/salience.py`: a statutory reference
inside a recommendation is weighted above a date in passing. The governance
question is not "is this sentence cited" but "is our AI-assisted output getting
more or less sourced over time", and the ledger answers it.

## Evaluation

`eval/run_eval.py` runs the detector against the seed corpus and prints precision, recall and F1 at run time. The harness also runs a grader-precision-recall evaluation against a 60-item labelled corpus (`eval/corpus/grader.jsonl`) and reports per-class metrics, a five-by-six confusion matrix and a governance-framed caveat block. An evaluation-only cross-model backend (`python eval/run_eval.py --grader codex`) drives a local Codex CLI for a same-task different-model probe; it is never auto-selected and never run in CI. The numbers are corpus-dependent and not a claim of general accuracy. See [`eval/README.md`](../eval/README.md), which states the limits, the analytic nature of the contradicted-class zero for the offline heuristic, and the relevant prior art (McCoy, Pavlick and Linzen 2019; Gao et al. 2023) plainly. The corpora are regression and illustration seeds, not validated benchmarks.

## Tests

Stdlib only, no test dependencies. From the repo root:

```
python -m unittest discover -s tests -v
```

The suite covers detection (every trigger, inline and adjacent sourcing, the closed v0 false negative); the loop-safety guard; enforce-mode blocking; the verifier (mocked network, LLM-failure fallback, no-key path); the CBOM v0.2 schema (`actor_identity`, `classification_overrides`, `override_ledger_refs`); the four-state verdict including `NOT_ASSESSABLE`; the override ledger (SPEC-L8-S004 write-path validation, SPEC-L8-S003 separation-of-duties, INV-004 append-only triggers); the writer pack and clean-room generation; the five output-integrity gates G1-G5; the MCP server dispatch and the in-process API; the Claude Code Stop hook with loop-safety sentinel; the local LLM grader path; the per-layer status dashboard; and the grader-eval path (`sys.modules`-isolated under a unique spec name). The CI matrix runs the full suite on Python 3.11 through 3.13. See the CI badge in the README for the live count and pass status.

The rule that an internal error must never break the session is enforced throughout.

## Release status

Current increment: **v0.9.5**, a feature and hygiene patch over 0.9.4. It adds `warrantos init`, which scaffolds starter `context.json` and `actor.json` templates (with writer and reviewer deliberately distinct so the default does not trip separation of duties) so a first-time user does not have to reverse-engineer the six-role actor schema; the scaffolded files are verified end-to-end as valid `check` inputs. It also extends CI to a Windows and macOS matrix (closing the Linux-only gap that let the 0.9.3 `cp1252` crash ship), opts the pinned GitHub Actions into the Node 24 runtime ahead of the 2026-06-16 forced migration without unpinning their SHAs, and removes a stray empty `50)` file from the repository root. The build state is unchanged at 20 BUILT / 0 PARTIAL.

v0.9.4 was the first release published to PyPI since 0.9.2 (0.9.3 was tagged but never published). It folds the 0.9.3 fixes together with a set of pre-publish corrections: it single-sources the package version so WarrantOS can no longer misreport its own version (the module constant had drifted to 0.9.1 while the package metadata was a later 0.9.x; `pyproject.toml` now reads the version dynamically from `warrantos/__init__.py`), adds a zero-setup `warrantos demo` command and a `warrantos --version` flag (the demo fixtures ship as package data, so the front-door demo works from a clean install rather than pointing at `examples/`, which is not shipped in the wheel), and replaces the deprecated `datetime.utcnow()` in the provenance timestamp with a timezone-aware call of identical output. From 0.9.3 it carries the Windows `cp1252` unicode-crash fix (UTF-8 stdout/stderr so non-Latin-1 report content no longer raises), the `WARRANTOS_DB` environment variable wired into the `check` and `retention` `--db` defaults (previously documented but a no-op), the README corrected to the installed `warrantos.*` namespace and `provenance` console script, the reproducible public `examples/honest-demo` asserted in the gallery and CI, and `.claude-plugin/marketplace.json` so the documented `/plugin marketplace add` flow works. The build state is unchanged at 20 BUILT / 0 PARTIAL.

v0.9.5 builds on v0.9.4, which built on v0.9.3, which built on v0.9.2, which built on v0.9.1 (verdict-layer separation of duties, the cryptographic-verifiability wave: Merkle ledger, Ed25519 attestation, portable `.warrant`, offline and browser verifiers, AI scaffold-residue detection, append-only triggers installed by default, and pre-launch security hardening) and added: claim detection expanded from 5 to 11 triggers (decision, causal, comparative, superlative, named-body), per-profile unsupported-claim HOLD thresholds, improved verdict transparency, a `ClaudeCliGrader` that verifies through a Claude subscription with no API spend, the four formerly STARTER/NOT_BUILT rows moved to BUILT (G4, G5, Data Classification, Retention/Tombstones), a Python floor lifted to 3.11, and a CI smoke-test fix. v0.9.2 also closed the last three foundation rows (F-policy with the now-committed normative `docs/SPEC.md` and six-role registry, F-compliance with the ISO 42001 / NIST AI RMF self-assessment mapping, F-metrics with shadow-log aggregation), so all 20 rows are BUILT. See [`CHANGELOG.md`](../CHANGELOG.md) and [`STATUS.md`](STATUS.md). v0.9.5 is published to PyPI via Trusted Publishing. Remaining future work, stated plainly in the docs: an automated SPEC-ID conformance check, and the adopter-supplied sensitivity taxonomy and retention policy that the default Data Classification and Retention rows still require.
