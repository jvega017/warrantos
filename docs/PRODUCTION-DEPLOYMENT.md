# Production deployment prerequisites

Candidate `warrantos-0.11.0b2-local-rc.1` is not tagged or production qualified.
The following controls are deployment prerequisites, not bundled assurances.
No production key is bundled with WarrantOS.

## Required trust material

1. Generate an Ed25519 key outside the application workspace using an approved
   key-management process.
2. Supply the private seed to the attesting process through
   `WARRANTOS_SIGNING_KEY`; do not commit it to a repository or manifest.
3. Distribute the corresponding public key through a separately controlled
   `warrantos-trust-root/v1` document.
4. Pin that document in Vega or call:

   `warrantos-evidence verify-release --warrant release.warrant --prose final.md --cbom cbom.json --trust-root trust-root.json`

The command requires exact prose and CBOM inputs, rejects unsigned bundles,
and rejects a valid signature made by any key other than the pinned key.

## Required host controls

- Authenticate `created_by` and semantic-review principals outside WarrantOS.
  A caller-supplied reviewer label is not identity or authority evidence.
- Keep source bytes available for binding re-verification. A URL is not a
  snapshot.
- Treat standalone `passage_reproduced` as exact bytes, digests and passages
  reproduced only. The compatibility `--reviewer` and `--verdict` flags are
  ignored and cannot create `support_verified`. A host claiming semantic
  support must supply an independently verifiable, authenticated proof bound to
  the exact claim/source/binding hashes and relevant mission/run identifiers.
- Anchor checkpoints to an independently operated timestamp/transparency
  service if resistance to an operator who controls the signing key is needed.
  This candidate does not provide such infrastructure.
- Apply OS-level sandboxing and secret brokering to model/tool processes. Local
  execution alone is not a security boundary.

Until these prerequisites and an external pilot are evidenced, the candidate
remains `production_qualified: false`.
