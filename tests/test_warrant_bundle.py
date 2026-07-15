"""Tests for the .warrant verifiable artefact (provenance.warrant_bundle)."""

import os
import unittest

from warrantos.provenance import attestation, warrant_bundle

try:
    _PRIV, _PUB = attestation.generate_keypair()
    _HAVE = True
except attestation.AttestationUnavailable:
    _PRIV = _PUB = None
    _HAVE = False


_LEDGER = [
    {"id": 1, "kind": "claim", "text": "Claim A", "source": "https://example.org/a"},
    {"id": 2, "kind": "claim", "text": "Claim B", "source": None},
    {"id": 3, "kind": "override", "reviewer": "human:director.so"},
]
_CBOM = {"schema": "cbom-v0.2", "claims": 2, "sources": 1}
_PROSE = "# Brief\n\nClaim A is supported. Claim B is flagged.\n"


def _bundle(priv=None):
    return warrant_bundle.create_warrant(
        prose=_PROSE, cbom=_CBOM, ledger_entries=_LEDGER,
        run_id="run_b", timestamp="2026-06-09T00:00:00Z", private_seed_b64=priv,
    )


def _unsigned_bundle():
    # Build an unsigned bundle regardless of any ambient WARRANTOS_SIGNING_KEY.
    old = os.environ.pop("WARRANTOS_SIGNING_KEY", None)
    try:
        return warrant_bundle.create_warrant(
            prose=_PROSE, cbom=_CBOM, ledger_entries=_LEDGER,
            run_id="run_b", timestamp="2026-06-09T00:00:00Z",
        )
    finally:
        if old is not None:
            os.environ["WARRANTOS_SIGNING_KEY"] = old


class TestWarrantBundle(unittest.TestCase):
    def test_unsigned_bundle_is_overall_invalid_by_default(self):
        # Fail-closed: integrity holds, but an UNSIGNED bundle is not overall VALID
        # unless the verifier explicitly opts in. An attestation without a verified
        # signer must not silently read as VALID.
        b = _unsigned_bundle()
        r = warrant_bundle.verify_warrant(b, prose=_PROSE)
        self.assertEqual(r["integrity"], "VALID")
        self.assertEqual(r["signature"], "UNSIGNED")
        self.assertEqual(r["overall"], "INVALID")

    def test_unsigned_bundle_valid_only_with_allow_unsigned(self):
        b = _unsigned_bundle()
        r = warrant_bundle.verify_warrant(b, prose=_PROSE, allow_unsigned=True)
        self.assertEqual(r["overall"], "VALID")

    def test_missing_checkpoint_root_is_invalid(self):
        b = _unsigned_bundle()
        b["checkpoint"].pop("root_hash", None)
        self.assertEqual(warrant_bundle.verify_warrant(b, allow_unsigned=True)["integrity"], "INVALID")

    def test_missing_ledger_entries_is_invalid(self):
        b = _unsigned_bundle()
        b.pop("ledger_entries", None)
        # entries default to [] -> empty root, which will not match a non-empty checkpoint
        self.assertEqual(warrant_bundle.verify_warrant(b, allow_unsigned=True)["integrity"], "INVALID")

    def test_nan_in_entry_is_rejected_at_create(self):
        with self.assertRaises(ValueError):
            warrant_bundle.create_warrant(
                prose=_PROSE, cbom=_CBOM,
                ledger_entries=[{"id": 1, "x": float("nan")}],
                run_id="r", timestamp="2026-06-09T00:00:00Z",
            )

    def test_tampered_ledger_entry_breaks_integrity(self):
        b = _bundle()
        b["ledger_entries"][1]["text"] = "TAMPERED"
        r = warrant_bundle.verify_warrant(b)
        self.assertEqual(r["integrity"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    def test_dropped_ledger_entry_breaks_integrity(self):
        b = _bundle()
        del b["ledger_entries"][0]
        self.assertEqual(warrant_bundle.verify_warrant(b)["integrity"], "INVALID")

    def test_tampered_prose_detected(self):
        b = _bundle()
        r = warrant_bundle.verify_warrant(b, prose=_PROSE + "\nInjected sentence.\n")
        self.assertEqual(r["prose"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    @unittest.skipUnless(_HAVE, "attestation extra not installed")
    def test_signed_bundle_verifies_and_attributes(self):
        b = _bundle(_PRIV)
        self.assertTrue(b["signed"])
        r = warrant_bundle.verify_warrant(b, prose=_PROSE, expected_public_key_b64=_PUB)
        self.assertEqual(r["signature"], "VALID")
        self.assertEqual(r["overall"], "VALID")

    @unittest.skipUnless(_HAVE, "attestation extra not installed")
    def test_signed_bundle_wrong_key_is_unknown(self):
        b = _bundle(_PRIV)
        _op, other_pub = attestation.generate_keypair()
        r = warrant_bundle.verify_warrant(b, expected_public_key_b64=other_pub)
        self.assertEqual(r["signature"], "UNKNOWN_KEY")
        self.assertEqual(r["overall"], "INVALID")

    @unittest.skipUnless(_HAVE, "attestation extra not installed")
    def test_tampering_after_signing_breaks_signature(self):
        b = _bundle(_PRIV)
        b["checkpoint"]["root_hash"] = "sha256:" + "00" * 32
        r = warrant_bundle.verify_warrant(b)
        # integrity already fails (root no longer matches entries) and signature too
        self.assertEqual(r["integrity"], "INVALID")
        self.assertEqual(r["signature"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    # v2 Binding Tests (C1 & C2 vulnerability fix)

    def test_v2_bundle_has_correct_version(self):
        # Verify that new bundles are v2.
        b = _bundle()
        self.assertEqual(b["version"], "warrant-bundle-v2")
        self.assertEqual(b["checkpoint"].get("bundle_version"), "warrant-bundle-v2")

    def test_v2_checkpoint_includes_prose_and_cbom_hashes(self):
        # Verify that v2 checkpoint binds prose and CBOM.
        b = _bundle()
        cp = b["checkpoint"]
        self.assertIn("prose_sha256", cp)
        self.assertIn("cbom_sha256", cp)
        # These should match the top-level fields.
        self.assertEqual(cp["prose_sha256"], b["prose_sha256"])
        expected_cbom_digest = "sha256:" + __import__("hashlib").sha256(
            __import__("json").dumps(
                _CBOM, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(cp["cbom_sha256"], expected_cbom_digest)

    def test_v2_unsigned_bundle_valid_with_prose_and_cbom_ok(self):
        # Unsigned v2 bundle with correct prose and CBOM should be VALID if allow_unsigned.
        b = _unsigned_bundle()
        r = warrant_bundle.verify_warrant(b, prose=_PROSE, allow_unsigned=True)
        self.assertEqual(r["integrity"], "VALID")
        self.assertEqual(r["prose"], "VALID")
        self.assertEqual(r["cbom"], "VALID")
        self.assertEqual(r["signature"], "UNSIGNED")
        self.assertEqual(r["overall"], "VALID")

    def test_v2_signed_bundle_valid_with_prose_and_cbom_ok(self):
        # Signed v2 bundle with correct prose and CBOM should be VALID.
        if not _HAVE:
            self.skipTest("attestation extra not installed")
        b = _bundle(_PRIV)
        r = warrant_bundle.verify_warrant(b, prose=_PROSE, expected_public_key_b64=_PUB)
        self.assertEqual(r["integrity"], "VALID")
        self.assertEqual(r["prose"], "VALID")
        self.assertEqual(r["cbom"], "VALID")
        self.assertEqual(r["signature"], "VALID")
        self.assertEqual(r["overall"], "VALID")

    def test_v2_tampered_prose_breaks_verification(self):
        # Swapping prose should make prose check INVALID.
        b = _bundle()
        r = warrant_bundle.verify_warrant(b, prose=_PROSE + "\nInjected.\n")
        self.assertEqual(r["prose"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    def test_v2_tampered_cbom_breaks_verification(self):
        # Swapping CBOM should make cbom check INVALID and break signature (if signed).
        b = _bundle()
        tampered_cbom = {"schema": "cbom-v0.2", "claims": 999, "sources": 1}
        b["cbom"] = tampered_cbom
        r = warrant_bundle.verify_warrant(b)
        self.assertEqual(r["cbom"], "INVALID")
        # Overall should be INVALID due to cbom mismatch.
        self.assertEqual(r["overall"], "INVALID")

    def test_v2_tampered_cbom_with_signature_breaks_signature(self):
        # If signed, tampering CBOM should break the signature too (since it's part of signed checkpoint).
        if not _HAVE:
            self.skipTest("attestation extra not installed")
        b = _bundle(_PRIV)
        tampered_cbom = {"schema": "cbom-v0.2", "claims": 999, "sources": 1}
        b["cbom"] = tampered_cbom
        r = warrant_bundle.verify_warrant(b)
        # Both cbom and signature should be INVALID.
        self.assertEqual(r["cbom"], "INVALID")
        self.assertEqual(r["signature"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    def test_v2_tampered_ledger_entry_breaks_signature(self):
        # Tampering a ledger entry changes the root, which breaks signature.
        if not _HAVE:
            self.skipTest("attestation extra not installed")
        b = _bundle(_PRIV)
        b["ledger_entries"][1]["text"] = "TAMPERED"
        r = warrant_bundle.verify_warrant(b)
        self.assertEqual(r["integrity"], "INVALID")
        self.assertEqual(r["signature"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    def test_v2_tampered_timestamp_breaks_signature(self):
        # Changing timestamp in checkpoint should break signature.
        if not _HAVE:
            self.skipTest("attestation extra not installed")
        b = _bundle(_PRIV)
        b["checkpoint"]["timestamp"] = "2026-06-10T00:00:00Z"
        r = warrant_bundle.verify_warrant(b)
        # Signature should be INVALID.
        self.assertEqual(r["signature"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    def test_v1_bundle_marked_legacy_unbound(self):
        # v1 bundles (without bundle_version) are marked LEGACY_UNBOUND.
        b = _unsigned_bundle()
        # Manually downgrade to v1 format.
        b["version"] = "warrant-bundle-v1"
        b["checkpoint"].pop("bundle_version", None)
        b["checkpoint"].pop("prose_sha256", None)
        b["checkpoint"].pop("cbom_sha256", None)
        r = warrant_bundle.verify_warrant(b, prose=_PROSE, allow_unsigned=True)
        # Even with all checks passing, v1 bundle is LEGACY_UNBOUND, not VALID.
        self.assertEqual(r["overall"], "LEGACY_UNBOUND")

    def test_v1_bundle_cbom_check_invalid(self):
        # v1 bundles cannot trust cbom (it's unsigned).
        b = _unsigned_bundle()
        # Manually downgrade to v1 format.
        b["version"] = "warrant-bundle-v1"
        b["checkpoint"].pop("bundle_version", None)
        b["checkpoint"].pop("prose_sha256", None)
        b["checkpoint"].pop("cbom_sha256", None)
        r = warrant_bundle.verify_warrant(b, allow_unsigned=True)
        # cbom check should be INVALID for v1 bundles.
        self.assertEqual(r["cbom"], "INVALID")

    def test_missing_cbom_in_v2_makes_cbom_invalid(self):
        # If cbom is missing from bundle, cbom check should be INVALID.
        b = _unsigned_bundle()
        b.pop("cbom", None)
        r = warrant_bundle.verify_warrant(b, allow_unsigned=True)
        self.assertEqual(r["cbom"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    def test_missing_cbom_sha256_in_checkpoint_makes_cbom_invalid(self):
        # If cbom_sha256 is missing from checkpoint, cbom check should be INVALID.
        b = _unsigned_bundle()
        b["checkpoint"].pop("cbom_sha256", None)
        r = warrant_bundle.verify_warrant(b, allow_unsigned=True)
        self.assertEqual(r["cbom"], "INVALID")
        self.assertEqual(r["overall"], "INVALID")

    def test_canonical_json_bytes_consistency(self):
        # Test that canonical_json_bytes is deterministic and consistent.
        from warrantos.provenance import canonical
        obj = {"z": 1, "a": 2, "m": {"nested": True}}
        bytes1 = canonical.canonical_json_bytes(obj)
        bytes2 = canonical.canonical_json_bytes(obj)
        self.assertEqual(bytes1, bytes2)
        # Verify it's sorted and compact.
        self.assertIn(b'"a":2', bytes1)
        self.assertIn(b'"m":{"nested":true}', bytes1)
        self.assertIn(b'"z":1', bytes1)

    def test_canonical_json_bytes_rejects_nan(self):
        # canonical_json_bytes should reject NaN.
        from warrantos.provenance import canonical
        obj = {"x": float("nan")}
        with self.assertRaises(ValueError):
            canonical.canonical_json_bytes(obj)

    def test_cbom_digest_uses_canonical_form(self):
        # _cbom_digest should produce same result regardless of key order.
        cbom1 = {"schema": "cbom-v0.2", "claims": 2, "sources": 1}
        cbom2 = {"sources": 1, "claims": 2, "schema": "cbom-v0.2"}
        digest1 = warrant_bundle._cbom_digest(cbom1)
        digest2 = warrant_bundle._cbom_digest(cbom2)
        self.assertEqual(digest1, digest2)

    def test_round_trip_v2_bundle_integrity(self):
        # Create, serialize, deserialize, verify.
        if not _HAVE:
            self.skipTest("attestation extra not installed")
        import json as json_lib
        b = _bundle(_PRIV)
        # Serialize to JSON and back.
        json_str = json_lib.dumps(b)
        b2 = json_lib.loads(json_str)
        # Verify should still pass.
        r = warrant_bundle.verify_warrant(b2, prose=_PROSE, expected_public_key_b64=_PUB)
        self.assertEqual(r["overall"], "VALID")


if __name__ == "__main__":
    unittest.main()
