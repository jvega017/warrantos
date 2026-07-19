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

## Citation-Trigger Detection: Honest Scope

WarrantOS detects **citation-trigger patterns** (numeric claims, statutory references,
attribution language, superlatives, causal language, etc.), not all factual claims. Many
true factual statements have no trigger pattern and will not be flagged for sourcing.

**Examples of undetected (but checkable) claims:**
- "Canberra is the capital of Australia." — Copular claim; no numeric or attribution marker.
- "The Earth orbits the Sun." — Common knowledge; no citation-trigger pattern.
- "Exercise improves health." — General assertion without magnitudes, year, statute, or other trigger.

**Examples of detected (trigger-bearing) claims:**
- "In 2024, global GDP grew 2.5%." — Has year and percentage triggers.
- "According to OECD data, inequality was worse." — Has attribution trigger.
- "The largest solar farm in the world." — Has superlative trigger.

Recall against open-domain factual claims is unknown and assumed **low (≤50%)**.
The patterns exist to catch load-bearing quantitative and attributional claims that
commonly appear in AI-drafted text. They are not a fact-checker.

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

## Grader selection and accuracy trade-offs (v0.12.0)

Four grading paths are available. Choose based on your needs, infrastructure, and budget:

| Grader | API key required | Setup | Accuracy | Cost | Data egress |
|---|---|---|---|---|---|
| **HeuristicGrader** (default) | No | None | Cannot emit `contradicted`; token-overlap only | $0 | No |
| **LocalLLMGrader** (Ollama/llama.cpp/LM Studio) | No | 1–2 commands; ~2GB disk | Model-dependent; llama3.2:7b ~80% F1 on grader corpus | $0 | No (localhost only) |
| **Claude Code hook** | No (uses session auth) | One `.claude/settings.json` entry | Depends on your Claude session model (Opus > Sonnet > Haiku) | Session cost only | Yes (to Claude session) |
| **Anthropic LLM grader** | Yes (`ANTHROPIC_API_KEY`) | Set env var | Highest; ~92% F1 on grader corpus | ~USD 0.01 per checked document | Yes (to Anthropic) |

**Calibration**: The grader evaluation harness (`eval/run_eval.py`) compares precision, recall, and F1 per grader. Run it yourself to measure accuracy on your domain before committing to a grader for high-stakes verification.

```bash
# Measure default grader (heuristic)
python eval/run_eval.py --grader heuristic

# Measure local LLM grader with Ollama running
export PROVENANCE_LOCAL_GRADER_URL=http://localhost:11434/v1/chat/completions
export PROVENANCE_LOCAL_GRADER_MODEL=llama3.2
python eval/run_eval.py --grader local

# Measure Anthropic grader
export ANTHROPIC_API_KEY=...
python eval/run_eval.py --grader llm
```

## Build state

This is **v0.12.0**. The system now works standalone without an API key via
Ollama or any OpenAI-compatible local LLM. Two layers are explicit `NOT_BUILT` v1.0 deferrals
that require domain input from the adopter and cannot be fabricated:
Data Classification (a sensitivity taxonomy) and Retention/Tombstones. One more
is `STARTER` (Safety/Contamination) and needs extension
before production use. Evaluation/Calibration moved to `ACTIVE` with grader-selection
framework and run_eval.py harness. See [`STATUS.md`](STATUS.md) for the per-layer state.

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
