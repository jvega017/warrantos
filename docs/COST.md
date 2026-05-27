# Cost model and spend control

`claude-provenance` is **free by default**. Every layer that ships in
the beta runs locally on stdlib only. The only stage that can incur
spend is the Layer 7 G2 LLM grader, and it is opt-in. This document
gives you the matrix and the flags.

## What runs locally (no cost)

| Stage | What it does | Cost |
|---|---|---|
| Layer 1 classifier | Regex-based 11-class assignment | Local; 0 |
| Layer 2 ledger writes | SQLite append-only | Local; 0 |
| Layer 3 derived requirements | Rule-based transforms | Local; 0 |
| Layer 4 admissibility | Per-item flag emission | Local; 0 |
| Layer 5 writer pack | In-memory composition | Local; 0 |
| Layer 6 discipline mode | Argument-shape check | Local; 0 |
| Layer 6 subprocess isolation | Local subprocess; depends on what your subprocess does | Local; 0 (unless the subprocess itself spends) |
| Layer 7 G1 boundary scan | Regex over the draft | Local; 0 |
| Layer 7 G2 **claim detection** | Regex via `CLAIM_TRIGGERS` | Local; 0 |
| Layer 7 G2 **offline verifier** (default) | Token-overlap heuristic against fetched URL text | Local; **0** even on `--verify` (uses heuristic) |
| Layer 7 G2 **online verifier (URL fetch)** | HTTP GET of cited URL (3 redirects, 1.5 MB cap) | Local CPU + your bandwidth; 0 API credits |
| Layer 7 G3 self-grounding | Model-family registry lookup | Local; 0 |
| Layer 7 G4 contamination scan | Regex against documented starter list | Local; 0 |
| Layer 7 G5 calibration | Brier score over verdicts | Local; 0 |
| Override ledger | SQLite append-only | Local; 0 |
| CBOM assembly | In-memory dataclass build | Local; 0 |
| Reader-facing footer | Markdown render | Local; 0 |
| MCP server stdio transport | Local process | Local; 0 |
| Classifier corpus runner | Stdlib JSONL + regex | Local; 0 |

A default `warrantos check draft.md` invocation passes through every
stage above. **Zero credits consumed.**

## What costs API credits

| Stage | Trigger | Per-call cost |
|---|---|---|
| Layer 7 G2 LLM grader | `--verify` flag AND `ANTHROPIC_API_KEY` env var set | One Anthropic API call per detected claim |
| Layer 7 G2 Local LLM grader | `--verify` flag AND `PROVENANCE_LOCAL_GRADER_URL` env var set | **0 API credits**. Uses your local LLM (Ollama, llama.cpp, vLLM). See [`NO-API-KEY.md`](NO-API-KEY.md) §1. |
| Layer 7 G2 Claude Code Stop hook | Hook wired to `~/.claude/settings.json` | **0 separate credits**. Verifies inside your Claude Code session using its existing auth. See [`NO-API-KEY.md`](NO-API-KEY.md) §2. |

Three ways to get `contradicted` verdicts without paying Anthropic
API credits. See [`docs/NO-API-KEY.md`](NO-API-KEY.md) for the
decision tree and configuration. Without any of the three, `--verify`
falls back to the offline heuristic, which cannot emit
`contradicted` by construction.

## Spend-control flags

Three flags keep the bill bounded when you do opt in to the LLM
grader:

| Flag | Effect |
|---|---|
| `--max-verify-claims N` | Verify at most N claims per run, prioritised by salience. Default 0 = no cap. |
| `--salience-min FLOAT` | Verify only claims at or above this salience score. Default 0.0 = verify every detected claim. The salience module's documented `LOAD_BEARING_THRESHOLD` is 0.5; passing `--salience-min 0.5` only verifies load-bearing claims. |
| `--no-fetch` | Skip URL fetches even when verifying. Useful in CI runners with no network. |

When either cap fires, the report shows what was skipped:

```json
"verifier_skipped": {
  "reason": "salience_min",
  "count": 8,
  "examples": ["The team met on Tuesday.", "..."]
}
```

## Recommended profiles

| Use case | Recommended flags | Cost profile |
|---|---|---|
| CI on every commit | `--profile final-prose --ci` (no `--verify`) | Local heuristic only; free |
| Daily brief shadow-mode observation | `tools/warrantos-shadow-observe.py --profile brief-light` (no `--verify`) | Local heuristic only; free |
| Pre-publication pass on a Cabinet brief | `--verify --salience-min 0.5 --max-verify-claims 20` | One LLM call per load-bearing claim, capped at 20 per run |
| Pre-publication pass on an academic paper | `--verify --salience-min 0.3 --max-verify-claims 100` | One LLM call per moderately-load-bearing claim, capped at 100 |
| Worst case (verify everything) | `--verify` with no caps | One LLM call per detected claim. Use only on short, high-stakes drafts. |

## What an LLM grader call costs in practice

The grader uses the model identifier from `PROVENANCE_GRADER_MODEL`
(default `claude-haiku-4-5-20251001`). Each call sends roughly:

- 200-400 tokens of system prompt (cached after the first call in a
  session).
- The claim sentence (typically 20-50 tokens).
- The fetched source text, capped at 1.5 MB but typically truncated
  by the grader to ~2,000 tokens.

Order-of-magnitude estimate using Anthropic's published Haiku 4.5
pricing as of 2026: under USD 0.01 per claim on most drafts. A
20-claim run is on the order of USD 0.10-0.20. A 100-claim
academic-paper run is on the order of USD 0.50-1.00. These are
order-of-magnitude estimates; the authoritative current pricing lives
at anthropic.com/pricing.

Override the model with `PROVENANCE_GRADER_MODEL=claude-opus-4-7` if
you need higher-quality verification at higher cost.

## Free fallbacks that are still useful

Even without an `ANTHROPIC_API_KEY`:

1. The offline heuristic returns `verified` when the source text
   contains tokens from the claim, `not_addressed` when it does not,
   and `unverifiable` when the citation cannot be machine-checked.
2. `unverifiable` load-bearing claims still produce a `HOLD` verdict.
3. The boundary scan, the classifier, the override discipline, the
   override footer, and the CBOM v0.2 fields all work identically.

The honest claim: **WarrantOS does most of its work without spending
a credit**. The LLM grader is a sharper tool for the
contradicted-claim path; it is not a precondition for getting value.

## Threat model: what costs can NOT be hidden

Three categories of spend are NOT controlled by the warrantos CLI:

1. **Caller-supplied writer subprocess** (`run_clean_room_subprocess`).
   The subprocess command you supply may call any LLM. The
   `extra_env_allowlist` is the deliberate path for threading a key
   to it; this is an explicit operator choice, not silent inheritance.
2. **MCP host model usage** (Claude Code or Claude Desktop calling
   tools). The MCP transport does not itself cost credits, but the
   Claude session calling the tools does. That cost is your normal
   Claude usage cost and is governed by Anthropic's billing for your
   account, not by anything in this repo.
3. **Network fetches** (`fetch_text`). The verifier fetches cited
   URLs. This consumes bandwidth and is rate-limited only by the
   1.5 MB read cap. Use `--no-fetch` if you need a fully offline
   pass.

All three categories are documented surface area; none is silent.
