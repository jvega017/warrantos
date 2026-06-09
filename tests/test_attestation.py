"""Tests for the Ed25519 attestation layer (provenance.attestation).

These exercise the real signing path, which requires the optional [attestation]
extra. If cryptography is absent the whole module is skipped, matching the
optional-dependency design.
"""

import unittest

from provenance import attestation

try:
    attestation.generate_keypair()
    _HAVE = True
except attestation.AttestationUnavailable:
    _HAVE = False


@unittest.skipUnless(_HAVE, "attestation extra (cryptography) not installed")
class TestAttestation(unittest.TestCase):
    def setUp(self):
        self.priv, self.pub = attestation.generate_keypair()
        self.body = {
            "version": "warrantos-checkpoint-v1",
            "root_hash": "sha256:" + "ab" * 32,
            "entry_count": 3,
            "run_id": "run_t",
            "timestamp": "2026-06-09T00:00:00Z",
        }

    def test_sign_then_verify_is_valid(self):
        signed = attestation.sign_checkpoint(self.body, self.priv)
        self.assertEqual(signed["public_key"], self.pub)
        self.assertEqual(attestation.verify_checkpoint(signed), "VALID")

    def test_verify_with_matching_expected_key(self):
        signed = attestation.sign_checkpoint(self.body, self.priv)
        self.assertEqual(attestation.verify_checkpoint(signed, self.pub), "VALID")

    def test_tampered_body_is_invalid(self):
        signed = attestation.sign_checkpoint(self.body, self.priv)
        signed["entry_count"] = 999  # change a committed field
        self.assertEqual(attestation.verify_checkpoint(signed), "INVALID")

    def test_tampered_root_is_invalid(self):
        signed = attestation.sign_checkpoint(self.body, self.priv)
        signed["root_hash"] = "sha256:" + "00" * 32
        self.assertEqual(attestation.verify_checkpoint(signed), "INVALID")

    def test_wrong_expected_key_is_unknown_key(self):
        signed = attestation.sign_checkpoint(self.body, self.priv)
        _other_priv, other_pub = attestation.generate_keypair()
        self.assertEqual(attestation.verify_checkpoint(signed, other_pub), "UNKNOWN_KEY")

    def test_missing_signature_is_malformed(self):
        self.assertEqual(attestation.verify_checkpoint(self.body), "MALFORMED")

    def test_canonical_bytes_excludes_sig_and_is_stable(self):
        signed = attestation.sign_checkpoint(self.body, self.priv)
        a = attestation.canonical_bytes(signed)
        b = attestation.canonical_bytes(self.body)
        self.assertEqual(a, b)  # signature/public_key excluded
        self.assertNotIn(b"signature", a)


if __name__ == "__main__":
    unittest.main()
