# WarrantOS critical analysis and improvement plan — 2026-06-24

Prepared 2026-06-24. This document is a *second-pass* critical analysis. It is
written against the live v0.9.5 tree (not the docs) and is meant to be read
alongside two prior inputs: the external "B+ / 87" assessment, and the
2026-06-11 roadmap that drove the Phase-1 detection and verdict work (now
shipped). It does three things:

1. Records what the codebase actually does *today*, verified by reading and
   running it — not what the README says it does.
2. Names the findings the B+ assessment did not surface, because they only
   show up when you run the suite and read the mirrored source.
3. Lays out a phased plan whose ordering is deliberately inverted from the
   usual one: **the project's own credibility defects come before its feature
   gaps.** A provenance tool is judged first on whether its own claims hold.

## BLUF

The B+ assessment is fair and its weakness list is accurate, but it graded the
*documentation*, which is exemplary. Running the tree surfaces a class of
finding the docs paper over. The single highest-value fix is no longer
detection recall (Phase-1 closed the worst of that). It is **closing the gap
between what the project claims about itself and what a clean checkout
actually does** — because that gap is exactly the failure mode WarrantOS exists
to make expensive in *other people's* documents. Three concrete instances:

- `python -m unittest discover -s tests` does **not** pass on a clean checkout.
  It reports 7 errors. The README frames the suite as "stdlib only, no test
  dependencies" with a green CI badge; both are true only when the optional
  `[attestation]` extra is present *and* its native crypto backend is healthy.
  When `cryptography` is installed but its backend is broken, two test modules
  fail at **import time** (`_FailedTest`) and the attest-CLI tests error rather
  than skip.
- Claim detection is maintained as **two hand-synchronised copies** of the same
  regex set (`warrantos/provenance/extract.py` and
  `warrantos/hooks/provenance_check.py`), kept in agreement only by a comment
  that says "update the hook first and mirror here." This is a latent
  correctness bug in the load-bearing detection path.
- The contamination gate (G4) ships policy-domain patterns
  (`authority_impersonation`, `legislative_injection`,
  `classification_laundering`) that match the *legitimate* vocabulary of the
  exact documents this tool targets — ministerial briefs, statutory references.
  These will fire on real policy prose, and there is no false-positive
  measurement on in-domain text.

Fix those first (Phase 0). They are cheap, they are the project's own standard
applied to itself, and they de-risk everything downstream. Then raise the
detection ceiling honestly (Phase 1), make verification useful without spend
(Phase 2), right-size the compliance and evaluation claims (Phase 3), and close
the executability and adoption gaps (Phase 4).

## What I verified by running the tree

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` on this checkout | **708 tests, 7 errors, 1 skipped** — not green |
| Root cause of the 7 errors | `test_attestation`, `test_warrant_bundle` fail at import; `test_attest_cli` (5) error — all from a broken `cryptography` backend (`No module named '_cffi_backend'`) |
| Why the guard misses it | `test_attest_cli.setUp` catches `attestation.AttestationUnavailable`, but a half-broken backend raises `pyo3_runtime.PanicException`, which is not caught; the two `_FailedTest` modules call `generate_keypair()` at module import, outside any guard |
| Phase-1 verdict thresholds | **Shipped.** `_PROFILE_UNSUPPORTED_THRESHOLD` is live in `consolidate_verdict()`; an audit run can no longer return a bare PASS with all claims unsupported |
| Claim triggers | **11 regex triggers, confirmed.** `decision` matches `must|shall|requires|recommend`; `superlative` matches `first|only|most|best` — both high-recall and high-false-positive on ordinary prose |
| Detection source of truth | **Duplicated.** `extract.py` is a hand-copy of `hooks/provenance_check.py`; no test asserts they stay identical |
| Build state | 20 BUILT / 0 PARTIAL, as documented |

## What the B+ assessment got right, and where it stops

The external assessment's eight weaknesses (heuristic detection ceiling,
lexical scaffold detection, weak no-key verification, small corpora, compliance
optics, no adoption evidence, partially-theoretical L5/L6, starter-grade
classification/retention) are all real and all correctly characterised. Nothing
below contradicts them.

Where it stops: it is a *documentation and architecture* review. It reads the
README, the SPEC, STATUS.md, and skims source. It therefore credits the project
for properties the docs assert — "341+ tests, stdlib-only", "20 BUILT / 0
PARTIAL" — without independently reproducing them. The grade would survive the
findings above, but a B+ on a tool whose entire thesis is "verify, don't trust"
should be conditional on the tool passing its own bar. Right now it does not,
out of the box.

## The phased plan

### Phase 0 — Make the project pass its own bar (1 session, highest priority)

Rationale: every item here is the WarrantOS thesis applied to WarrantOS. None
is speculative; each is a verified defect with a known fix.

**0.1 Make the suite green on a clean checkout, with and without extras.**
- Guard the attestation/bundle test modules so they `skipUnless` a *healthy*
  crypto backend is importable — catch `Exception` (or do a probe import of
  `_cffi_backend` / a trial `generate_keypair()` in a module-level
  `try/except` that sets a `_HAVE_ATTEST` flag), not just
  `AttestationUnavailable`. Move the import-time `generate_keypair()` in
  `test_attestation.py` and `test_warrant_bundle.py` behind that flag so they
  skip instead of becoming `_FailedTest`.
- Files: `tests/test_attest_cli.py`, `tests/test_attestation.py`,
  `tests/test_warrant_bundle.py`. Add a shared `tests/_attest_support.py`
  helper so the probe lives in one place.
- Acceptance: `python -m unittest discover -s tests` exits 0 with **zero**
  optional extras installed (all attestation tests SKIP, not ERROR), and again
  exits 0 with `[attestation]` healthy (they RUN).

**0.2 Add a CI lane that proves the stdlib-only claim.**
- The 0.9.3 `cp1252` crash shipped because CI was Linux-only; the analogous gap
  here is that CI presumably installs `[attestation]`, so the
  no-extras-clean-pass property is never exercised. Add a matrix lane that runs
  the suite in a venv with **no** extras. This is what makes the README's
  "stdlib only, no test dependencies" line *true and enforced* rather than
  aspirational.
- Files: `.github/workflows/ci.yml`.

**0.3 Single-source the detection patterns.**
- Make `hooks/provenance_check.py` import `CLAIM_TRIGGERS`, `CITATION_MARKERS`,
  `CITE_NEEDED`, and `sentences()` from a shared module (either `extract.py`
  directly, or a new dependency-free `warrantos/provenance/_patterns.py` that
  both import). The hook's only hard constraint is stdlib-only and no network;
  `extract.py` is already both, so the import is safe.
- If a true import is undesirable for hook-isolation reasons, the minimum
  acceptable fix is a test that asserts the two pattern lists are byte-identical
  so silent drift becomes a CI failure.
- Files: `warrantos/hooks/provenance_check.py`, `warrantos/provenance/extract.py`
  (or new `_patterns.py`), `tests/test_provenance.py`.
- Acceptance: there is exactly one definition of the trigger set, or a test
  that fails the instant the two diverge.

**0.4 Reconcile the README's test-count and pass claims with reality.**
- State the real shape: "N tests; M require the optional `[attestation]` extra
  and skip cleanly without it." Drop or qualify any phrasing that implies a
  bare `unittest discover` is green regardless of environment. This is a
  one-paragraph honesty edit and it is the cheapest credibility win in the plan.
- Files: `README.md` (Tests section), `docs/QUICKSTART.md`.

### Phase 1 — Raise the detection ceiling honestly (1–2 weeks)

Addresses external-assessment W1 (heuristic ceiling) and W2 (lexical scaffold
detection). Phase-1 of the prior roadmap raised *recall*; this raises *honesty
about precision* and opens the only real path past the regex ceiling.

**1.1 Measure in-domain false positives before adding any pattern.**
- The new triggers (`superlative`, `decision`, `numeric_approx`) and the G4
  policy patterns are FP-prone precisely on the target domain. Build a
  stratified labelled corpus of *real* policy/brief prose (≥200 sentences, not
  60 illustration seeds) and report per-trigger precision and the G4 FP rate on
  legitimate ministerial/legislative text. Publish the confusion, including the
  embarrassing rows.
- Files: `eval/corpus/` (new in-domain corpus), `eval/run_eval.py`,
  `docs/LIMITATIONS.md`.

**1.2 Add an opt-in LLM claim-segmentation path, clearly separated from the
stdlib tripwire.**
- The prior roadmap's own risk note is correct: "do not chase 100% recall with
  regexes." The honest ceiling-raiser is sentence-level extraction by an LLM,
  offered as an **opt-in** (`--extractor llm`) that never touches the
  zero-dependency default path or the blocking hook. Regex stays the free,
  fast, offline tripwire; LLM extraction is the high-stakes upgrade.
- Files: `warrantos/provenance/extract.py` (pluggable extractor interface),
  `warrantos/provenance/grade.py` (reuse grader plumbing), CLI flag.

**1.3 Give scaffold-residue detection one non-lexical signal.**
- Pure phrase-matching is trivially evaded. Add a structural signal —
  second-person addressivity / meta-discourse density ("as you requested", "let
  me know", "I hope this helps") scored as a *rate*, not a literal list — and
  document plainly that this still catches only cheap residue. Keep the verdict
  contribution conservative to avoid FP on legitimately second-person prose
  (cover letters, correspondence).
- Files: `warrantos/provenance/context_admissibility.py` (G1 boundary),
  `tests/test_boundary.py`.

### Phase 2 — Make verification useful without spend (1 week)

Addresses W3 (verification weak without API keys). The tension the assessment
names is real: the tool is most useful where you already have verification
infrastructure. Lower that activation energy.

**2.1 Promote the no-spend grader path to a documented default.**
- `ClaudeCliGrader` (subscription via `claude --print`) and the local
  OpenAI-compatible grader already exist. Make `get_grader()` auto-select
  `ClaudeCliGrader` when `claude` is on PATH and no API key/local URL is set,
  and lead with it in `docs/NO-API-KEY.md`. This turns "verification needs an
  API key" into "verification needs the CLI you already have."
- Files: `warrantos/provenance/grade.py`, `docs/NO-API-KEY.md`.

**2.2 Strengthen the offline heuristic beyond token overlap.**
- The offline path cannot emit `contradicted` and only checks overlap. Add a
  lightweight lexical-entailment / negation-aware check (still stdlib) that can
  surface *probable* contradiction as `unverifiable→review` rather than
  silently passing. Keep the honest disclosure that true contradiction
  detection needs a grader; this just narrows the gap.
- Files: `warrantos/provenance/verify.py`, `tests/test_verify.py`.

### Phase 3 — Right-size the compliance and evaluation claims (3–5 days)

Addresses W4 (small corpora) and W5 (compliance optics) and the "no automated
SPEC-ID conformance check" red flag — which is the cheapest high-leverage item
in the whole plan.

**3.1 Build the automated SPEC-ID conformance check.**
- A ~50-line script that parses every `SPEC-*` and `INV-*` identifier in
  `docs/SPEC.md`, asserts each appears in *both* code and a test, and fails CI
  on an orphan. This converts F-compliance from "documented mapping"
  (the assessment's "documentation theater" charge) into an *enforced*
  traceability gate, and it is the one item that genuinely moves the compliance
  story from prose to mechanism.
- Files: new `tools/spec_conformance.py`, `.github/workflows/ci.yml`,
  `tests/test_spec_conformance.py`.

**3.2 Defuse the compliance-optics risk.**
- Add a top-of-document banner to `docs/COMPLIANCE.md` ("This is a
  self-assessment, not certification — see §5") and reduce the visual weight of
  the mapping table so a skimming reader cannot mistake it for conformance
  evidence. The content is already honest; this is about what a five-second
  glance conveys.
- Files: `docs/COMPLIANCE.md`.

**3.3 Stop reporting point precision/recall a 60-item corpus cannot support.**
- Either grow the grader corpus to a size that supports a headline number, or
  report intervals / drop the point estimates and say "regression seeds, not a
  benchmark" at the *number*, not just in a caveat block. Consistency with the
  project's own honesty norm.
- Files: `eval/README.md`, `eval/run_eval.py`.

### Phase 4 — Executability and adoption (2–4 weeks, lower urgency)

Addresses W6 (no adoption evidence), W7 (theoretical L5/L6), and the
version-churn red flag.

**4.1 Retire the legacy v0.3 plugin bifurcation.**
- The Claude Code plugin still wires v0.3, not WarrantOS — a documented but real
  split-brain user experience. Wire the WarrantOS surfaces (CLI/MCP/four-state
  verdict) into the plugin, or clearly sunset the plugin path. This is the
  red-flag item with the most direct user impact.
- Files: `.claude-plugin/plugin.json`, `warrantos/hooks/`, `docs/`.

**4.2 Ship a runnable end-to-end clean-room reference.**
- L5/L6 are "built" but the generation loop is caller-implemented, so the full
  vision isn't executable from the box. Provide one reference harness
  (`examples/clean-room-e2e/`) that drives writer-pack → generation →
  gates → verdict end to end against a local or CLI model, so the architecture
  is demonstrable, not just described.
- Files: new `examples/clean-room-e2e/`, `tools/`.

**4.3 Adopt a soak/release policy to stop the churn.**
- v0.9.0b1→v0.9.5 in ~6 days, with a unicode crash shipping in between, reads
  as insufficient soak. Phase 0.1–0.2 (green clean-checkout + no-extras CI lane)
  remove the *class* of regression that drove the churn; pair them with a stated
  minimum soak window and a "CI green on the full OS×extras matrix" release gate
  in `CONTRIBUTING.md`.
- Files: `CONTRIBUTING.md`, `.github/workflows/release.yml`.

**4.4 Produce one real-world validation artefact.**
- The honest demo is synthetic. A single documented case study of WarrantOS
  catching a *genuine* fabricated or mis-attributed citation in real
  AI-assisted writing would do more for adoption than any feature. Lower effort
  than it sounds: run the gate over a corpus of real AI-drafted briefs and
  write up what it caught and missed.
- Files: `docs/` (case study), `examples/`.

## Sequencing and effort

| Phase | Theme | Effort | Why this order |
|---|---|---|---|
| 0 | Pass its own bar | ~1 session | Cheapest, highest credibility; verified defects; de-risks all downstream claims |
| 1 | Detection ceiling, honestly | 1–2 weeks | The central technical limitation; but measure FP before adding patterns |
| 2 | Verification without spend | ~1 week | Removes the biggest adoption blocker for the target user |
| 3 | Right-size compliance/eval | 3–5 days | SPEC-ID check is cheap and converts optics into mechanism |
| 4 | Executability + adoption | 2–4 weeks | Highest absolute value (real validation) but depends on 0–2 being solid |

## Non-goals (carried forward and reaffirmed)

- Do not build a certified compliance product. 3.1/3.2 make the mapping
  *honest and enforced*, not certified.
- Do not chase 100% regex recall. 1.2 (opt-in LLM extraction) is the correct
  instrument past the regex ceiling; more patterns past ~60–70% recall only add
  false positives.
- Do not add hard deletion; tombstones (INV-011) stay.
- Do not gate drafting; blocking stays at publish boundaries only.
- Do not let the version number outrun the soak (4.3).

## The one-line version

The B+ is for the documentation, and the documentation has earned it. The
codebase has not yet earned it on its own terms: it ships a suite that does not
pass clean, a load-bearing detector kept correct by a comment, and an
in-domain false-positive surface it has never measured. Phase 0 is the project
holding itself to the standard it sells. Everything after is the roadmap the B+
assessment already (correctly) described.
