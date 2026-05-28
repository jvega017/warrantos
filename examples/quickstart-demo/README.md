# Quickstart demo (HOLD)

A two-minute, copy-paste end-to-end run of the warrantos pipeline. Demonstrates every layer that ships in v0.9.0b1: Layer 1 classification, Layer 7 G1 prose-boundary scan, Layer 7 G2 claim detection (offline, no API key), CBOM v0.2 with actor_identity, and the four-state consolidated verdict.

This example produces `HOLD`. For the other three verdicts (`PASS`, `BLOCK`, `NOT_ASSESSABLE`), see [`examples/README.md`](../README.md) for the full gallery.

## Files

- `draft.md`: a sample brief paragraph with one unsupported
  load-bearing claim. Designed to produce a `HOLD` verdict so the
  demo shows the gate firing.
- `context.json`: three context items: a source citation, a
  user-feedback line, and a `policy-red-team` review finding that
  exercises SPEC-L1-S005 review-role gating.
- `actor.json`: the six-role actor identity map that turns
  `NOT_ASSESSABLE` into a real verdict for the `final-prose`
  profile.

## Run

From the repository root:

```bash
python cli/warrantos_cli.py check examples/quickstart-demo/draft.md \
  --context examples/quickstart-demo/context.json \
  --actor-identity examples/quickstart-demo/actor.json \
  --profile final-prose
```

Or, after `python -m pip install -e .` from the repository root:

```bash
warrantos check examples/quickstart-demo/draft.md \
  --context examples/quickstart-demo/context.json \
  --actor-identity examples/quickstart-demo/actor.json \
  --profile final-prose
```

## Expected output (text mode)

```
warrantos check
  run id:        run_<short>
  profile:       final-prose
  draft chars:   239
  context items: 3
  by context_type:
    empirical_evidence     1
    review_finding         1
    user_feedback          1
  claims detected: 2
  claims supported: 1
  claims unsupported: 1
  boundary: pass (0 violations)
  overrides on record: 0

VERDICT: HOLD
  - HOLD: unsupported load-bearing claim (salience=1.00): The Act will save AUD 250 million over the forward estimates.

artefacts written to: .warrant/runs/run_<short>
```

The `HOLD` verdict fires because the second sentence in `draft.md`
contains a magnitude claim with no source citation. The first
sentence has a citation token, so it counts as supported.

## What each verdict means

| Verdict | Trigger | Action |
|---|---|---|
| PASS | No boundary violation, no unsupported load-bearing claim, no contradicted claim, no NOT_ASSESSABLE | Ship the artefact |
| HOLD | Unsupported or unverifiable load-bearing claim | Add a citation or downgrade the claim |
| BLOCK | Boundary violation in final-prose, or a contradicted claim | Rewrite the offending text |
| NOT_ASSESSABLE | Final-prose without `--actor-identity` | Supply actor identity or use a non-final-prose profile |

## What to try next

- Edit `draft.md` to add a citation to the magnitude claim. Re-run.
  The verdict shifts to `PASS`.
- Edit `draft.md` to insert "based on your feedback" somewhere.
  Re-run with `--profile final-prose`. The verdict shifts to `BLOCK`.
- Remove `--actor-identity` from the command. Re-run. The verdict
  shifts to `NOT_ASSESSABLE`.
- Run with `--writer-model claude-opus-4-7 --verifier-model claude-opus-4-7`.
  The verdict carries a `FLAG (G3 informational)` line for self-grounding.

Every per-run artefact lands in `.warrant/runs/<run_id>/`: `cbom.json`,
`context_items.json`, `boundary.json`, `claims.json`, `verifier.json`,
`verdict.json`. Inspect them to see how each layer recorded its work.
