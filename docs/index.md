# WarrantOS

Every factual claim in an AI-assisted document ships with a source, a `[CITE NEEDED]` tag, or a logged BLOCK. No warrant, no ship.

`claude-provenance` on GitHub and as the legacy Claude Code plugin; `warrantos` on PyPI and the CLI.

## Current acquisition

The public 0.10.0 package and Action are affected by the P0 artefact-binding
advisory and are not recommended. The only recommended current adopter path is
the **authenticated 0.11.0b2 candidate bundle**. Its PowerShell installer must
be authenticated in the parent process with the out-of-band installer and
manifest digests before `-ExpectedManifestSha256` is passed to `install.ps1`.

Start with the [Quickstart](QUICKSTART.md) for the exact fail-closed bootstrap.
Use the [Overview](OVERVIEW.md) to inspect what ships, and read the
[security advisory](https://github.com/jvega017/warrantos/security/policy)
before relying on an older distribution.

## Three ways in

**Lint your docs for AI slop.** Scan for scaffold residue and unsourced claims before a draft goes anywhere. Rules live in one place so a `slop` finding and a `check` violation are always explained the same way. See the [Specification](SPEC.md).

**Gate your agent.** A stdio MCP server and a Claude Code Stop hook check what the model wrote before the turn ends: stdlib only, no network, never breaks the session. See [Plugin](PLUGIN.md) and the [MCP config reference](MCP-CONFIG.md).

**Build an audit trail for governance.** Seal a checked run into a portable `.warrant` bundle that a third party verifies offline, with a zero-backend browser verifier for readers who have only the file. See [Verification](VERIFICATION.md) and the [Compliance mapping](COMPLIANCE.md) to ISO/IEC 42001 and the NIST AI RMF.

## What this does not do

The claim detector is a heuristic and will produce false positives and false negatives. Offline verification checks token overlap, not meaning. It does not replace human review and does not claim to. Read the full list in [Limitations](LIMITATIONS.md).

## Where to go next

- [Status](STATUS.md): the per-layer build-state dashboard
- [Distribution](DISTRIBUTION.md): install surfaces and packaging
- Reference section in the sidebar: deeper design notes, the roadmap, and the multi-agent review record

Source, issues, and releases: [github.com/jvega017/warrantos](https://github.com/jvega017/warrantos)
