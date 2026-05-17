# eval: evaluation harness for claude-provenance

## What this is

This directory contains a small, hand-built seed corpus and an evaluation
harness for the claude-provenance v0 heuristic detector.

**This is not an external validated benchmark.** The corpus was constructed
manually to cover the claim types the heuristic is designed to catch, to
confirm that the false-negative the v0 design closed stays closed, and to
give a regression baseline. Reported numbers are entirely corpus-dependent
and reflect the design choices embedded in the corpus labels. Do not quote
precision, recall or F1 from this harness as general accuracy figures.

## Corpus: eval/corpus/seed.jsonl

35 items. Each line is a JSON object:

```json
{
  "id":   "<unique id>",
  "text": "<one short paragraph>",
  "gold": [
    {
      "claim":  "<substring asserting a fact>",
      "axis1":  "supported | unsupported | tagged",
      "axis2":  "verified | unverifiable | skipped | na"
    }
  ]
}
```

Items with an empty `gold` array are non-claim sentences included to confirm
the heuristic does not fire on them.

### Axis-1 labels (v0 heuristic)

| Label | Meaning |
|---|---|
| `supported` | The claim sentence itself carries a citation (URL, APA, Source: note, markdown link, or footnote), or the immediately following sentence is a citation-lead line. |
| `unsupported` | A claim trigger fires but no adjacent citation is present. |
| `tagged` | The claim carries an explicit `[CITE NEEDED]` marker. |

### Axis-2 labels (offline verify_text)

| Label | Meaning |
|---|---|
| `unverifiable` | A citation is present but source text cannot be fetched (offline). |
| `skipped` | No citation is present; nothing to verify. |
| `verified` | Source text was fetched and salient tokens matched (not reachable offline). |
| `na` | Axis-2 verdict not applicable for this gold entry. |

### Coverage in the seed corpus

The corpus explicitly covers:

- **Supported claims** -- inline URL, APA (Author, Year), `Source:` note,
  adjacent citation-lead line (next sentence is the source)
- **Unsupported claims** -- each trigger type: year, percentage, magnitude,
  statute, attribution
- **Tagged claims** -- explicit `[CITE NEEDED]` across mixed trigger types
- **v0 false-negative case** -- a source two or more sentences away from the
  claim; the corpus labels the claim `unsupported`, confirming the v0
  bleeding-citation bug stays closed
- **Non-claim sentences** -- plain text with no factual trigger; gold is empty
- **APA citation with multi-word author** -- exercises a known regex limitation
  where `(Productivity Commission, 2021)` does not match the single-token APA
  pattern; correctly labelled `supported` (gold) even though the heuristic
  predicts `unsupported` (a genuine false positive)

## Running the evaluation

From the repo root:

```
python eval/run_eval.py
```

Use a custom corpus:

```
python eval/run_eval.py --corpus path/to/custom.jsonl
```

The harness exits 0 on success and prints a metrics table. It exits 1 only if
the corpus file is missing or malformed.

## How to extend the corpus

1. Add lines to `eval/corpus/seed.jsonl`. Each line must be valid JSON with
   the schema above.
2. Choose texts that are self-evidently labelled: a reviewer reading the text
   must be able to agree the gold axis-1 label without external knowledge.
3. Cover edge cases you care about: non-English Unicode, footnote references
   (`[^1]`), markdown links, multi-claim sentences, very long claims.
4. After adding items, re-run `python eval/run_eval.py` and inspect the
   confusion table. Large drops in precision or recall warrant investigation.
5. Run `python -m unittest tests.test_eval -v` to confirm the harness
   invariants still hold.

## Test suite

`tests/test_eval.py` verifies:

- The harness runs on the seed corpus and exits 0.
- Every reported metric is within `[0, 1]`.
- The corpus parses as JSONL and all axis-1/axis-2 values are from the allowed
  set.
- The v0 false-negative item (`c10`) is labelled `unsupported`.

The test suite does **not** assert specific accuracy numbers because those
numbers are corpus-dependent and will change as the corpus grows.
