# Offline-verifiable warrants

WarrantOS does not ask you to trust its ledger. It lets anyone recompute it.

A `warrantos check` run produces an audit trail. The verification layer turns
that trail into a portable, tamper-evident artefact that a third party can
verify offline, with no access to your database and no network call. This is the
HTTPS analogy made literal: a document anyone can check.

## What it gives you

- **A tamper-evident ledger.** `provenance.merkle` builds a deterministic,
  RFC 6962 style Merkle tree (leaf/node domain separation, odd-node promotion)
  over the ordered audit entries. One root digest fixes the entire ledger state:
  any insert, edit, delete, or reorder changes the root.
- **A signed checkpoint.** With the optional `[attestation]` extra, a checkpoint
  root is Ed25519-signed, binding the ledger state to a signer.
- **A portable `.warrant` bundle.** `create_warrant()` packages the prose digest,
  the CBOM, the relevant ledger entries, and the signed checkpoint into a single
  file that travels with the artefact.
- **An offline verifier.** `warrantos verify-external` recomputes the Merkle root
  from the entries and matches it against the checkpoint. The integrity half is
  pure stdlib and needs no key; only signature attribution needs `[attestation]`.
- **A browser verifier.** `web/verify.html` is a zero-backend, client-side
  verifier whose canonical-JSON parser matches the Python verifier byte for byte,
  including astral-plane unicode.

## Fail-closed by default

An unsigned or signature-unavailable bundle verifies as overall **INVALID**
unless you pass `--allow-unsigned` explicitly. An attestation is never silently
accepted without a verified signer. Merkle inclusion proofs bind to
`(index, size)` and reject replayed, wrong-size, or extra-step proofs. Canonical
serialisation rejects NaN and Infinity, a known Python/JS divergence vector, and
is pinned with known-answer vectors.

## Use it

```bash
# 1. Run a normal check; it writes a run directory under .warrant/runs/<id>.
warrantos check final.md \
  --context context.json --actor-identity actor.json --profile final-prose

# 2. Bundle that run into a portable, verifiable artefact.
#    Set WARRANTOS_SIGNING_KEY first to attribute the bundle to a signer.
warrantos attest final.md --run-dir .warrant/runs/<id> --out final.warrant

# 3. Verify it offline, anywhere, with no access to the original ledger.
warrantos verify-external final.warrant --prose final.md
#    Pin the expected signer to assert attribution:
warrantos verify-external final.warrant --prose final.md --key <signer-pubkey-b64url>
#    Accept an integrity-valid but unsigned bundle (drops attribution):
warrantos verify-external final.warrant --allow-unsigned
```

`verify-external` exits non-zero on any failure, so it drops straight into CI as
a release gate. The browser verifier (`web/verify.html`) accepts the same
`.warrant` for a no-install check by a reader who has only the file.

## What signing requires

The standard library ships no public-key signing, so the Ed25519 signature path
needs the optional extra:

```bash
pip install "claude-provenance[attestation]"
```

The **integrity** check (recompute the root, match the checkpoint) needs nothing
beyond the standard library. The project ships **no real default key**; a
production adopter sets `WARRANTOS_SIGNING_KEY`.

## Honest limits

- An unsigned bundle is integrity-verifiable but carries no attribution. It tells
  you the entries have not been tampered with, not who produced them.
- The `.warrant` envelope and canonical serialisation are a project-defined
  format, pinned with known-answer vectors and a Python/JS differential check,
  but not yet a published, versioned standard. A migration to an established
  signed-statement format (DSSE or COSE) is under consideration. See
  [`LIMITATIONS.md`](LIMITATIONS.md).
- Verification proves the audit trail is intact and attributed. It does not prove
  the underlying claims are true. That is the job of the verdict gates, not the
  signature.
