# Verifying claims without an Anthropic API key

Three paths to get the `contradicted` verdict (or any LLM verdict)
without setting `ANTHROPIC_API_KEY`. Pick one based on what you have
available. All three are documented surface area; none uses hidden
inheritance.

## Decision tree

| You have... | Use |
|---|---|
| A local LLM (Ollama, llama.cpp, LM Studio, vLLM) | **Local LLM grader** (this page §1) |
| Claude Code installed, with hooks enabled | **Claude Code Stop hook** (this page §2) |
| Claude Desktop with sampling support | **MCP sampling** (this page §3: design only; deferred to v0.10) |
| None of the above | Heuristic grader (default). Free, deterministic, cannot emit `contradicted`. |

## §1. Local LLM grader

The grader speaks the OpenAI-compatible `/v1/chat/completions` shape
so it works with any of: Ollama, llama.cpp's server, LM Studio, vLLM,
and most local-LLM tools.

### Set up Ollama in two commands

```bash
ollama pull llama3.2
ollama serve  # listens on http://localhost:11434
```

### Point warrantos at it

```bash
export PROVENANCE_LOCAL_GRADER_URL=http://localhost:11434/v1/chat/completions
export PROVENANCE_LOCAL_GRADER_MODEL=llama3.2

warrantos check examples/quickstart-demo/draft.md \
  --context examples/quickstart-demo/context.json \
  --actor-identity examples/quickstart-demo/actor.json \
  --verify --no-fetch
```

The verifier now uses your local model. The `verifier_rows` field in
the report carries `grader: local-llm:llama3.2` instead of
`heuristic`.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PROVENANCE_LOCAL_GRADER_URL` | (unset) | Required to activate. Full URL to the chat-completions endpoint. |
| `PROVENANCE_LOCAL_GRADER_MODEL` | `llama3.2` | Model name passed in the request body. |
| `PROVENANCE_LOCAL_GRADER_API_KEY` | (unset) | Optional `Authorization: Bearer ...` for self-hosted vLLM behind nginx, etc. Most local servers need none. |
| `PROVENANCE_LOCAL_GRADER_TIMEOUT` | `60` | Per-call timeout in seconds. |

### Cost and data egress

| Concern | Reality |
|---|---|
| API cost | **0**. No external calls. |
| Data egress | **0**. The claim and source text never leave the local host. |
| Anthropic account | Not required. |
| Fallback if endpoint is down | The grader silently falls back to the heuristic; no run breaks. |

### Trade-offs

- A local model's `contradicted` verdicts depend on the model's
  quality. Llama 3.2 8B-Instruct is competent at basic
  contradiction; smaller models may miss subtle ones.
- The heuristic-vs-local-LLM grader-precision comparison
  (`eval/run_eval.py`) is the way to calibrate before relying on the
  local path for high-stakes verification.

## §2. Claude Code Stop hook

The `hooks/claude_code_verify_hook.py` script hands unverified
load-bearing claims back to the **same Claude Code session** that
wrote the draft. The session does the verification using its existing
auth; no separate API key, no separate model, no extra cost.

### Wire it in

Add to `~/.claude/settings.json` (or `.claude/settings.json` for a
single project):

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "python /path/to/claude-provenance/hooks/claude_code_verify_hook.py",
        "blocking": true
      }
    ]
  }
}
```

After installing with `pip install claude-provenance`, you can also
launch the hook by entry point:

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "warrantos-verify-hook",
        "blocking": true
      }
    ]
  }
}
```

(The `warrantos-verify-hook` entry point is shipped from v0.8.)

### What the hook does

1. Reads the most recent `.warrant/runs/<run_id>/` directory.
2. If `verdict == HOLD` and there are load-bearing unsupported
   claims, prints a structured hand-back message to stderr and exits
   2 (which Claude Code reads as feedback for the next turn).
3. Claude reads the message in the next turn and verifies the claims
   using the session's own model.
4. Loop-safe: if the same hand-back has just been delivered, the
   hook silently passes through rather than re-blocking.

### Cost and credit usage

| Concern | Reality |
|---|---|
| Separate API key | Not required. |
| Cost | Whatever your Claude Code session normally costs (Pro / Max plan, or pay-as-you-go API). The hook adds no separate billing. |
| Anthropic account | The one you already use for Claude Code. |
| Privacy | The claims stay in the session you are already running them in. |

### Trade-offs

- Verification quality depends on the model in your Claude session.
  An Opus session verifies more accurately than a Haiku session.
- Not all Claude sessions have the context for every domain claim;
  the hook explicitly asks Claude to flag uncertainty rather than
  hallucinate a verdict.

## §3. MCP sampling (design only; deferred to v0.10)

The MCP protocol supports a `sampling/createMessage` request type: an
MCP server can ask the **host** (Claude Code, Claude Desktop) to make
an LLM call on its behalf. The host's credentials and billing apply.
The server never sees an API key.

This is the **canonical "no separate API key" path** for the warrantos
MCP server: when `warrant_check` is invoked over MCP, the server
would call back through sampling to verify each detected claim.

**Status:** designed, not implemented in v0.9.0b1. v0.9 shipped
empirical calibration on real briefs, INV-004 storage-level append-
only triggers, and the per-layer conformance dashboard. MCP sampling
implementation requires host-side permission UX work that is still
scoped: most current MCP hosts surface each sampling call as an
interactive permission prompt, and the unattended trade-off has not
been resolved.

The wiring requires:

1. A new `MCPSamplingGrader` class that takes a sampling callback.
2. `tool_warrant_check` accepting an optional `use_mcp_sampling=True`
   argument that constructs the callback.
3. Documentation for the host's sampling permission model (the user
   must approve each sampling call by default in current Claude
   hosts; the trade-off vs unattended runs is a real UX decision).

Tracked as a v0.10 deferral in CHANGELOG. Today:

- For interactive Claude Code use, prefer §2 (Stop hook).
- For unattended use without an Anthropic API key, prefer §1 (local
  LLM).

## Summary

| Path | API key | Cost | Data leaves local | Verdict quality |
|---|---|---|---|---|
| Heuristic (default) | None | 0 | No (only the URL fetch) | Cannot emit `contradicted` |
| §1 Local LLM | None | 0 | No | Model-dependent |
| §2 Claude Code hook | None separately | Your Claude session cost | Yes (to Claude session) | Session-model-dependent |
| §3 MCP sampling (deferred, v0.10) | None separately | Your host's session cost | Yes (to host) | Host-model-dependent |
| Anthropic LLM grader | `ANTHROPIC_API_KEY` | Per claim, ~USD 0.01 | Yes (to Anthropic) | Highest |
