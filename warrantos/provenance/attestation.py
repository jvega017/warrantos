"""Ed25519 signed checkpoints: the asymmetric trust anchor for attestation.

This is the ONE optional dependency in the project. The integrity core
(``provenance.merkle``) is pure stdlib: a Merkle root fixes the ledger state and
anyone can recompute it with no key. Signing turns that root into a verifiable
*attestation*: a third party with only the public key can confirm who vouched for
a given ledger state, without the private key and without contacting the signer.

That asymmetric property cannot be had from the standard library (it ships no
public-key signing), so Ed25519 lives behind the ``[attestation]`` extra:

    pip install "claude-provenance[attestation]"

If the extra is not installed, importing the signing functions raises
``AttestationUnavailable`` with that hint. The stdlib integrity check and Merkle
inclusion proofs keep working without it; only the signature layer is gated.

Keys are raw 32-byte Ed25519 seeds/points, base64url-encoded in JSON so a
checkpoint is a small, portable, copy-pasteable object. Production adopters set
``WARRANTOS_SIGNING_KEY`` (base64url private seed); the project ships no real
default key, by design.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Optional, Tuple


class AttestationUnavailable(RuntimeError):
    """Raised when signing is requested but the [attestation] extra is absent."""


def _load_backend():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise AttestationUnavailable(
            "Ed25519 signing requires the optional dependency. Install with: "
            'pip install "claude-provenance[attestation]"'
        ) from exc
    return Ed25519PrivateKey, Ed25519PublicKey, serialization


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def canonical_bytes(body: dict) -> bytes:
    """Deterministic serialisation of a checkpoint body for signing.

    Sorted keys, no whitespace, UTF-8. The ``signature`` and ``public_key``
    fields are excluded so signing and verifying agree on exactly the committed
    content regardless of how the signed object is later reassembled.
    """
    payload = {k: v for k, v in body.items() if k not in ("signature", "public_key")}
    # allow_nan=False: NaN/Infinity are not valid JSON and cannot round-trip to the
    # JavaScript verifier, so a checkpoint containing them must not be signable.
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def generate_keypair() -> Tuple[str, str]:
    """Return (private_seed_b64, public_key_b64). The private seed is secret."""
    Ed25519PrivateKey, _Pub, serialization = _load_backend()
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return _b64e(seed), _b64e(pub)


def _signing_key_from(private_seed_b64: Optional[str]):
    Ed25519PrivateKey, _Pub, _ser = _load_backend()
    seed_b64 = private_seed_b64 or os.environ.get("WARRANTOS_SIGNING_KEY")
    if not seed_b64:
        raise AttestationUnavailable(
            "No signing key. Pass one or set WARRANTOS_SIGNING_KEY "
            "(base64url Ed25519 seed). Generate with generate_keypair()."
        )
    return Ed25519PrivateKey.from_private_bytes(_b64d(seed_b64))


def sign_checkpoint(body: dict, private_seed_b64: Optional[str] = None) -> dict:
    """Sign a checkpoint body. Returns the body plus signature and public_key.

    The signature covers ``canonical_bytes(body)``, so it commits to the Merkle
    root and every other field except the signature/public_key themselves.
    """
    _Priv, _Pub, serialization = _load_backend()
    priv = _signing_key_from(private_seed_b64)
    msg = canonical_bytes(body)
    sig = priv.sign(msg)
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    signed = dict(body)
    signed["public_key"] = _b64e(pub)
    signed["signature"] = _b64e(sig)
    return signed


def verify_checkpoint(signed: dict, expected_public_key_b64: Optional[str] = None) -> str:
    """Verify a signed checkpoint.

    Returns one of: ``VALID``, ``INVALID`` (signature does not match),
    ``UNKNOWN_KEY`` (a public key was expected and this one differs), or
    ``MALFORMED`` (missing fields). Does not raise on a bad signature, so a
    verifier can branch on the outcome.
    """
    sig_b64 = signed.get("signature")
    pub_b64 = signed.get("public_key")
    if not sig_b64 or not pub_b64:
        return "MALFORMED"
    if expected_public_key_b64 and pub_b64 != expected_public_key_b64:
        return "UNKNOWN_KEY"
    _Priv, Ed25519PublicKey, _ser = _load_backend()
    try:
        from cryptography.exceptions import InvalidSignature
        pub = Ed25519PublicKey.from_public_bytes(_b64d(pub_b64))
        pub.verify(_b64d(sig_b64), canonical_bytes(signed))
        return "VALID"
    except InvalidSignature:
        return "INVALID"
    except Exception:
        return "MALFORMED"
