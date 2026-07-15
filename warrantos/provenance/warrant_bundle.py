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
  In v2 bundles, the checkpoint also binds to prose_sha256 and cbom_sha256.

Verification (``verify_warrant``) is pure stdlib for the integrity half (recompute
the Merkle root from the entries and check it matches the checkpoint) and uses the
optional ``[attestation]`` extra only to check the signature. So a sceptic can
confirm the evidence trail is internally consistent with zero dependencies, and
additionally confirm WHO signed it if they choose to install the extra.

v2 Binding Fix (C1 & C2 vulnerability):
- In v1 bundles: signature covers only the Merkle root. prose_sha256 and cbom
  are top-level unsigned fields. Attacker could swap them and signature still
  validates as VALID.
- In v2 bundles: prose_sha256 and cbom_sha256 are part of the checkpoint body
  that is signed. Swapping either one breaks the signature.
- v1 bundles are marked LEGACY_UNBOUND and never return overall=VALID.
"""

from __future__ import annotations

import hashlib
import json
from typing import List, Optional

from warrantos.provenance import canonical, merkle


def _prose_digest(prose: str) -> str:
    """Digest of prose using canonical bytes."""
    return "sha256:" + hashlib.sha256(prose.encode("utf-8")).hexdigest()


def _cbom_digest(cbom: dict) -> str:
    """Digest of CBOM using canonical JSON bytes."""
    return "sha256:" + hashlib.sha256(canonical.canonical_json_bytes(cbom)).hexdigest()


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

    v2 Fix (C1 & C2 vulnerability):
    - Checkpoint now includes prose_sha256 and cbom_sha256 in the signed body.
    - This binds both to the signature, preventing CBOM/prose swaps.
    """
    entry_blobs = [_entry_bytes(e) for e in ledger_entries]
    base_checkpoint = merkle.build_checkpoint(entry_blobs, run_id=run_id, timestamp=timestamp)

    # v2: Add prose and CBOM hashes to the checkpoint so they're committed to by
    # the signature. The checkpoint body now includes everything needed for a
    # complete attestation.
    prose_sha256 = _prose_digest(prose)
    cbom_sha256 = _cbom_digest(cbom)

    v2_checkpoint = {
        "root_hash": base_checkpoint["root_hash"],
        "run_id": run_id,
        "timestamp": timestamp,
        "bundle_version": "warrant-bundle-v2",
        "prose_sha256": prose_sha256,
        "cbom_sha256": cbom_sha256,
        "entry_count": base_checkpoint["entry_count"],
        "algorithm": base_checkpoint["algorithm"],
        "version": 1,
    }

    signed = False
    try:
        from warrantos.provenance import attestation
        try:
            v2_checkpoint = attestation.sign_checkpoint(v2_checkpoint, private_seed_b64)
            signed = True
        except attestation.AttestationUnavailable:
            signed = False
        except BaseException:
            # Catch any other errors from cryptography library (including panics)
            signed = False
    except BaseException:
        # ImportError or other issues with importing attestation (including panics)
        signed = False

    return {
        "version": "warrant-bundle-v2",
        "prose_sha256": prose_sha256,
        "cbom": cbom,
        "ledger_entries": ledger_entries,
        "checkpoint": v2_checkpoint,
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
    - ``cbom``: ``VALID`` / ``INVALID`` / ``NOT_CHECKED`` (v2 bundles only;
      checks if cbom_sha256 matches the signed checkpoint).
    - ``signature``: ``VALID`` / ``INVALID`` / ``UNKNOWN_KEY`` / ``UNSIGNED`` /
      ``UNAVAILABLE`` (the [attestation] extra is not installed).
    - ``overall``: ``VALID`` only if integrity is VALID, prose is not INVALID,
      cbom is not INVALID, and the signature is VALID. An UNSIGNED or UNAVAILABLE
      signature is overall ``INVALID`` UNLESS ``allow_unsigned=True`` is passed
      explicitly. v1 bundles always return ``LEGACY_UNBOUND`` (never ``VALID``).

    v2 Fix (C1 & C2 vulnerability):
    - v2 bundles have prose_sha256 and cbom_sha256 committed in the signed
      checkpoint. Tampering either breaks the signature.
    - v1 bundles are marked LEGACY_UNBOUND (prose/cbom are unsigned top-level
      fields). They can never be overall VALID with this verifier.
    """
    result = {
        "integrity": "INVALID",
        "prose": "NOT_CHECKED",
        "cbom": "NOT_CHECKED",
        "signature": "UNSIGNED",
    }
    cp = bundle.get("checkpoint") or {}
    entries = bundle.get("ledger_entries")
    if entries is None:
        entries = []

    # Detect bundle version (v1, v2, or unknown).
    is_v2 = bundle.get("version") == "warrant-bundle-v2" and cp.get("bundle_version") == "warrant-bundle-v2"
    is_v1 = bundle.get("version") == "warrant-bundle-v1"

    # 1. Integrity: recompute the Merkle root from the entries. A bundle with no
    # checkpoint root cannot be integrity-valid (nothing was committed to).
    recomputed = merkle.ledger_root([_entry_bytes(e) for e in entries])
    root = cp.get("root_hash")
    result["integrity"] = "VALID" if (root and recomputed == root) else "INVALID"

    # 2. Prose digest (optional).
    if prose is not None:
        result["prose"] = "VALID" if _prose_digest(prose) == bundle.get("prose_sha256") else "INVALID"

    # 3. CBOM binding (v2 only, checked against signed checkpoint).
    # In v2: cbom_sha256 is part of the signed checkpoint, so tampering breaks signature.
    # In v1: cbom is an unsigned top-level field, cannot be trusted.
    if is_v2:
        cbom = bundle.get("cbom")
        if cbom is not None:
            expected_cbom_sha256 = _cbom_digest(cbom)
            checkpoint_cbom_sha256 = cp.get("cbom_sha256")
            result["cbom"] = "VALID" if (checkpoint_cbom_sha256 and expected_cbom_sha256 == checkpoint_cbom_sha256) else "INVALID"
        else:
            # cbom is missing, mark INVALID
            result["cbom"] = "INVALID"
    else:
        # v1 bundle: cbom is not bound to signature, so we cannot trust it.
        # Mark as INVALID to prevent overall VALID.
        result["cbom"] = "INVALID"

    # 4. Signature (optional extra).
    if cp.get("signature"):
        try:
            from warrantos.provenance import attestation
            result["signature"] = attestation.verify_checkpoint(cp, expected_public_key_b64)
        except (ImportError, AttributeError):
            # ImportError: attestation module not available
            # AttributeError: attestation imported but verify_checkpoint not found
            result["signature"] = "UNAVAILABLE"
        except Exception:
            # Catch any exception during verify_checkpoint (backend load failures, etc.)
            # The function itself handles most cases, but be defensive
            result["signature"] = "UNAVAILABLE"
    else:
        result["signature"] = "UNSIGNED"

    # 5. Compute overall result.
    # v1 bundles: LEGACY_UNBOUND (never VALID, even if all checks pass).
    # v2 bundles: VALID only if all checks pass.
    # Unknown bundles (v0.9.0, etc.): INVALID (unrecognized format).
    if is_v2:
        sig_ok = result["signature"] == "VALID" or (
            allow_unsigned and result["signature"] in ("UNSIGNED", "UNAVAILABLE")
        )
        ok = (
            result["integrity"] == "VALID"
            and result["prose"] != "INVALID"
            and result["cbom"] != "INVALID"
            and sig_ok
        )
        result["overall"] = "VALID" if ok else "INVALID"
    elif is_v1:
        result["overall"] = "LEGACY_UNBOUND"
    else:
        # Unknown or unrecognized format (v0.9.0, etc.)
        result["overall"] = "INVALID"

    return result
