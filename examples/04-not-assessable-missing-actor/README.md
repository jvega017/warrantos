# Example 04: `NOT_ASSESSABLE`

The artefact is fine in every other respect: the one factual sentence has an inline citation; no boundary violations; clean context. The fourth verdict state catches a different failure: the run does not have the metadata required to certify a final-prose artefact.

Specifically, this example deliberately omits `--actor-identity` from the command line. Under the `final-prose` profile, certification requires a complete actor-identity map (CBOM v0.2). Without it, the run cannot truthfully say `PASS`. Most tools would either pass silently or fail noisily; WarrantOS reports the missing metadata as a fourth verdict so an operator can see the gap.

## Run

```bash
warrantos check examples/04-not-assessable-missing-actor/draft.md \
  --context examples/04-not-assessable-missing-actor/context.json \
  --profile final-prose
```

Note: no `--actor-identity` argument.

## What you should see

```
VERDICT: NOT_ASSESSABLE
  - NOT_ASSESSABLE: final-prose artefact requires actor_identity to
    certify the override/identity leg of the coupling thesis. No
    actor_identity supplied. Either provide --actor-identity or use
    a non-final-prose profile.
```

## Why this fourth verdict matters

| Without NOT_ASSESSABLE | With NOT_ASSESSABLE |
|---|---|
| Tool binary-ises into PASS or FAIL | Tool names the case where the artefact is *neither* defective *nor* certifiable on the available data |
| Missing actor identity quietly passes | Missing actor identity surfaces explicitly |
| Operator has no signal that audit metadata is incomplete | Operator sees `supply actor identity or use a non-final-prose profile` |

This is one of the structural-honesty properties the WarrantOS coupling thesis depends on. Certifying on incomplete information is itself a failure mode.

## How to resolve it

Two paths, equally valid:

1. Add `--actor-identity examples/04-not-assessable-missing-actor/actor.json` to the command (copy the actor.json from `examples/01-pass/`). The verdict shifts to `PASS`.
2. Switch `--profile final-prose` to `--profile brief-light` or `--profile prompt-template`. Those profiles do not require actor identity, so the verdict resolves to PASS or HOLD on the merits of the prose alone.
