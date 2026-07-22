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

    v2 binding: The checkpoint now includes prose_sha256 and cbom_sha256, binding
    all three security-critical assets (prose, claims, ledger) into the signed root.
    """
    entry_blobs = [_entry_bytes(e) for e in ledger_entries]
    prose_sha = _prose_digest(prose)
    cbom_sha = "sha256:" + hashlib.sha256(
        json.dumps(cbom, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    checkpoint = merkle.build_checkpoint(
        entry_blobs, run_id=run_id, timestamp=timestamp,
        prose_sha256=prose_sha, cbom_sha256=cbom_sha
    )

    signed = False
    # Only attempt signing if a key is provided or WARRANTOS_SIGNING_KEY is set
    import os as _os
    key_available = private_seed_b64 or _os.environ.get("WARRANTOS_SIGNING_KEY")

    if key_available:
        try:
            from warrantos.provenance import attestation
            try:
                checkpoint = attestation.sign_checkpoint(checkpoint, private_seed_b64)
                signed = True
            except attestation.AttestationUnavailable:
                signed = False
        except ImportError:
            signed = False
        except Exception:
            # Catch any exception from sign_checkpoint (cryptography errors, pyo3 panics, etc.)
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
    cbom: Optional[dict] = None,
    expected_public_key_b64: Optional[str] = None,
    allow_unsigned: bool = False,
) -> dict:
    """Verify a ``.warrant`` bundle offline. Fail-closed by default.

    Returns a result dict with:
    - ``integrity``: ``VALID`` if the Merkle root recomputed from the entries
      matches the checkpoint root, else ``INVALID``. A missing checkpoint or
      missing root is ``INVALID`` (you cannot trust what is not committed to).
    - ``prose``: ``VALID`` / ``INVALID`` / ``NOT_CHECKED`` (only if ``prose`` given).
    - ``cbom``: ``VALID`` / ``INVALID`` / ``NOT_CHECKED`` (only if ``cbom`` given).
    - ``signature``: ``VALID`` / ``INVALID`` / ``UNKNOWN_KEY`` / ``UNSIGNED`` /
      ``UNAVAILABLE`` (the [attestation] extra is not installed).
    - ``overall``: ``VALID`` only if integrity is VALID, prose/cbom are not INVALID, and
      the signature is VALID. An UNSIGNED or UNAVAILABLE signature is overall
      ``INVALID`` UNLESS ``allow_unsigned=True`` is passed explicitly, so an
      attestation is not silently accepted without a verified signer.

    v2 verification: If the checkpoint includes prose_sha256 and cbom_sha256,
    tampering with those assets after signing will be detected.
    """
    result = {"integrity": "INVALID", "binding": "INVALID", "prose": "NOT_CHECKED", "cbom": "NOT_CHECKED", "signature": "UNSIGNED"}
    cp = bundle.get("checkpoint") or {}
    entries = bundle.get("ledger_entries")
    if entries is None:
        entries = []

    # 1. Integrity: recompute the Merkle root from the entries. A bundle with no
    # checkpoint root cannot be integrity-valid (nothing was committed to).
    recomputed = merkle.ledger_root([_entry_bytes(e) for e in entries])
    root = cp.get("root_hash")
    result["integrity"] = "VALID" if (root and recomputed == root) else "INVALID"

    # The v2 checkpoint commits the bundle-level prose digest and embedded
    # CBOM. Reproduce that binding even when the caller does not separately
    # supply prose/CBOM inputs, so substitution cannot hide behind an omitted
    # optional argument. Legacy checkpoints are explicitly identified rather
    # than silently described as bound.
    if cp.get("version") == "warrantos-checkpoint-v2":
        embedded_cbom_sha = "sha256:" + hashlib.sha256(
            json.dumps(bundle.get("cbom"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        result["binding"] = "VALID" if (
            cp.get("prose_sha256")
            and cp.get("prose_sha256") == bundle.get("prose_sha256")
            and cp.get("cbom_sha256")
            and cp.get("cbom_sha256") == embedded_cbom_sha
        ) else "INVALID"
    else:
        result["binding"] = "LEGACY_UNBOUND"

    # 2. Prose digest (optional). Also check against checkpoint binding if present.
    if prose is not None:
        prose_digest = _prose_digest(prose)
        bundle_digest = bundle.get("prose_sha256")
        checkpoint_digest = cp.get("prose_sha256")
        # Verify against both bundle-level and checkpoint-level digests
        if checkpoint_digest and checkpoint_digest != prose_digest:
            result["prose"] = "INVALID"
        elif bundle_digest and bundle_digest != prose_digest:
            result["prose"] = "INVALID"
        else:
            result["prose"] = "VALID"

    # 3. CBOM digest (optional). Also check against checkpoint binding if present.
    if cbom is not None:
        cbom_sha = "sha256:" + hashlib.sha256(
            json.dumps(cbom, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        checkpoint_cbom = cp.get("cbom_sha256")
        embedded_cbom_sha = "sha256:" + hashlib.sha256(
            json.dumps(bundle.get("cbom"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        if checkpoint_cbom and checkpoint_cbom != cbom_sha:
            result["cbom"] = "INVALID"
        elif embedded_cbom_sha != cbom_sha:
            result["cbom"] = "INVALID"
        else:
            result["cbom"] = "VALID"

    # 4. Signature (optional extra).
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
        and result["binding"] != "INVALID"
        and result["prose"] != "INVALID"
        and result["cbom"] != "INVALID"
        and sig_ok
    )
    result["overall"] = "VALID" if ok else "INVALID"
    return result
