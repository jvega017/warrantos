# Security policy

`claude-provenance` is a governance-adjacent tool: it logs claim provenance, context admissibility, and human overrides. Defects in this surface can undermine the audit guarantee the tool is designed to provide. Please report security issues responsibly.

## Supported versions

| Version | Supported | Notes |
|---|---|---|
| `0.11.0b1` local release candidate rc.1 | Candidate only | v2 bundle binding and pinned-trust verification are implemented and tested; no `v0.11.0b1` tag or production qualification |
| `0.10.0` and earlier | No | Latest tagged version; P0 Advisory: `.warrant` bundles do not bind prose and CBOM to the checkpoint. See below. |


The version table describes repository security capability, not a release or
production-readiness guarantee. `release-manifest.json` is canonical.
## P0 Advisory: v0.10.0 and earlier warrant bundles

**Affected versions:** `0.10.0` and earlier

**Vulnerability:** The Merkle checkpoint in `.warrant` bundles attests to the ledger entries (claims and verifications) only. It does not include a binding to the prose (`prose_sha256`) or CBOM (`cbom_sha256`). An adversary with access to a signed bundle can mutate the prose or claims after the bundle is signed, and the signature verification will pass because the checkpoint and signature have not changed.

**Mitigation:**
1. Use a reviewed local release candidate that declares `0.11.0b1`, or wait for a tagged release containing the v2 binding. Confirm the emitted checkpoint is `warrantos-checkpoint-v2`.
2. Re-attest your checked runs with `warrantos attest` (generates v2 bundles automatically).
3. Discard old `.warrant` files or mark them `LEGACY_UNBOUND` in your audit trail.
4. When verifying external bundles, inspect the checkpoint `version` field: `warrantos-checkpoint-v2` is safe, `warrantos-checkpoint-v1` or `warrantos-checkpoint-v0` require manual audit of prose and CBOM integrity before relying on the signature.

**Technical details:** In local release candidate rc.1 declaring 0.11.0b1, `build_checkpoint()` in `merkle.py` accepts optional `prose_sha256` and `cbom_sha256` parameters and includes them in the checkpoint object before signing. Production-facing verification additionally requires an external pinned trust root. The lower-level compatibility API can inspect unsigned bundles only when `allow_unsigned=True`; such output is not a production attestation.

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
- Adversarial prompt injection in the underlying LLM (Layer 7 G4 ships a domain-extended internal corpus and still needs adopter-supplied threat models).

## Hardening notes for adopters

- Pin the `WARRANTOS_DB` location and back the SQLite file up.
- Do not edit the ledger tables manually. INV-004 triggers will raise; if you find a path that bypasses them, that is a security issue.
- Run the override ledger on a filesystem with append-only or write-once support where possible.
- Treat the per-run `.warrant/runs/<run_id>/` artefacts as audit evidence, not transient scratch space.
