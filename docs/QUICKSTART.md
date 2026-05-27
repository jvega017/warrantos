# Quickstart

Five minutes from `pip install` to a working verdict.

## Install

```bash
pip install claude-provenance
```

Core install has **zero third-party dependencies**. Stdlib only.

Optional MCP transport (only needed for Claude Code / Claude Desktop
integration; the Python API and CLI work without it):

```bash
pip install "claude-provenance[mcp]"
```

## Verify the install

```bash
warrantos --help
```

Should print the help for the integration CLI. If you prefer running
without installing, every entry point also works as a module:

```bash
python -m cli.warrantos_cli --help
```

## Run the bundled demo

```bash
git clone https://github.com/jvega017/claude-provenance.git
cd claude-provenance

warrantos check examples/quickstart-demo/draft.md \
  --context examples/quickstart-demo/context.json \
  --actor-identity examples/quickstart-demo/actor.json \
  --profile final-prose
```

Expected verdict: **`HOLD`** with one unsupported load-bearing claim.
The demo is wired so every layer fires at least once. See
[`examples/quickstart-demo/README.md`](../examples/quickstart-demo/README.md)
for the explanation of each line of output.

## What just happened

The CLI ran your draft through every layer of the WarrantOS pipeline:

1. **Layer 1** classified the three context items into eleven canonical
   classes. The `policy-red-team` review finding was forced to
   `review_finding` even though its text looks like a casual note,
   because the `source_agent` matched the SPEC-L1-S005 registry.
2. **Layer 7 G1** scanned your draft for prose-boundary violations
   (e.g. "based on your feedback"). The demo has none.
3. **Layer 7 G2** detected factual claims. The first sentence has a
   URL citation, so it counts as supported. The second sentence
   asserts a 250-million-dollar saving with no source, so it counts
   as unsupported and load-bearing.
4. The CBOM v0.2 was assembled with the actor identity map you
   supplied and saved to `.warrant/runs/<run_id>/cbom.json`.
5. The consolidated verdict logic returned `HOLD` because of the
   unsupported claim.

## The four-verdict model

| Verdict | Trigger | What you do |
|---|---|---|
| `PASS` | No boundary violation, no unsupported load-bearing claim, no contradicted claim, no NOT_ASSESSABLE | Ship the artefact |
| `HOLD` | Unsupported or unverifiable load-bearing claim | Add a citation or downgrade the claim |
| `BLOCK` | Boundary violation in final-prose, or a contradicted verifier verdict | Rewrite the offending text |
| `NOT_ASSESSABLE` | Final-prose without `--actor-identity` | Supply actor identity or use a non-final-prose profile |

## What runs locally vs what costs API credits

| Stage | Cost |
|---|---|
| Layer 1 classifier | Local; no cost |
| Layer 2 ledger writes | Local; no cost |
| Layer 4 admissibility | Local; no cost |
| Layer 7 G1 boundary scan | Local; no cost |
| Layer 7 G2 claim **detection** | Local; no cost |
| Layer 7 G2 claim **verification, offline mode** (default) | Local; no cost |
| Layer 7 G2 claim **verification, LLM mode** | Anthropic API credits per claim when `ANTHROPIC_API_KEY` is set AND `--verify` is passed |
| CBOM assembly + footer | Local; no cost |
| MCP server | Local; no cost |

The default invocation is free. You only pay API credits when you
explicitly opt into the LLM grader. See [`COST.md`](COST.md) for the
spend-control flags and recommended profiles.

## What this tool does and does NOT claim

WarrantOS does **not** prove your artefacts are correct. It
guarantees three operational properties:

1. Unsupported claims are surfaced, not invisible.
2. Process material cannot reach final prose without a recorded
   transformation.
3. Overrides cannot reach the public artefact without a structured
   rationale (SPEC-L8-S004) and a reader-facing footer
   (SPEC-L8-S005).

The remaining failure modes are addressed by human review and the
six-paper coupling thesis documented in
[`docs/OVERVIEW.md`](OVERVIEW.md). Treat this tool as the operational
form of that thesis, not as a correctness oracle.

## Where to go next

- **One-page tour of every layer**:
  [`docs/OVERVIEW.md`](OVERVIEW.md)
- **Adding the MCP server to Claude Code / Claude Desktop**:
  [`docs/MCP-CONFIG.md`](MCP-CONFIG.md)
- **Verifying claims without an Anthropic API key**:
  [`docs/NO-API-KEY.md`](NO-API-KEY.md) — local LLM, Claude Code
  hook, or MCP sampling (v0.9).
- **Keeping API costs predictable**:
  [`docs/COST.md`](COST.md)
- **What gates exist and how to extend them**:
  [`docs/STACK.md`](STACK.md)
- **Layer 1 context admissibility rules**:
  [`docs/CONTEXT-ADMISSIBILITY.md`](CONTEXT-ADMISSIBILITY.md)

## Reporting issues

[`https://github.com/jvega017/claude-provenance/issues`](https://github.com/jvega017/claude-provenance/issues)

The CHANGELOG keeps an explicit "still deferred" list with rationale
for each item. If a gap matters to your use case, please open an issue
referencing the CHANGELOG section.
