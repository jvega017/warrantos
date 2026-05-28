# Example 03: `BLOCK` from a prose-boundary violation

The draft opens with "Based on your feedback this is now more commercial". That phrase narrates the writing process to the reader, instead of applying the feedback silently. The Layer 7 G1 prose-boundary gate is designed to catch exactly this leak.

## Run

```bash
warrantos check examples/03-block-prose-boundary/draft.md \
  --context examples/03-block-prose-boundary/context.json \
  --actor-identity examples/03-block-prose-boundary/actor.json \
  --profile final-prose
```

## What you should see

```
VERDICT: BLOCK
  - BLOCK: boundary violation [process_feedback severity=high] line 3: Based on your feedback
  - BLOCK: boundary violation [comparative_revision severity=medium] line 3: more commercial
```

with `boundary: blocked (2 violations)` in the summary. The first sentence of the draft trips two distinct boundary rules: `process_feedback` (narrating that the writer received feedback) and `comparative_revision` (telling the reader the draft used to be different).

## Why it blocks

| Mechanism | Outcome |
|---|---|
| Layer 1 classification | `ctx_feedback_001` correctly classifies as `user_feedback` |
| Layer 4 admissibility | `user_feedback` may inform the writer's Clean Brief but MUST NOT reach final prose verbatim |
| Layer 7 G1 prose-boundary | The phrase "based on your feedback" matches a lexical-residue rule under the `final-prose` profile |
| Verdict consolidation | Any boundary violation in `final-prose` -> `BLOCK` |

The `BLOCK` is structural, not stylistic. The writer was asked to make the brief more commercial. The right move is to make the brief more commercial, full stop, without telling the reader the brief used to be different.

## How to fix it

Edit `draft.md` and remove the first sentence. The remaining sentence has a valid citation, so the verdict shifts to `PASS`.

## Other ways to reach `BLOCK`

- Add "as discussed in our planning session" - matches the process-history rule.
- Add a claim that is verifiably contradicted by its cited source (requires an LLM grader configured).
