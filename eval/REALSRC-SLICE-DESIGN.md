# Real-source slice (Option 3): design specification

**Status:** Design specification, not items. The slice is **research
execution** that requires real fetched sources, careful curation, and an
authorial decision about scope. This document fixes the design so the
next session, or Juan directly, can execute it without re-thinking the
shape of the work. It is not auto-executed because building a sloppy
real-source slice is worse than building no slice at all and would
contradict the very governance discipline the project is about.

**Purpose.** Address the deepest reviewer objection raised by the
2026-05-21 fresh-critic and prior-art check: that with no fetch, the
existing 60-item synthetic corpus is a natural language inference
setting, not end-to-end citation verification, so the title's "From
Citation to Epistemic Governance" is over-scoped. A real fetched-source
slice converts the synthetic corpus into a controlled mechanism isolator
and adds a slice that exercises the citation-verification claim under
realistic retrieval. The synthetic corpus is then a diagnostic, not a
benchmark; the real slice is the slice the title earns.

---

## Scope

**Size:** 15 to 30 items. Smaller than the synthetic corpus on purpose:
each item is curated, fetched, and labelled with provenance.

**Class balance (target):**

| gold class | count target | rationale |
|---|---|---|
| verified | 5 | the source explicitly supports the claim |
| contradicted | 4 | the source explicitly contradicts the claim |
| not_addressed | 3 | source provided but doesn't address the claim |
| unverifiable | 2 | citation present, source unfetchable (paywall, deadlink) |
| skipped | 2 | no citation and no source |

Total 16 items, balanced toward verified and contradicted because those
are the labels the grader's behaviour most needs to be tested on with
real text.

**Out of scope for this slice:**
- Paywalled academic articles (use OA where possible).
- Multi-document evidence (one source per claim).
- Cross-language sources.
- Long-form passages: each `source` field should be a quotable span
  (one to three sentences) drawn from a longer document, with the URL,
  fetch date, and locator stored in `note`.

## Source domains (priorities, with rationale)

Domains chosen for stability, public access, and policy-relevance to
both pathways:

1. **ABS (Australian Bureau of Statistics)** — Labour Force, CPI, WPI,
   National Accounts. Stable, citable, sentence-level claims are
   common. Use api.data.abs.gov.au or the published media releases.
2. **OECD** — AI policy observatory, OECD AI Principles, country
   dashboards. Stable URLs, sentence-level numeric claims.
3. **Queensland Treasury / Budget / MYFER public releases** — only
   the already-published material (no pre-release content). Stable.
4. **legislation.qld.gov.au and legislation.gov.au** — authoritative
   statutory text, useful for statute-reference claims.
5. **Productivity Commission, Queensland Productivity Commission,
   Queensland Competition Authority** — published research reports.
6. **CSIRO / data.gov.au / data.qld.gov.au** — published findings.

Avoid:
- Anything Cabinet-in-Confidence, Sensitive, Protected, HR, legal
  advice, or pre-release budget. Hard rule.
- News articles as primary sources where the original report exists.
- Wikipedia as a source (use only the underlying citations).

## Item construction protocol

For each item:

1. **Select a claim candidate.** Either author a plausible claim of the
   right shape, or extract a sentence from a public document that
   asserts a checkable fact.
2. **Locate the candidate source.** For verified: a source that
   actually supports the claim. For contradicted: a source that
   asserts the opposite or a different magnitude. For not_addressed:
   a source on the right general topic that does not speak to this
   specific assertion. For unverifiable: a citation with no fetchable
   text (e.g., a personal communication, a withdrawn page, a
   paywalled article behind login).
3. **Fetch.** Use WebFetch or Firecrawl. Record the full URL, the
   fetch date (UTC), and a hash of the fetched content (sha256 of the
   span).
4. **Extract the quotable span.** Keep it short (one to three
   sentences) and include the span in the `source` field. Put the URL,
   fetch date, and content hash in the `note` field.
5. **Label gold.** Apply the self-evident criterion: a reviewer
   reading only the visible fields must agree the gold label without
   external knowledge. For real-source items this is strictly harder
   than for synthetic items; do not force "self-evident" labels onto
   ambiguous cases — discard or reclassify instead.
6. **Assign id.** Sequential `r001`, `r002`, ... so the real-source
   slice ids are distinct from the synthetic `g001`-`g060`.

## Schema (extension of existing grader corpus)

A new file at `eval/corpus/grader-realsrc.jsonl`. Identical line schema
to `grader.jsonl`, with one convention:

```json
{
  "id": "r001",
  "claim": "...",
  "citation": "URL or APA token",
  "source": "<the quoted span from the fetched document>",
  "gold": "verified | contradicted | not_addressed | unverifiable | skipped",
  "note": "URL=<url>; fetched=<YYYY-MM-DD>; sha256=<hex>; rationale=<one-line>"
}
```

## Harness integration

`eval/run_eval.py` should accept either or both corpora:

- New CLI flag `--realsrc-corpus PATH` defaulting to
  `eval/corpus/grader-realsrc.jsonl` (if file exists; otherwise the
  block is silently skipped, exit 0).
- Print a SECOND grader-evaluation block titled
  "REAL-SOURCE SLICE" after the synthetic-corpus grader block.
- Per-class P/R/F1 reporting identical to the synthetic block.
- Confusion matrix.
- The caveat block must state, in addition to the synthetic caveats,
  that real-source items have inherent labelling ambiguity and the
  self-evident criterion is strictly harder to apply.

## Test plan

Add to `tests/test_eval.py`:

- `--realsrc-corpus` with a non-existent path: harness still exits 0
  on the synthetic corpus and silently omits the real-source block.
- A minimal valid real-source corpus (one item per class) parses and
  reports.
- The schema accepts and emits the `note` field unchanged.
- Existing 247 tests continue to pass.

## Reporting discipline

When the real-source slice is reported alongside the synthetic block:

- Never quote the combined accuracy as one number. Always show the
  two blocks separately, by gold class, by support.
- The synthetic block is reframed as "controlled mechanism isolator,
  diagnostic, NOT a benchmark."
- The real-source block is the slice that earns the
  citation-verification framing of the title.
- For both blocks, report the `error` column explicitly with a count.
  A clean confusion matrix is only trustworthy if `error` is named
  and stated.

## Honesty: what this slice does NOT do

- It does not make the corpus an external validated benchmark. n is
  still small.
- It does not provide independent annotation. Single annotator (Juan).
  Probe A (label-reproducibility by a different-family model) and
  independent human second-coding remain the named revision items.
- It does not test multi-document or cross-lingual evidence.
- It does not pin the model used in any cross-model probe; that
  remains separately controlled.

## Sequencing

1. After Probe A on Gemini returns a non-vacuous kappa (i.e., the
   synthetic gold is reproducible), build this slice. A vacuous Probe
   A would suggest the synthetic gold itself is contested, in which
   case the real-source slice's construction protocol needs
   adjustment first.
2. Build the slice on a new branch `eval/realsrc-slice`. One commit
   per logical chunk (corpus file, harness integration, tests,
   docs).
3. PR for review. Do not merge until Juan has reviewed each item's
   gold label and rationale.

## Effort estimate

- Per item: 10 to 20 minutes (find candidate, fetch, extract span,
  label, hash). 15 to 30 items = 4 to 8 hours of careful work.
- This is a research-execution session, not a sprint. Reserve a
  block of time. Do not interleave with other work.
