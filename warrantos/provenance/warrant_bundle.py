"""The ``.warrant`` verifiable artefact: attest a document, verify it offline.

A ``.warrant`` bundle is a self-contained, portable record that lets anyone, with
no access to the original ledger and no contact with the author, answer one
question: does this document's evidence trail hold together, and who vouched for
it? It is the artefact that makes the HTTPS analogy literal.

Bundle (a single JSON object):
- ``prose_sha256``: digest of the final prose the bundle attests to.
- ``cbom``: the claim/source bill of materials for the artefact.
- ``ledger_entries``: the ordered, canonicalised ledger rows relevant to the run.
- ``checkpoint``: the Merkle root over those entries, optionally Ed25519-signed.

Verification (``verify_warrant``) is pure stdlib for the integrity half (recompute
the Merkle root from the entries and check it matches the checkpoint) and uses the
optional ``[attestation]`` extra only to check the signature. So a sceptic can
confirm the evidence trail is internally consistent with zero dependencies, and
additionally confirm WHO signed it if they choose to install the extra.
"""

from __future__ import annotations

import hashlib
import json
from typing import List, Optional

from warrantos.provenance import merkle


def _prose_digest(prose: str) -> str:
    return "sha256:" + hashlib.sha256(prose.encode("utf-8")).hexdigest()


def _entry_bytes(entry: dict) -> bytes:
    # Canonical, deterministic serialisation so the root is reproducible anywhere,
    # including in the JavaScript web verifier. allow_nan=False rejects NaN/Infinity,
    # which are not valid JSON and have no JS equivalent (a silent divergence vector).
    return json.dumps(
        entry, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def create_warrant(
    *,
    prose: str,
    cbom: dict,
    ledger_entries: List[dict],
    run_id: str,
    timestamp: str,
    private_seed_b64: Optional[str] = None,
) -> dict:
    """Build a ``.warrant`` bundle. Signs the checkpoint if a key is available.

    ``private_seed_b64`` (or the WARRANTOS_SIGNING_KEY env var) enables signing;
    if neither is present and signing is not possible, the bundle ships with an
    unsigned checkpoint (still integrity-verifiable, just not attributable).
    """
    entry_blobs = [_entry_bytes(e) for e in ledger_entries]
    checkpoint = merkle.build_checkpoint(entry_blobs, run_id=run_id, timestamp=timestamp)

    signed = False
    try:
        from warrantos.provenance import attestation
        try:
            checkpoint = attestation.sign_checkpoint(checkpoint, private_seed_b64)
            signed = True
        except attestation.AttestationUnavailable:
            signed = False
    except ImportError:
        signed = False

    return {
        "version": "warrant-bundle-v1",
        "prose_sha256": _prose_digest(prose),
        "cbom": cbom,
        "ledger_entries": ledger_entries,
        "checkpoint": checkpoint,
        "signed": signed,
    }


def verify_warrant(
    bundle: dict,
    *,
    prose: Optional[str] = None,
    expected_public_key_b64: Optional[str] = None,
    allow_unsigned: bool = False,
) -> dict:
    """Verify a ``.warrant`` bundle offline. Fail-closed by default.

    Returns a result dict with:
    - ``integrity``: ``VALID`` if the Merkle root recomputed from the entries
      matches the checkpoint root, else ``INVALID``. A missing checkpoint or
      missing root is ``INVALID`` (you cannot trust what is not committed to).
    - ``prose``: ``VALID`` / ``INVALID`` / ``NOT_CHECKED`` (only if ``prose`` given).
    - ``signature``: ``VALID`` / ``INVALID`` / ``UNKNOWN_KEY`` / ``UNSIGNED`` /
      ``UNAVAILABLE`` (the [attestation] extra is not installed).
    - ``overall``: ``VALID`` only if integrity is VALID, prose is not INVALID, and
      the signature is VALID. An UNSIGNED or UNAVAILABLE signature is overall
      ``INVALID`` UNLESS ``allow_unsigned=True`` is passed explicitly, so an
      attestation is not silently accepted without a verified signer.
    """
    result = {"integrity": "INVALID", "prose": "NOT_CHECKED", "signature": "UNSIGNED"}
    cp = bundle.get("checkpoint") or {}
    entries = bundle.get("ledger_entries")
    if entries is None:
        entries = []

    # 1. Integrity: recompute the Merkle root from the entries. A bundle with no
    # checkpoint root cannot be integrity-valid (nothing was committed to).
    recomputed = merkle.ledger_root([_entry_bytes(e) for e in entries])
    root = cp.get("root_hash")
    result["integrity"] = "VALID" if (root and recomputed == root) else "INVALID"

    # 2. Prose digest (optional).
    if prose is not None:
        result["prose"] = "VALID" if _prose_digest(prose) == bundle.get("prose_sha256") else "INVALID"

    # 3. Signature (optional extra).
    if cp.get("signature"):
        try:
            from warrantos.provenance import attestation
            result["signature"] = attestation.verify_checkpoint(cp, expected_public_key_b64)
        except ImportError:
            result["signature"] = "UNAVAILABLE"
    else:
        result["signature"] = "UNSIGNED"

    sig_ok = result["signature"] == "VALID" or (
        allow_unsigned and result["signature"] in ("UNSIGNED", "UNAVAILABLE")
    )
    ok = (
        result["integrity"] == "VALID"
        and result["prose"] != "INVALID"
        and sig_ok
    )
    result["overall"] = "VALID" if ok else "INVALID"
    return result
