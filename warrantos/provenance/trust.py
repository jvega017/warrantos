"""Pinned signer policy for production-facing WarrantOS verification.

The public key embedded in a ``.warrant`` is self-asserted.  This module makes
the trust decision external: a deployer supplies a pinned trust-root document,
and verification fails closed when it is absent, malformed, or does not match.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class TrustRoot:
    key_id: str
    public_key_b64: str
    algorithm: str = "ed25519"
    schema: str = "warrantos-trust-root/v1"

    def __post_init__(self) -> None:
        if self.schema != "warrantos-trust-root/v1":
            raise ValueError("unsupported trust-root schema")
        if self.algorithm != "ed25519":
            raise ValueError("unsupported trust-root algorithm")
        if not self.key_id or not isinstance(self.key_id, str):
            raise ValueError("trust-root key_id must be non-empty")
        try:
            raw = _b64d(self.public_key_b64)
        except Exception as exc:
            raise ValueError("trust-root public key is not valid base64url") from exc
        if len(raw) != 32:
            raise ValueError("Ed25519 trust-root public key must be exactly 32 bytes")

    @property
    def fingerprint(self) -> str:
        return "sha256:" + hashlib.sha256(_b64d(self.public_key_b64)).hexdigest()

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "public_key": self.public_key_b64,
            "fingerprint": self.fingerprint,
        }


def _b64d(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("empty key")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def load_trust_root(path: str | Path) -> TrustRoot:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    allowed = {"schema", "key_id", "algorithm", "public_key", "fingerprint"}
    extra = set(data) - allowed
    if extra:
        raise ValueError("unknown trust-root field(s): %s" % ", ".join(sorted(extra)))
    root = TrustRoot(
        schema=data.get("schema", ""),
        key_id=data.get("key_id", ""),
        algorithm=data.get("algorithm", ""),
        public_key_b64=data.get("public_key", ""),
    )
    supplied_fingerprint: Optional[str] = data.get("fingerprint")
    if supplied_fingerprint is not None and supplied_fingerprint != root.fingerprint:
        raise ValueError("trust-root fingerprint does not match public key")
    return root


def verify_release_warrant(bundle: dict, *, prose: str, cbom: dict,
                           trust_root: TrustRoot) -> dict:
    """Verify an exact release artefact against an external pinned signer."""
    from warrantos.provenance.warrant_bundle import verify_warrant

    result = verify_warrant(
        bundle,
        prose=prose,
        cbom=cbom,
        expected_public_key_b64=trust_root.public_key_b64,
        allow_unsigned=False,
    )
    result["trust"] = "PINNED" if result.get("signature") == "VALID" else "REJECTED"
    result["trust_root_key_id"] = trust_root.key_id
    result["trust_root_fingerprint"] = trust_root.fingerprint
    result["overall"] = "VALID" if (
        result.get("overall") == "VALID" and result["trust"] == "PINNED"
        and result.get("binding") == "VALID"
    ) else "INVALID"
    return result
