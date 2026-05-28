# Examples gallery

Four runnable cases, one per verdict in the WarrantOS four-state model. Each example is self-contained: a `draft.md`, a `context.json`, an `actor.json`, and a per-example `README.md` explaining which line in the draft causes that verdict.

| Verdict | Example | What triggers it |
|---|---|---|
| `PASS` | [`01-pass/`](01-pass/) | Every claim has an inline citation; no boundary violation; actor identity supplied |
| `HOLD` | [`quickstart-demo/`](quickstart-demo/) | One magnitude claim has no source; remaining mechanics PASS |
| `BLOCK` | [`03-block-prose-boundary/`](03-block-prose-boundary/) | Final prose narrates process material ("based on your feedback") |
| `NOT_ASSESSABLE` | [`04-not-assessable-missing-actor/`](04-not-assessable-missing-actor/) | Final-prose profile but no `--actor-identity` supplied |

The `quickstart-demo/` folder is the canonical HOLD case kept for backward compatibility and the README quickstart command; the other three sit alongside it as a gallery.

## Run any example

From the repository root:

```bash
warrantos check examples/<case>/draft.md \
  --context examples/<case>/context.json \
  --actor-identity examples/<case>/actor.json \
  --profile final-prose
```

For the `NOT_ASSESSABLE` example, omit `--actor-identity` deliberately:

```bash
warrantos check examples/04-not-assessable-missing-actor/draft.md \
  --context examples/04-not-assessable-missing-actor/context.json \
  --profile final-prose
```

## What the four verdicts mean

| Verdict | Action |
|---|---|
| `PASS` | Ship the artefact |
| `HOLD` | Add a citation or downgrade the unsupported load-bearing claim |
| `BLOCK` | Rewrite the offending text (boundary violation or contradicted claim) |
| `NOT_ASSESSABLE` | Supply actor identity or use a non-final-prose profile |

Per-run artefacts land in `.warrant/runs/<run_id>/`: `cbom.json`, `context_items.json`, `boundary.json`, `claims.json`, `verifier.json`, `verdict.json`. Inspect them to see how each layer recorded its work.
