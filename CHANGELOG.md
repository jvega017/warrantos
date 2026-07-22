# Changelog

All notable changes to WarrantOS (repository formerly named `claude-provenance`) are recorded here. The
project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and Semantic Versioning.

## [Unreleased]

**Candidate status:** the package source declares 0.11.0b2 and this checkout is
`warrantos-0.11.0b2-local-rc.1`, with no `v0.11.0b2` tag. It is not production qualified. The
canonical statement is `release-manifest.json`.

### Changed

- Repaired the candidate Quickstart, contributor setup and Action examples so
  checkout names, module paths, supported Python versions and newline-delimited
  paths match the shipped interfaces.
- Made `warrantos demo` retain its complete run, create `demo.warrant`, verify
  it against the exact draft bytes and print a repeatable verification command.
- Added release-truth enforcement for GitHub Action lock and Claude plugin
  version parity. Local candidate surfaces may identify the latest published
  version, but public promotion requires every surface to match the candidate.
- Added explicit claim-support states and linked source-snapshot/claim-binding
  schemas. The legacy `supported` CLI label remains for compatibility but now
  serialises as `support_state: citation_present`; it is not semantic proof.
- Added release-truth drift checks across code, manifest and public surfaces.
- Added a separate fail-closed public-publication truth profile so a local
  candidate tag cannot silently promote local-only status and acquisition claims.
- Packaged the source-snapshot and claim-binding JSON schemas as importable
  warrantos.schemas resources with a stdlib loader and copy-drift tests.
- Included the zero-backend browser verifier and release tooling in the source
  distribution, and added build attestations, CycloneDX output, resolved
  dependency audit and a three-OS by three-Python installed-package smoke matrix.
- Removed the unusable partial test tree from the sdist, included the Claude hook
  descriptor in source and wheel distributions, and made release CI install and
  smoke-test the exact built sdist before any TestPyPI promotion.


### Added

- **P0.3 Cryptographic Binding for v2 Warrant Bundles.** The checkpoint now binds `prose_sha256` and `cbom_sha256` into the Merkle root before signing, so tampering with prose or claims after attestation is cryptographically detectable. v2 checkpoints use `warrantos-checkpoint-v2`. Verification is backward-compatible; v0 and v1 bundles remain verifiable as `VALID` when integrity holds, but are now tagged `LEGACY_UNBOUND` in audit logs.

### Security

- **0.11.0b2 fail-closed semantic boundary.** Exact claim/source byte and locator checks
  now produce the evidence-only `passage_reproduced` state. Legacy caller
  strings supplied as reviewer/verdict are ignored and cannot mint
  `support_verified`; standalone WarrantOS does not yet validate an
  authenticated, hash-bound semantic-proof schema. This supersedes the earlier
  local 0.11.0b1 candidate.
- Added exact source-byte, text-extraction, claim-range and passage-range
  verification plus an installed `warrantos-evidence` workflow. A semantic
  verdict remains attributable to the declared reviewer rather than being
  presented as WarrantOS-detected truth.
- Added `warrantos-trust-root/v1` and fail-closed release verification against
  an externally pinned Ed25519 public key. No production key is bundled.

- **P0 Advisory: v0.10.0 and earlier warrants do not bind prose and CBOM to the Merkle root.** An adversary with access to a signed bundle can modify the prose or claims after attestation and the signature remains valid. The integrity check would fail (changed ledger) but a verifier who only spot-checks the signature would miss the mutation. Affected users should update to 0.11.0b2 or later, re-attest their bundles (which automatically upgrades to v2), and verify the new `prose_sha256` and `cbom_sha256` fields in the checkpoint. See `SECURITY.md` for details.

## [0.10.0] - 2026-07-08

The distribution wave. No change to the build state (still **20 BUILT / 0 PARTIAL**).

### Added

- **`warrantos tells`.** Opinionated AI-writing-style scanner, the sibling of `slop`: contrastive negation ("not X, but Y" and its variants), hedge stacking (two or more hedges in one sentence), em-dash and spaced en-dash punctuation, a high-precision AI filler lexicon, and formulaic paragraph-opener drumbeats (reported from the second occurrence). Same engine, flags, score formula and exit contract as `slop`; documented as house style, never authorship proof (docs/TELLS.md).
- **Hardened scaffold-bleed detection.** The canonical residue list gains four families: delivery meta-commentary ("Below is a", "Here's a breakdown"), sycophantic agreement ("You're absolutely right", "Great question"), offers to continue ("Feel free to", "Would you like me to"), and edit narration ("I've updated the"). Both the G1 boundary gate and `slop` consume the same list, so both surfaces gain the coverage at once.
- **`warrantos slop`.** Zero-config AI scaffold-residue scanner for Markdown, reStructuredText and plain-text trees: per-finding file, line, matched pattern and category (chat bleed, identity leak, sign-off residue, scaffold, placeholder), a density-based SLOP SCORE from 0.0 to 10.0, `--json`, `--badge` (shields.io URL) and an opt-in `--fail-over THRESHOLD` CI exit code. Precision-tuned: only near-unambiguous residue patterns fire, and every finding names the pattern that matched.
- **Composite GitHub Action (`action.yml`)** running `slop`, `check --ci`, or both over a repository, with SHA-pinned steps.
- **pre-commit hooks (`.pre-commit-hooks.yaml`)**: `warrantos-slop` on Markdown files and an opt-in manual-stage `warrantos-check`.
- **Claude Code plugin packaging**: `.claude-plugin/plugin.json` updated to the current schema, a `/warrant` slash command, and `docs/PLUGIN.md`.
- **`CITATION.cff`** so the repository is citeable and linked to the working paper (in preparation).
- **`docs/DISTRIBUTION.md`** with copy-paste snippets for every distribution surface.

### Changed

- **README rewritten to the 10-second contract**: real trimmed `warrantos demo` output up top, install one-liners, three usage wedges, and the full previous body preserved in `docs/FULL-OVERVIEW.md`.
- **`warrantos check` now accepts multiple drafts** (`warrantos check a.md b.md`); each draft gets its own run and the process exit code is the worst across drafts. Fixes the pre-commit multi-file invocation, which previously died with an argparse usage error.

## [0.9.5] - 2026-06-12

A feature and hygiene patch over 0.9.4. No change to the build state (still **20 BUILT / 0 PARTIAL**).

### Added

- **`warrantos init`.** Scaffolds starter `context.json` and `actor.json` templates so a first-time user does not have to reverse-engineer the actor-identity six-role schema. The writer and reviewer identities are deliberately different so the default scaffold does not trip the separation-of-duties rule, and the command prints the exact `check` invocation to run next. Existing files are never overwritten without `--force`. Verified end-to-end: the scaffolded files are accepted by `warrantos check`.

### Changed

- **CI now runs on Windows and macOS, not just Linux.** The `test` job is a 3-OS x 3-Python matrix. The 0.9.3 `cp1252` unicode crash shipped because CI only ran on Ubuntu and never exercised the Windows console path; that gap is closed.
- **GitHub Actions opted into the Node 24 runtime** via `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` ahead of GitHub's 2026-06-16 forced migration. The security-critical action SHA-pins are preserved; only the JS runtime they execute under changes.

### Fixed

- **Removed a stray empty `50)` file** accidentally committed to the repository root.

## [0.9.4] - 2026-06-12

A patch over 0.9.3, and the first release published to PyPI since 0.9.2: 0.9.3 was tagged but never published. No change to the build state (still **20 BUILT / 0 PARTIAL**); these are pre-publish correctness and packaging fixes folded in before the package reached PyPI.

### Fixed

- **WarrantOS no longer misreports its own version.** `warrantos/__init__.py` declared `__version__ = "0.9.1"` while the packaged metadata read a later `0.9.x`. A provenance tool reporting false provenance about itself is fixed: the version is single-sourced in `warrantos/__init__.py`, and `pyproject.toml` now reads it dynamically (`dynamic = ["version"]`), so the module constant and the packaged metadata can never drift apart again.
- **Naive timezone in a provenance timestamp.** The context bill-of-materials `created_utc` field used the deprecated `datetime.utcnow()` (a naive timestamp, slated for removal in a future Python). It now uses `datetime.now(timezone.utc)` with the identical `...Z` output format, removing the last deprecation warning.

### Added

- **`warrantos demo`.** A zero-setup first run: WarrantOS checks a bundled synthetic AI-style draft and returns a real `BLOCK` verdict (6 claims, 0 supported, 7 boundary violations). The fixtures ship as package data (`warrantos/demo_assets/`), so it works from a clean `pip install` with no repository checkout. This replaces the previous front-door command, which pointed at `examples/` (not shipped in the wheel) and therefore failed for installed users. The run is isolated to a temporary directory and never writes into the user's working tree.
- **`warrantos --version`.** Prints the version and exits, so the version that produced a verdict can be recorded.
- **Regression tests** (`tests/test_release_0_9_3_fixes.py`) pinning each of the above: version single-source, the `WARRANTOS_DB` default, `--version`, the bundled `demo`, and the cp1252 unicode-write path.

### Documentation

- **README front-door demo now works from a clean install.** The hero command is `warrantos demo`; the explicit `examples/honest-demo` command is retained for inspection and CI.

## [0.9.3] - 2026-06-11

A patch release over 0.9.2. Tagged with a GitHub Release but never published to PyPI; its fixes ship to PyPI as part of 0.9.4. No change to the build state (still **20 BUILT / 0 PARTIAL**); these are correctness, documentation, and packaging fixes.

### Fixed

- **Windows unicode crash in the CLI.** `stdout`/`stderr` are now forced to UTF-8, so the CLI no longer crashes when report content contains non-Latin-1 characters (Greek, mathematical symbols, smart quotes) on a Windows `cp1252` console.
- **`WARRANTOS_DB` is now actually read.** The `WARRANTOS_DB` environment variable now sets the `--db` default for the `check` and `retention` commands. It was documented but had been a no-op.

### Added

- **`.claude-plugin/marketplace.json`** so the documented `/plugin marketplace add` flow works. `plugin.json` version is aligned to the release.

### Changed

- **Stale Python classifiers dropped.** The `py3.8`-`3.10` classifiers are removed, matching the `requires-python = ">=3.11"` floor.

### Documentation

- **README clean-install accuracy.** References corrected to the installed `warrantos.*` namespace and the `provenance` console script, so a clean install matches the docs. A stale Release-status contradiction is fixed.
- **Reproducible public honest demo.** The private-brief anecdote is replaced with a reproducible public demo (`examples/honest-demo`), asserted in the gallery and CI.

## [0.9.2] - 2026-06-11

### Added

- **Claim detection expanded from 5 to 11 triggers** (`provenance.extract`). The detector now fires on six additional categories beyond the original year / percentage / magnitude / statute / attribution set: `decision` (must/shall/required/recommend, closing the salience/detection misalignment where decision-language sentences scored load-bearing but were not detected), `superlative` (largest/first/unprecedented), `causal` (caused/led to/results in/due to), `numeric_approx`, `named_body` (OECD/ABS/Treasury/ANAO/RBA and similar named authorities), and `comparison`. Causal, comparison, and named-body attribution carry +0.30 salience weight.
- **Per-profile unsupported-claim HOLD thresholds** (Layer 7 G2). A run can no longer return a bare `PASS` while a large fraction of its load-bearing claims are unsupported; each profile carries an unsupported-fraction threshold above which the verdict is downgraded to `HOLD`. The strict `audit` profile is the tightest.
- **Improved verdict transparency.** The verdict path surfaces why a verdict was reached (the triggering rule, the unsupported fraction, the separation-of-duties flag) rather than emitting a bare state.
- **`ClaudeCliGrader`** (`provenance.grade.ClaudeCliGrader`, grader id `claude-cli` / `fetch+claude-cli`). A subscription-over-API verification path that shells out to `claude --print`, so a user on a Claude subscription verifies through their plan rather than spending on `ANTHROPIC_API_KEY`. Falls back to the heuristic on any failure; never called from the blocking hook.

### Changed

- **G4 Safety & Contamination is now BUILT** (was STARTER). The generic starter pattern set is extended with policy-domain contamination patterns and a 24-item labelled corpus (`eval/corpus/contamination.jsonl`); `corpus_completeness` flips from `starter` to `domain-extended`. The list is still not exhaustive: production deployments SHOULD continue to extend it against their own documented threat model.
- **G5 Evaluation & Calibration is now BUILT** (was STARTER). `warrantos calibrate` runs the grader against the labelled eval corpus and writes `.warrant/calibration.json` (grader, corpus size, per-class recall, coverage estimate); `check_calibration()` accepts either live verdict rows (Brier-with-explicit-coverage) or the stored calibration file. Confidence coverage is typically 0 with the offline `HeuristicGrader`; per-class recall is the meaningful measure until an LLM grader supplies numeric confidence.
- **Foundation: Data Classification is now BUILT** (was NOT_BUILT) (`provenance.classification`). A 4-tier default registry mirrors the reference adopter's data gate; keyword heuristics (Cabinet, ministerial, legal advice, Crown Solicitor, HR/PIP/termination, $NNNM/B budget markers, credential patterns) are a documented STARTER set that production deployments SHALL extend with a domain taxonomy. Unmatched text defaults to Official, never silently Public.
- **Foundation: Retention & Deletion (tombstones) is now BUILT** (was NOT_BUILT) (`provenance.retention`, `schema/provenance.sql`). INV-011 is implemented as append-only tombstones: no hard delete. Expiry of a retention window appends a tombstone marking the run logically retired while preserving every ledger row (INV-004 append-only is never violated). Per-run windows are set at run creation or appended later via `set_window()` (latest override wins). Adopters still specify the window.
- **Build state moves from 13 BUILT / 3 PARTIAL / 2 STARTER / 2 NOT_BUILT** at v0.9.1 to **20 BUILT / 0 PARTIAL** at v0.9.2. The final three foundation rows closed: **F-policy** (the normative spec `docs/SPEC.md` plus a machine-readable six-role registry `warrantos/provenance/roles.py`), **F-compliance** (a self-assessment control mapping to ISO/IEC 42001 and the NIST AI RMF in `docs/COMPLIANCE.md` — a documented mapping, explicitly not certified conformance; an automated SPEC-ID conformance check remains future work), and **F-metrics** (shadow-log aggregation via `warrantos/provenance/metrics.py` and the `warrantos metrics` command). Status flips are conditional on the artefacts existing on disk, pinned by guard tests. Adopter-specific configuration (sensitivity tiers, retention windows) remains adopter-supplied by design.
- **Minimum supported Python lifted to 3.11** (`requires-python = ">=3.11"`). The CI matrix is now 3.11 / 3.12 / 3.13. Python 3.8 through 3.10 are dropped: they are end-of-life or near end-of-life and the code uses 3.11+ features.

### Fixed

- **CI smoke-test fix.** The CI smoke test is corrected to run against the supported Python matrix.

## [0.9.1] - 2026-06-10

### Added

- **AI assistant scaffold-residue detection** (Layer 7 G1). The prose-boundary scanner now catches the conversational and scaffold residue that bleeds from the chat into a final artefact, which is a core value proposition: AI self-reference ("as an AI language model"), capability disclaimers ("I cannot verify"), assistant openers ("Certainly!") and closers ("I hope this helps, let me know if"), delivery framing ("here's the revised version"), request acknowledgements ("as requested"), hedged provenance ("based on the information provided"), future-promise narration, and scaffold placeholders (`[TODO: ...]`, `lorem ipsum`, `TKTK`). On a representative leak document, detection went from 1 violation to 11. Verified to not false-positive on real academic and policy prose. Applies to final-prose, brief-light, and paper-full profiles; process-discussing profiles (audit, methodology, prompt-template) are unaffected.
- **Security hardening of the attestation chain** (fresh-critic + Codex + Gemini review). verify_warrant and the CLI/web verifier are now FAIL-CLOSED: an UNSIGNED or signature-UNAVAILABLE bundle is overall INVALID unless `--allow-unsigned` is passed explicitly (an attestation is no longer silently accepted without a verified signer). Merkle inclusion proofs now bind to `(index, size)` and reject replayed, wrong-size, or extra-step proofs. canonical serialisation rejects NaN/Infinity (a Python/JS divergence vector) and is pinned with known-answer vectors. Separation of duties is now also enforced on the MCP path (was CLI-only). 19 new adversarial tests; the web verifier is validated headless against signed and unsigned bundles with astral-plane unicode, matching the Python verifier byte for byte.
- **`warrantos attest` and `warrantos verify-external` CLI** (P1.3/P1.4 surface). `attest` bundles a completed check run into a portable `.warrant` (prose digest + CBOM + ledger entries + signed checkpoint); `verify-external` verifies it offline and exits non-zero on any failure, so it drops straight into CI. The integrity check needs no dependencies; signature attribution uses the `[attestation]` extra.
- **Ed25519 signed checkpoints and the `.warrant` verifiable artefact** (`provenance.attestation`, `provenance.warrant_bundle`). A checkpoint's Merkle root can now be Ed25519-signed, and `create_warrant()` bundles the prose digest, CBOM, the relevant ledger entries, and the signed checkpoint into a portable `.warrant` object. `verify_warrant()` checks it offline: the integrity half (recompute the Merkle root from the entries, match the checkpoint) is pure stdlib; only the signature trust-anchor needs the new `[attestation]` extra (`pip install "claude-provenance[attestation]"`), since the standard library ships no public-key signing. Verdicts: integrity VALID/INVALID, signature VALID/INVALID/UNKNOWN_KEY/UNSIGNED. Production adopters set `WARRANTOS_SIGNING_KEY`; the project ships no real default key. This makes the HTTPS analogy literal: a document anyone can verify offline.
- **Merkle-ised ledger core** (`provenance.merkle`, pure stdlib). A deterministic, RFC 6962 style Merkle tree (leaf/node domain separation, odd-node promotion) over the audit ledger. Provides the ledger integrity hash (one root digest that fixes the entire ordered ledger state; any insert, edit, delete, or reorder changes it) and the attestation root that signed checkpoints will commit to and external verifiers will check inclusion proofs against. Includes `MerkleTree`, `ledger_root()`, `build_checkpoint()`, and inclusion-proof verification. Foundation for the cryptographic-integrity wave (.warrant attestation + offline verifier).

### Security (pre-launch hardening, multi-agent review: Codex + Gemini + Opus + Fable)

- **SSRF and scheme guard in the URL verifier** (`provenance/verify.py`). `fetch_text` now refuses any non-`http(s)` scheme (closes `file://` and `ftp://` local-file disclosure) and resolves the host, rejecting any address that is not globally routable (`ipaddress.is_global`, which also closes RFC 6598 CGNAT `100.64.0.0/10`, loopback, link-local, private, reserved, IPv4-mapped IPv6). Redirects are re-validated per hop with a per-request cap. The check runs before any network call. DNS-rebinding TOCTOU and NAT64 are documented residuals for this opt-in path.
- **Web verifier XSS and fail-closed signature** (`web/verify.html`). All untrusted `.warrant` fields render via `textContent`, never `innerHTML`; a strict CSP blocks external requests. The signature model is now tri-state (`SIGNED_VALID` / `UNSIGNED` / `SIGNATURE_INVALID`): a present-but-corrupt signature is `SIGNATURE_INVALID` and forces overall `INVALID`, which the allow-unsigned toggle can never override.
- **Path containment across all CLI and MCP surfaces** (`provenance/pathguard.py`, `mcp_server.py`, `cli/warrantos_cli.py`). Caller-supplied `run_id` is regex-validated; every output and DB path is confined under its intended root by resolved-path containment (not string matching). Closes arbitrary file write to the ledger via `tool_warrant_record_override` and arbitrary file read via `tool_warrant_get_run`.
- **Supply chain: release and CI workflows pinned** (`.github/workflows/`). Every action is pinned to a full commit SHA; permissions are job-scoped (`id-token: write` only on the PyPI publish job, behind a protected environment).

### Changed

- **Separation of duties is now a verdict-layer property** (`consolidate_verdict()`, CLI and MCP). A same-actor writer/reviewer override downgrades a final-artefact profile to `HOLD` and the strict `audit` profile to `BLOCK`; an independent reviewer is required to certify `PASS` (SPEC-L8-S003). The `0.9.0b1` tag surfaced this in the footer only.
- **Append-only triggers installed by default** (`schema/provenance.sql`, hook and ledger-write schema paths). `BEFORE UPDATE` and `BEFORE DELETE` `RAISE(ABORT)` triggers ship on every ledger table on the default `warrantos check` and hook path, not only via an optional installer. INV-004 now matches the README claim; DELETE is covered as well as UPDATE.

### Documentation

- README, `docs/OVERVIEW.md`, `docs/STATUS.md` reconciled with `main`: separation of duties presented as wired (was "not wired"), the cryptographic-verifiability wave surfaced (new `docs/VERIFICATION.md`, README section, tooling-map entries), a new `F-integrity` status row (rollup now **13 BUILT**, was 12), and the append-only claim scoped to the SQLite ledger.

## [0.9.0b1] - 2026-06-06

### Added — v0.9 beta-trial finalisation

- **`prompt-template` profile** for G1 (`_PROFILE_RULES`). Empirical calibration: on 2026-05-27 all 10 morning brief-prompt templates triggered BLOCK with 29-59 violations under `brief-light`. The new profile drops the lexical-residue rules because the input IS the rule-list discussion, not a final artefact. Re-tested: BLOCK → HOLD with 0 violations (HOLDs are genuine unsupported-claim signal). Shadow observer default updated to use `prompt-template`.
- **L3 ledger persistence** (`provenance.ledger_write.persist_context_transform`). Closes SPEC-L3-N001 SHALL: every derived requirement now produces a `context_transform` ledger row. New module `provenance/ledger_write.py` houses write-path helpers (kept separate from read-only `provenance/ledger.py`).
- **INV-004 storage-level append-only triggers** (`provenance.ledger_write.enable_append_only_triggers`). SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers RAISE(ABORT) on every audit-bearing table, so a row can be inserted but never modified or removed. INV-004 moves from ASSERTED to ENFORCED. A DELETE is as damaging to a tamper-evident ledger as an UPDATE, so both are blocked. The `human_override` triggers are installed automatically when the override DB is opened.
- **L8 escalation-path taxonomy** (`provenance.overrides`). Eight canonical paths documented (none recorded / peer_review / director_signoff / executive_signoff / cabinet_office / legal_review / second_coder_review / external_auditor). Non-canonical values accepted but tagged with a `custom:` prefix. `list_canonical_escalation_paths()` exposes the set.
- **`warrantos status` command** (`provenance.status` + new CLI subcommand). Reports per-layer conformance against the 8 architecture layers plus the foundation row. Status values: BUILT / PARTIAL / STARTER / NOT_BUILT. Three output formats: text (default), `--json`, `--markdown`. `docs/STATUS.md` is the committed Markdown render.
- **Version bump** in `pyproject.toml` to `0.9.0b1`.

### Still deferred (post-v0.9, require Juan's domain input)

These four items remain NOT_BUILT or STARTER. They cannot be fabricated; the adopter must supply the domain-specific input:

- **SHALL-level classifier corpus (N >= 50 per class)** — SPEC-L1-S006 promotion to SHALL.
- **G4 production threat-model corpus** — replaces the starter pattern list with a documented adversarial corpus.
- **Foundation: Data Classification (sensitivity tiers)** — adopter declares the sensitivity taxonomy.
- **Foundation: Retention & Deletion (tombstones)** — adopter specifies retention windows; INV-011 promotes from PROPOSITION when implemented.

### Added — v0.8 no-API-key verification paths

- **LocalLLMGrader** (`provenance.grade.LocalLLMGrader`). Posts to an
  OpenAI-compatible `/v1/chat/completions` endpoint so the verifier
  can produce `contradicted` verdicts using Ollama, llama.cpp's
  server, LM Studio, vLLM, or any compatible local-LLM tool. Zero
  external network egress; zero Anthropic API cost. Activated via
  `PROVENANCE_LOCAL_GRADER_URL`; falls back to HeuristicGrader on any
  failure. Stdlib only (uses `urllib.request`).
- **`get_grader()` selection order**: LocalLLMGrader if
  `PROVENANCE_LOCAL_GRADER_URL` is set; LLMGrader if
  `ANTHROPIC_API_KEY` is set; HeuristicGrader otherwise. The local
  path wins over the Anthropic path when both are configured because
  the local choice indicates an explicit preference for zero data
  egress.
- **Claude Code Stop hook** (`hooks/claude_code_verify_hook.py`,
  entry point `warrantos-verify-hook`). When wired to
  `~/.claude/settings.json` under `hooks.Stop`, the hook reads the
  latest run's verdict, identifies unsupported load-bearing claims,
  and hands them back to the same Claude Code session via stderr +
  exit code 2. The session verifies them in the next turn using its
  existing auth. Loop-safe: a sentinel file in `.warrant/` prevents
  re-blocking the same hold set twice.
- **docs/NO-API-KEY.md**: complete guide to verifying claims without
  an Anthropic API key, with a decision tree (local LLM vs Claude
  Code hook vs MCP sampling) and configuration recipes per path.
- **MCP sampling design**: documented as the canonical "no separate
  API key" path; implementation is a v0.9 deferral with the gap
  named honestly in NO-API-KEY.md §3 and in this CHANGELOG.

### Documentation updates for v0.8

- `pyproject.toml` adds the `warrantos-verify-hook` entry point.
- `docs/QUICKSTART.md` links to NO-API-KEY.md.
- `docs/COST.md` lists the local-LLM and Claude-Code-hook paths as
  zero-API-cost options for `--verify`.
- `docs/MCP-CONFIG.md` cross-references NO-API-KEY.md for the
  three no-Anthropic-key paths.

### Still deferred (post-v0.8)

- **MCP sampling implementation**: the design lives in
  NO-API-KEY.md §3. Implementation requires a new
  `MCPSamplingGrader`, a `warrant_check(use_mcp_sampling=True)`
  pathway, and host-side permission UX work. Tracked as v0.9.

### Added — v0.7 beta-ready packaging

- **pyproject.toml** with three console entry points: `warrantos`
  (the integration CLI), `provenance` (the legacy CLI), and
  `warrantos-mcp` (the MCP server). Zero required dependencies; the
  `mcp` package is an opt-in extra (`pip install
  "claude-provenance[mcp]"`). Targets Python 3.8 - 3.13. Build status
  marked `4 - Beta`.
- **examples/quickstart-demo/** with `draft.md`, `context.json`,
  `actor.json`, and a README walking through the expected HOLD
  verdict line-by-line. The bundled command exercises Layer 1
  classification, Layer 4 admissibility, Layer 7 G1 boundary, Layer
  7 G2 detection, CBOM assembly, and the four-state consolidator;
  G2 verification (`--verify`) and G3 (`--writer-model`/
  `--verifier-model`) are opt-in flags. G4 and G5 ship as STARTER
  and are not invoked by the bundled demo.
- **docs/QUICKSTART.md** — install + demo + the four-verdict table +
  the threat-model statement (what WarrantOS does and does NOT
  claim).
- **docs/MCP-CONFIG.md** — exact Claude Code and Claude Desktop
  config snippets, sanity-check instructions, cost-aware defaults,
  and troubleshooting.
- **docs/COST.md** — explicit cost matrix: what runs locally (free)
  vs what consumes Anthropic API credits, the three spend-control
  flags, recommended profiles per use case (CI, daily brief,
  Cabinet brief, academic paper), and order-of-magnitude pricing.
- **Cost-control flags on `warrantos check`**: `--max-verify-claims
  N` caps verifier spend by descending salience; `--salience-min
  FLOAT` filters out low-salience claims before they reach the
  verifier. Both report what was skipped in the new
  `verifier_skipped` field so an auditor can see the trade-off.
- **README quickstart** at the top with `pip install` + demo command
  + pointers to the four new docs. Beta status, Python 3.8+, and
  stdlib-only shields.

### Added — v0.6 deferred-list close-out

- **Layer 7 G3 wired into the warrantos CLI**
  (`cli/warrantos_cli.py`). New `--writer-model` and
  `--verifier-model` flags trigger `check_self_grounding`. The result
  lands in the report's `g3_self_grounding` field. When the verdict
  is `requires_external_grounding` or `family_match`, the reason is
  appended to the verdict reasons list as a `FLAG (G3 informational)`
  annotation. SPEC-L7-N003 says SHALL FLAG, not SHALL BLOCK; G3
  therefore does NOT promote PASS to HOLD/BLOCK.
- **Layer 7 G4 contamination scan** (`provenance.gates.check_contamination`).
  Replaces the v0.5 NotImplementedError stub with a regex scan
  against a documented starter pattern list (ignore-instructions,
  you-are-now, system-role inject, chat-template open/close,
  override-role, end-of-prompt marker, repeat-above). Returns a
  `ContaminationResult` with `verdict` in {pass, blocked}. The list
  is explicitly a `starter` corpus; the result carries a note that
  production deployments SHALL extend it.
- **Layer 7 G5 calibration** (`provenance.gates.check_calibration`).
  Replaces the v0.5 NotImplementedError stub with a Brier-score
  implementation that reports explicit coverage: total verdicts,
  typed rows ({verified, contradicted}), with-confidence rows, and
  the Brier score over the with-confidence subset. When coverage is
  zero (the offline-heuristic case), `brier` is None and the
  honest-disclosure note explains why. SPEC-L7-R002.
- **Layer 6 subprocess isolation**
  (`provenance.clean_room.run_clean_room_subprocess`). Level 2
  conformance for SPEC-L6-R001. Spawns a subprocess with a scrubbed
  environment (PATH, SYSTEMROOT, TEMP, TMP, LANG, LC_ALL, HOME,
  USERPROFILE, PYTHONIOENCODING; everything else is suppressed).
  Delivers the InvocationPlan via stdin as JSON. Returns a
  SubprocessRunResult with exit code, stdout, stderr, timed_out
  flag, and the count of scrubbed-vs-kept env keys. Caller-supplied
  `extra_env_allowlist` is the explicit path for threading a
  credential (e.g. `ANTHROPIC_API_KEY`) through.
- **SPEC-L1-S006 classifier corpus scaffold**
  (`eval/classifier-corpus/seeds.jsonl`,
  `eval/run_classifier_corpus.py`). Seed corpus with one
  representative example per class (N = 1 per class) and a runner
  that reports per-class precision and exits non-zero on regression.
  SPEC-L1-S006 SHOULD level reached for v0.6; v0.3 promotion to
  SHALL still requires N >= 50 per class.

### Still deferred (post-v0.6)

- **Promotion of SPEC-L1-S006 from SHOULD to SHALL**: requires
  authoring N >= 50 labelled examples per class. Not fabricated;
  awaits human authoring.
- **G3 verdict promotion (BLOCK or HOLD)**: SPEC says SHALL FLAG.
  Promoting to BLOCK would require a separate decision and SPEC
  amendment.
- **G4 production pattern list**: the starter set fires on the
  obvious patterns; a production corpus requires red-team review
  and threat-model authoring.
- **G5 LLM-grader confidence wiring**: the heuristic verifier cannot
  emit confidence by construction; using the LLM grader for every
  claim is gated by ANTHROPIC_API_KEY and cost.

### Added — v0.5 follow-ups (Layer 5, Layer 6, Layer 7 G3, docs)

- **Layer 5 clean-room writer pack** (`provenance/writer_pack.py`).
  `compile_writer_pack()` builds the five required sections per SPEC
  §6.2: Clean Brief (derived requirements only; no raw feedback),
  Approved Sources (admitted empirical evidence), Style Rules (from
  style signals), Acceptance Tests (default Layer 7 G1/G2/G3
  coverage), and Banned Residue List (boundary rules promoted from
  validation rules). Enforces SPEC-L4-S001 at the writer entry point:
  any item whose `can_be_seen_by` excludes `clean_room_writer` is
  rejected and the count is reported on the pack so the auditor can
  see how much material was withheld from the writer.
- **Layer 6 clean-room generation (discipline mode)**
  (`provenance/clean_room.py`). `prepare_invocation()` builds an
  `InvocationPlan` from a writer pack and a writer-model identifier.
  Refuses arbitrary context kwargs at the API surface: only
  `writer_pack`, `writer_model`, `writer_role`, `max_tokens`, and
  `temperature` are accepted. Any other key (e.g. `context`,
  `system_prompt`, `feedback`) raises ValueError. This is the
  SPEC-L6-S001 discipline; subprocess isolation (SPEC-L6-R001) is
  deferred to Level 2.
- **Layer 7 G3 self-grounding gate** (`provenance/gates.py`).
  `check_self_grounding(writer_model, verifier_model)` returns a
  `SelfGroundingResult` with verdict in {`ok`, `family_match`,
  `requires_external_grounding`}. Documented model-family registry
  resolves Claude, GPT, Gemini, Llama, Grok, Mistral, and Cohere
  identifiers (SPEC-L7-N004). INV-006 fires when writer and verifier
  identifiers match (case-insensitively). `family_match` is permitted
  per SPEC-L7-N004 but recorded for CBOM visibility.
- **docs/OVERVIEW.md** — a fresh-reader's tour of the repository:
  the eight-layer model, the four governance properties, the one
  command that connects every layer, what is built today, and what
  is explicitly NOT built with the rationale for each.

### Deferred from v0.5 (with rationale)

- **Layer 7 G4 (contamination)**: NOT BUILT. Requires a documented
  prompt-injection threat model and a labelled pattern corpus.
  Neither exists yet. The `check_contamination()` stub raises
  `NotImplementedError` so callers detect the gap rather than receive
  a silent pass.
- **Layer 7 G5 (calibration)**: NOT BUILT. Requires the verifier
  surface to emit a numeric confidence per claim. The offline
  heuristic verifier emits None on most paths, which makes a Brier
  score meaningless. `check_calibration()` raises.
- **Layer 6 subprocess isolation**: NOT BUILT. Discipline mode ships;
  subprocess isolation is Level 2 conformance work.
- **G3 wiring into the consolidated verdict**: BUILT as a callable
  module, NOT WIRED into `cli/warrantos_cli.py`'s consolidated
  verdict. Wiring requires deciding whether `requires_external_grounding`
  should HOLD or BLOCK; SPEC-L7-N003 says SHALL FLAG (not SHALL
  BLOCK), so the prudent default is informational only. The flag is
  available via `provenance.gates.check_self_grounding()`; CLI
  integration is a deliberate next-version decision.
- **SPEC-L1-S006 labelled classifier corpus**: NOT BUILT. Requires
  authored examples per class (N >= 50). Not fabricated. Awaits
  human-authored corpus.

### Added — Path X3 (WarrantOS upstream integration leg)

- **CBOM v0.2 schema additions** (SPEC-F-S002, SPEC-L1-S005, §10.3).
  `provenance.cbom.CBOM` carries `actor_identity` (role to identity
  map), `classification_overrides` (list of override rows referencing
  the human_override ledger), and `override_ledger_refs` (list of
  override ids). All three fields default to empty so v0.1 callers
  continue to work unchanged. Schema name remains `warrantos-cbom/v1`
  per INV-007 (additive change only).
- **Structured human override ledger** (SPEC-L8-S002 / SPEC-L8-S003 /
  SPEC-L8-S004). `provenance.overrides.record_override()` writes a
  row to a new `human_override` SQLite table. Empty `risk_accepted`
  or `compensating_control` SHALL block the override at the write
  path; the override does not exist if it cannot be recorded.
  `enforce_single_actor_rule()` implements SPEC-L8-S003: when
  reviewer identity matches the writer-pack actor and the artefact
  role is `final-prose`, the role is downgraded to `draft`.
- **Review-role registry and SPEC-L1-S005 classification gate**.
  `provenance.review_roles.REVIEW_ROLE_REGISTRY` enumerates eight
  canonical review-role agent names (`fresh-critic`,
  `evidence-auditor`, `policy-red-team`, `paper-editor`,
  `codex-rescue`, `policy-debate`, `claim-verify`,
  `rejection-handler`). When `classify_context()` receives a
  `source_agent` in the registry, classification is forced to
  `review_finding` ahead of the rule-based decision tree. This
  closes the Wave A policy-red-team A1 classification-laundering
  attack: a review_finding cannot be silently reclassified to
  `private_reasoning` merely because its text contains a "chain of
  thought" keyword. To override the gate, callers must supply a
  recorded override id via `classify_with_override()`.
- **Reader-facing override footer** (SPEC-L8-S005).
  `provenance.footer.render_override_footer()` emits a Markdown
  block listing every override applied to a run. Empty list returns
  the empty string. Single-actor downgrades carry a visible marker.
- **Integration CLI** (`cli/warrantos_cli.py`). A single command that
  runs Layer 1 classification with SPEC-L1-S005 source_agent gating,
  Layer 7 G1 prose-boundary scan, Layer 7 G2 claim detection with
  optional verifier, and CBOM v0.2 assembly, then emits a four-state
  consolidated verdict (PASS, HOLD, BLOCK, NOT_ASSESSABLE). The
  `NOT_ASSESSABLE` state closes a Codex adversarial-review concern:
  a final-prose artefact cannot certify as PASS without
  `actor_identity` to support the override/identity leg of the
  coupling thesis. Per-run JSON artefacts are written to
  `.warrant/runs/<run_id>/`.
- **MCP server wrapper** (`provenance/mcp_server.py`, Path X4-A).
  Exposes `warrant_check`, `warrant_classify`,
  `warrant_record_override`, and `warrant_get_run` as MCP tools. The
  `mcp` SDK is an optional dependency: the module imports cleanly
  without it; only `run_stdio_server()` raises ImportError with an
  install message. In-process dispatch via `call_tool_in_process()`
  lets callers use the pipeline as a Python API.
- **Shadow-mode observer** (`tools/warrantos-shadow-observe.py`,
  Path X4-B). Read-only observer that runs the warrantos pipeline
  over an already-published brief artefact and appends one
  JSON-line summary per run to a shadow log. Never blocks anything.
  Never modifies any production script. Includes a "NOT enforced"
  note in every row.

### Fixed

- `cli/provenance_cli.py` lacked `sys.path` manipulation, so
  `import provenance.context_admissibility` failed when the CLI was
  invoked as a subprocess; the lazy import caught the
  `ModuleNotFoundError` and emitted "context admissibility module is
  not available." with no output. Added the four-line
  `sys.path.insert` pattern; both `tests/test_context_cli.py`
  failures cleared.
- `tests.test_context_admissibility.test_admissibility_summary_is_stable`
  asserted the v0.1 seven-key dict shape; `admissibility_summary()`
  now emits ten keys (the seven v0.1 keys plus `can_be_seen_by`,
  `cannot_be_seen_by`, `prohibited_use`). Updated the assertion to
  the canonical v0.2 shape.

### Documentation

- `docs/PROBLEM-STACK.md` (in WarrantOS project folder, not yet in
  the public repo) carries the integration thesis: WarrantOS is the
  integration of six diagnosed failure modes from six papers, with
  a cross-cutting set of invariants enforcing the coupling.
  Provenance Ledger, Drift, LOGOS, Borrowed-Counterfactuals, Flagship
  2026, and MAG each contribute one failure mode and one layer.

### Test coverage

- 341 tests, 0 failures, 0 errors at branch tip.
- Coverage added for the v0.2 CBOM fields, override schema, review
  role registry, override footer rendering, full pipeline integration,
  MCP server tool dispatch, and the shadow observer.

### Honest limits carried forward

- The offline heuristic verifier cannot emit `contradicted` by
  construction. The BLOCK-on-contradicted branch fires only when an
  LLM grader is configured via `ANTHROPIC_API_KEY` or a callable
  cross-model backend is supplied.
- Layer 5 writer pack and Layer 6 clean-room generation are NOT
  BUILT. The harness operates over an already-written draft. Layer
  5/6 are a later path.
- Layer 7 G3 (self-grounding), G4 (contamination), and G5
  (calibration) gates are NOT BUILT.
- The SPEC-L1-S006 labelled classifier corpus (N >= 50 per class)
  does not yet exist. SPEC-v0.2 marks this as a SHOULD; promoting to
  SHALL is a v0.3 deliverable.

## [0.3.0] — 2026-05-21

- Cross-model grader (`--grader codex` evaluation-only backend).
- Governance reframe of eval documentation against HANS and ALCE.
- Per-class P/R/F1 over a 60-item labelled corpus.

## [0.2.0]

- Out-of-band verifier with fetch + LLM grading.
- Two-axis detection/verification model.
- Standalone CLI with CI mode.
- Epistemic-debt metric and evidence-matrix export.
- Salience weighting.
- Evaluation harness.

## [0.1.0]

- Heuristic detector with claim extraction.
- SQLite ledger.
- Report and enforce modes.
