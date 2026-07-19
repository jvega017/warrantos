# Probe A: label-reproducibility report

## STATUS: partial run, infrastructure errors present

18 of 60 items returned an `error` predicted label (annotator
infrastructure failure, not a classification result). The headline
agreement and kappa below count errors in the totals so they reduce
the numbers honestly. Read the per-class block: a class with zero
returns reflects a quota or transport cut-off on that segment of
the corpus, not a finding about reproducibility for that class.

**This is a machine reproducibility signal. It is NOT human inter-rater
reliability.** A different-family model (Gemini) was given the same
visible labelling fields (claim, citation, source) as a human annotator,
blind to the original gold, and asked to emit a class from the five-
class set. Agreement and Cohen's kappa are reported against the
original gold labels.

## Run metadata

- date: 2026-05-23 07:21 UTC
- corpus: eval\corpus\grader.jsonl (60 items)
- annotator (Probe A): gemini-2.5-flash-lite
- annotator model: gemini-2.5-flash-lite
- grader model being de-conflated from labels: Codex (GPT-5.x family) — different family from annotator (different-family agreement is informative; same-family is not).
- per-call timeout: 120s

## Headline

- agreement: 0.6167 (37/60)
- Cohen's kappa: 0.5455
- error count (annotator infrastructure failure, predicted-only label): 18

## Per-class agreement

| class | support | annotator agreed | recall |
|---|---|---|---|
| verified | 14 | 14 | 1.0000 |
| contradicted | 16 | 14 | 0.8750 |
| not_addressed | 12 | 6 | 0.5000 |
| unverifiable | 9 | 2 | 0.2222 |
| skipped | 9 | 1 | 0.1111 |

## Confusion matrix (rows = gold, cols = annotator)

| gold \ pred | verified | contradicted | not_addressed | unverifiable | skipped | error |
|---|---|---|---|---|---|---|
| verified | 14 | 0 | 0 | 0 | 0 | 0 |
| contradicted | 0 | 14 | 0 | 0 | 2 | 0 |
| not_addressed | 0 | 0 | 6 | 0 | 3 | 3 |
| unverifiable | 0 | 0 | 0 | 2 | 0 | 7 |
| skipped | 0 | 0 | 0 | 0 | 1 | 8 |

## Honesty caveats (applied)

- The annotator model (Gemini) is from a different family than the
  grader being evaluated (Codex). Same-family agreement is not run
  here because it would be uninformative.
- A high kappa indicates that the gold labels are reproducible by a
  different model from the same visible information, which
  corroborates the corpus's self-evident-labelling design criterion.
  It does NOT indicate human inter-rater reliability. Independent
  human second-coding remains the named revision item.
- A low kappa is also a finding: it would mean the gold labels are
  not reproducible from the visible fields alone, which would
  weaken the single-annotator defence of the corpus.
- Gemini output is model-dependent and not bit-reproducible across
  runs or model updates. The date and model name above pin this run.
- Errors (predicted-only label, infrastructure failures) are counted
  in the totals; they reduce agreement honestly rather than being
  silently dropped.
