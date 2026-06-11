# Limitations

WarrantOS enforces accountability; it does not arbitrate truth. A tool whose
thesis is provenance would fail its own audit if it overstated its assurance, so
the limits are stated plainly here. Read this before relying on a verdict.

## What WarrantOS does and does not claim

- It checks that every load-bearing claim carries a **warrant**: a source, an
  explicit `[CITE NEEDED]`, or a `BLOCK` on the record. It does **not** verify
  that a cited source actually supports the claim unless an LLM grader is
  configured, and even then within that grader's limits.
- It is **not** a hallucination detector or a fact-checker. A `PASS` means the
  artefact met the accountability gates, not that it is true.

## Verifier and grading limits

- The default **HeuristicGrader is offline and free** and cannot emit
  `contradicted`. The `BLOCK`-on-contradiction path is only reachable with a
  configured LLM grader (`--writer-model` / `--verifier-model` or
  `ANTHROPIC_API_KEY`). Without one, contradiction is not detected.
- Citation detection keys on inline URLs, `[CITE NEEDED]`, and APA-style
  `(Author, Year)` markers. It does **not** yet recognise numeric `[12]`
  citations, footnotes, or a standalone bibliography, so it **over-flags** prose
  that relies on those styles. A bare `(Author, Year)` is recognised as a
  citation but cannot be machine-checked by the offline verifier, which reports
  it `unverifiable`. A dedicated academic-citation profile that resolves
  author-year to a source is planned.
- Cross-model grader reproducibility was measured at kappa = 0.55 (moderate
  agreement) in the label-reproducibility probe. Treat LLM-grader confidence
  accordingly; it is a signal, not a verdict.

## Build state

This is **v0.9.1**. Two layers are explicit `NOT_BUILT` v1.0 deferrals
that require domain input from the adopter and cannot be fabricated:
Data Classification (a sensitivity taxonomy) and Retention/Tombstones. Two more
are `STARTER` (Safety/Contamination, Evaluation/Calibration) and need extension
before production use. See [`STATUS.md`](STATUS.md) for the per-layer state.

## Attestation and cryptography

- The integrity core (`provenance.merkle`) and `.warrant` integrity verification
  are stdlib-only and need no key. **Signing** an attestation requires the
  optional `[attestation]` extra (Ed25519); without it, a bundle is unsigned.
- An **unsigned** bundle is integrity-verifiable but carries no attribution.
  Verification is **fail-closed**: an unsigned or unverifiable signature is
  overall `INVALID` unless `--allow-unsigned` is passed explicitly.
- **Trust model.** The signing key is held by the operator, who can therefore
  regenerate and re-sign the entire ledger. Tamper-evidence holds against a
  checkpoint or signer public key the relying party obtained out of band
  beforehand, not against the operator themselves. There is no external
  transparency log or trusted timestamp; an adopter who needs non-repudiation
  against the operator must anchor checkpoints externally. The browser verifier
  shows a good signature under an **unpinned** key as `SIGNED_UNPINNED` (amber,
  not a green pass) and a browser without Ed25519 as `CANNOT_VERIFY` (not a
  tamper failure).
- The `.warrant` envelope and canonical serialisation are a project-defined
  format. They are pinned with known-answer vectors and a Python/JS differential
  check, but they are not yet a published, versioned standard. A migration to an
  established signed-statement format (DSSE or COSE) is under consideration.

## Scope

WarrantOS governs the **artefact, not the model**, at the writer's desk, on one
document, before it ships. It is not an MLOps observability platform, a
governance suite, or a compliance product for any specific regulation. It runs
locally with no telemetry and no network calls in the default path.
