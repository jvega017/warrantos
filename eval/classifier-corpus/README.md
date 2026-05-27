# SPEC-L1-S006 classifier corpus

This directory holds the labelled classification corpus required by
SPEC-L1-S006: every conformant implementation SHOULD ship a labelled
corpus of at least N = 50 representative inputs per class, with the
expected classification, and SHOULD run Layer 1 against this corpus
on every release.

**Status as of v0.6:** SEED ONLY. The seed file `seeds.jsonl` carries
one representative example per class (N = 1 per class). This satisfies
SPEC-L1-S006 at SHOULD level for v0.6 only; the v0.3 promotion to
SHALL requires N >= 50 per class.

## Why only seeds

Honest scope: a useful labelled corpus needs real input examples per
class, authored by a human with domain familiarity. The seeds below
were chosen to give the runner a meaningful smoke test (every class
appears at least once) without fabricating examples that pretend to
be a labelled dataset. The intent is to make the runner exercise the
classifier surface so a regression is visible; expanding the corpus
to N = 50 per class is research-execution work that follows.

## Corpus file format

`seeds.jsonl`: one JSON object per line, with three fields:

- `id`: stable identifier for this example.
- `text`: the input text.
- `expected_context_type`: the canonical SPEC §2.2 class name.

Example:

```jsonl
{"id": "seed_empirical_001", "text": "Source: Treasury Bulletin, 2026, page 12.", "expected_context_type": "empirical_evidence"}
```

## Running the runner

```
python eval/run_classifier_corpus.py [--corpus PATH] [--json]
```

Default corpus path is `eval/classifier-corpus/seeds.jsonl`. The
runner reports per-class precision, the number of mismatches, and the
exit code (0 on full match; 1 on any mismatch). Use this in CI when
extending the corpus to catch regressions.

## Extension protocol

To add a new example:

1. Author the input text. Real workflow inputs are preferred over
   synthetic prose.
2. Decide the expected_context_type from SPEC §2.2 (eleven canonical
   classes).
3. Append a line to `seeds.jsonl`.
4. Run `python eval/run_classifier_corpus.py` and confirm the new
   example passes.
5. When a class reaches N >= 50, mark that class as SHALL-ready in
   the CHANGELOG.

The promotion of SPEC-L1-S006 from SHOULD to SHALL happens when every
class reaches N >= 50.
