# Probe A: label-reproducibility report

## STATUS: TOOLING FAILURE — NOT A FINDING

This run produced 60 of 60 `error` predictions because the Gemini
free-tier daily quota was exhausted partway through (or before) the
run window. A capacity check after the run returned the explicit
diagnostic `TerminalQuotaError: You have exhausted your daily quota
on this model`. The 44 generic generation errors and 11 transport
errors recorded earlier in the 569-second run window were the same
underlying condition surfacing through different error classes; the 5
HTTP 503 "high demand" responses seen in the smoke test that
preceded this run were also part of the same quota-exhaustion arc.
The 0/60 agreement and 0.0000 kappa below are NOT a
label-reproducibility result. They are a record that the annotator
model was not callable.

What this run does demonstrate: the Probe A harness handles the
all-failure case as designed — no crash, every infrastructure failure
mapped to a clean `error` predicted label, the `error` count reported
explicitly, exit code 0 so a CI re-run will not break.

What is required before a finding can be reported: re-run when the
Gemini daily quota window has reset (next UTC day boundary by
default on the free tier; consult the Gemini account dashboard for
the exact reset clock). Before the re-run, a one-word probe (`gemini
-p "Reply with exactly OK"`) must return within a few seconds and
without `TerminalQuotaError`. The harness, corpus and gold labels
are unchanged. The Probe A script and design spec at
`eval/probe_label_reproducibility.py` and `eval/REALSRC-SLICE-DESIGN.md`
do not require any change for the re-run; only run the same command.

Operational implication, recorded for the run plan: 60 structured
classification calls on the Gemini free tier appears to be near or
above the daily quota envelope under load conditions, so the probe
needs to be scheduled when there is headroom or run on a paid tier.
This is a tooling-procurement fact, not a finding about the model
or the corpus.

---

**This is a machine reproducibility signal. It is NOT human inter-rater
reliability.** A different-family model (Gemini) was given the same
visible labelling fields (claim, citation, source) as a human annotator,
blind to the original gold, and asked to emit a class from the five-
class set. Agreement and Cohen's kappa are reported against the
original gold labels.

## Run metadata

- date: 2026-05-21 17:09 UTC
- corpus: eval\corpus\grader.jsonl (60 items)
- annotator model (Probe A): gemini-cli
- grader model being de-conflated from labels: Codex (GPT-5.x family) — different family from annotator (different-family agreement is informative; same-family is not).
- per-call timeout: 300s

## Headline

- agreement: 0.0000 (0/60)
- Cohen's kappa: 0.0000
- error count (annotator infrastructure failure, predicted-only label): 60

## Per-class agreement

| class | support | annotator agreed | recall |
|---|---|---|---|
| verified | 14 | 0 | 0.0000 |
| contradicted | 16 | 0 | 0.0000 |
| not_addressed | 12 | 0 | 0.0000 |
| unverifiable | 9 | 0 | 0.0000 |
| skipped | 9 | 0 | 0.0000 |

## Confusion matrix (rows = gold, cols = annotator)

| gold \ pred | verified | contradicted | not_addressed | unverifiable | skipped | error |
|---|---|---|---|---|---|---|
| verified | 0 | 0 | 0 | 0 | 0 | 14 |
| contradicted | 0 | 0 | 0 | 0 | 0 | 16 |
| not_addressed | 0 | 0 | 0 | 0 | 0 | 12 |
| unverifiable | 0 | 0 | 0 | 0 | 0 | 9 |
| skipped | 0 | 0 | 0 | 0 | 0 | 9 |

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
