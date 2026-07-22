# MCP config for Claude Code and Claude Desktop

Two-minute setup so the warrantos pipeline is callable as tools from
inside any Claude session.

## Install with the MCP extra

The authenticated candidate bundle does not install the optional MCP transport.
For source-checkout developer evaluation only, install from the current
WarrantOS repository:

```bash
git clone https://github.com/jvega017/warrantos.git
cd warrantos
python -m pip install -e ".[mcp]"
```

The `[mcp]` extra pulls in the `mcp` SDK. The core repo is stdlib
only; the SDK is only required when you actually want to expose the
tools to Claude over the stdio MCP transport.

## Claude Code (`~/.claude.json`)

Add to the `mcpServers` block:

```json
{
  "mcpServers": {
    "warrantos": {
      "command": "warrantos-mcp",
      "args": []
    }
  }
}
```

If `warrantos-mcp` is not on PATH (you installed in a virtualenv but
Claude Code runs outside it), use the explicit Python path:

```json
{
  "mcpServers": {
    "warrantos": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "warrantos.provenance.mcp_server"]
    }
  }
}
```

Restart Claude Code. The four tools should appear in the tool list:

- `warrant_check`: run the full pipeline over a draft.
- `warrant_classify`: classify a single context item.
- `warrant_record_override`: record a structured human override.
- `warrant_get_run`: read back the per-run artefacts.

## Claude Desktop (`claude_desktop_config.json`)

macOS path: `~/Library/Application Support/Claude/claude_desktop_config.json`
Windows path: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "warrantos": {
      "command": "warrantos-mcp",
      "args": []
    }
  }
}
```

Restart Claude Desktop. The tools appear under the hammer icon in the
chat input.

## Sanity check the wiring

In a Claude session, type:

> Use `warrant_classify` to classify the text "Source: Treasury Bulletin 2026, page 12."

Claude should call the tool and return `context_type:
empirical_evidence`. If the tool does not appear or returns an error,
run `warrantos-mcp` directly from a terminal and look for the
startup message; common failures are PATH issues or the SDK extra
not being installed.

## Verifying without an Anthropic API key

If you do not want to set `ANTHROPIC_API_KEY` (no Anthropic account,
strict data-egress rules, or you just prefer local), three options
are documented in [`NO-API-KEY.md`](NO-API-KEY.md):

1. **Local LLM grader** (Ollama, llama.cpp, vLLM): point the server
   at it via `PROVENANCE_LOCAL_GRADER_URL`.
2. **Claude Code Stop hook** (`warrantos-verify-hook`): verifies
   inside the existing Claude Code session, no separate credentials.
3. **MCP sampling**: designed, deferred to v0.10; documented as a
   gap. See [`NO-API-KEY.md`](NO-API-KEY.md) §3 for the rationale.

All three avoid the Anthropic API entirely while still producing
`contradicted` verdicts. The MCP server inherits whichever path the
host environment makes available.

## Cost-aware defaults

The MCP tools inherit the same offline-by-default discipline as the
CLI. None of the four tools costs API credits unless you explicitly
opt in:

| Tool | Cost |
|---|---|
| `warrant_classify` | Local only. Never costs credits. |
| `warrant_record_override` | Local SQLite write. Never costs credits. |
| `warrant_get_run` | Local file read. Never costs credits. |
| `warrant_check` with `verify=false` (default) | Local only. Never costs credits. |
| `warrant_check` with `verify=true` and `ANTHROPIC_API_KEY` set | Each detected claim consumes one Anthropic API call. |
| `warrant_check` with `verify=true` and no `ANTHROPIC_API_KEY` | Local heuristic verifier; never costs credits. The heuristic cannot emit `contradicted` by construction. |

See [`COST.md`](COST.md) for the full spend-control matrix.

## Pinning the MCP server to a specific working directory

The default working directory is wherever the MCP host launched the
server. For the override ledger (`.warrant/provenance.db`) to be
shared across runs, pin it explicitly:

```json
{
  "mcpServers": {
    "warrantos": {
      "command": "warrantos-mcp",
      "args": [],
      "env": {
        "WARRANTOS_DB": "/path/to/.warrant/provenance.db"
      }
    }
  }
}
```

Then pass `db_path` from `WARRANTOS_DB` when calling
`warrant_record_override`. (At time of writing the server does not
auto-read this env var; passing the path explicitly is the supported
path. Auto-resolution of `WARRANTOS_DB` is a tracked v0.10 item.)

## Troubleshooting

**The server starts but no tools appear in Claude.** Confirm the
`mcp` package is installed: `python -c "import mcp"`. Restart Claude.

**`warrantos-mcp` not found.** The authenticated candidate bundle does not
install the optional MCP transport. Treat MCP setup as source-checkout developer
evaluation until 0.11.0b2 is publicly promoted; do not resolve the obsolete
public `claude-provenance` extra or use the stale `provenance.mcp_server` module
path.

**Server starts then exits immediately.** Run it from a terminal to see the
error. The supported matrix is CPython 3.11 through 3.13. Older interpreters
and unqualified newer interpreters are not supported.

**Tool calls return `error: unknown tool`.** A typo in the tool name.
The four canonical names are `warrant_check`, `warrant_classify`,
`warrant_record_override`, `warrant_get_run`.
