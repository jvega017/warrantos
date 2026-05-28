# Example 01: `PASS`

A clean final-prose artefact: every factual sentence carries an inline citation on the same line; no process-narration phrases; actor identity supplied for the `final-prose` profile.

## Run

```bash
warrantos check examples/01-pass/draft.md \
  --context examples/01-pass/context.json \
  --actor-identity examples/01-pass/actor.json \
  --profile final-prose
```

## What you should see

```
VERDICT: PASS
```

with `claims supported: 2`, `claims unsupported: 0`, `boundary: pass (0 violations)`, `overrides on record: 0`.

## Why it passes

| Mechanism | Check |
|---|---|
| Layer 1 classification | Both context items classify as `empirical_evidence` (source citations) |
| Layer 7 G1 prose-boundary | Draft contains no banned process-narration phrases for the `final-prose` profile |
| Layer 7 G2 claim detection | Two factual sentences; each has an inline URL citation on the same line, so both score as `supported` |
| CBOM v0.2 assembly | `actor_identity` map is complete; the artefact is certifiable |
| Verdict consolidation | No HOLD, no BLOCK, no NOT_ASSESSABLE -> `PASS` |

## How to break it

- Remove the URL from line 3 or line 5 of `draft.md`. The verdict shifts to `HOLD` (the claim becomes unsupported).
- Add "based on your feedback this is now more commercial" anywhere in `draft.md`. The verdict shifts to `BLOCK`.
- Remove `--actor-identity` from the command. The verdict shifts to `NOT_ASSESSABLE`.
