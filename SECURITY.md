# Security policy

`claude-provenance` is a governance-adjacent tool: it logs claim provenance, context admissibility, and human overrides. Defects in this surface can undermine the audit guarantee the tool is designed to provide. Please report security issues responsibly.

## Supported versions

| Version | Supported |
|---|---|
| `0.9.x` (current beta) | Yes |
| `< 0.9` | No (please upgrade) |

## How to report a vulnerability

Email: **security@prometheuspolicylab.com** (preferred) or open a private security advisory via [GitHub Security Advisories](https://github.com/jvega017/warrantos/security/advisories/new).

Please do **not** file a public issue for a suspected vulnerability. A public issue alerts every reader before the fix lands.

## What to include

To help triage quickly:

- A description of the issue and which guarantee it undermines (e.g. "the override ledger can be silently edited", "the prose-boundary gate can be bypassed by `<specific input>`", "the CBOM omits a recorded context use under `<condition>`").
- A minimal reproduction. A failing test case in the format used by `tests/` is ideal; a `warrantos check` command line that demonstrates the issue is also acceptable.
- Your assessment of severity and the realistic threat model.
- Whether you have already disclosed publicly (or plan to).

## What to expect

- Acknowledgement within 7 days.
- An assessment of severity and a remediation plan, or an explanation if the report is out of scope, within 14 days.
- A coordinated-disclosure window of up to 90 days from acknowledgement, agreed with the reporter.
- Credit in the CHANGELOG when the fix lands, unless you prefer to remain anonymous.

## Scope

In scope:

- Defects in the eight WarrantOS layers (`provenance/*`, `cli/warrantos_cli.py`, `hooks/claude_code_verify_hook.py`).
- Bypasses of any output integrity gate (G1-G5) under documented configuration.
- Override-ledger integrity (INV-004 append-only, SPEC-L8-S004 write-path validation, SPEC-L8-S003 separation of duties).
- MCP server tool surface (`provenance/mcp_server.py`).

Out of scope:

- Behaviour of arbitrary upstream LLMs that the tool wraps. The tool's audit guarantees do not assert that the LLM produced correct text; they assert that the artefact and its provenance are recorded faithfully.
- Issues with `provenance` (the legacy v0.3 citation CLI) that do not also affect `warrantos`. The legacy CLI is kept for compatibility; security maintenance prioritises `warrantos`.
- Adversarial prompt injection in the underlying LLM (Layer 7 G4 ships a STARTER corpus and is explicitly documented as needing adopter-supplied threat models).

## Hardening notes for adopters

- Pin the `WARRANTOS_DB` location and back the SQLite file up.
- Do not edit the ledger tables manually. INV-004 triggers will raise; if you find a path that bypasses them, that is a security issue.
- Run the override ledger on a filesystem with append-only or write-once support where possible.
- Treat the per-run `.warrant/runs/<run_id>/` artefacts as audit evidence, not transient scratch space.
