"""Tests for the .warrant verifiable artefact (provenance.warrant_bundle)."""

import unittest

from provenance import attestation, warrant_bundle

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


class TestWarrantBundle(unittest.TestCase):
    def test_unsigned_bundle_integrity_verifies(self):
        # Force the unsigned path: no key passed and no env key.
        b = warrant_bundle.create_warrant(
            prose=_PROSE, cbom=_CBOM, ledger_entries=_LEDGER,
            run_id="run_b", timestamp="2026-06-09T00:00:00Z",
        )
        r = warrant_bundle.verify_warrant(b, prose=_PROSE)
        self.assertEqual(r["integrity"], "VALID")
        self.assertEqual(r["prose"], "VALID")
        self.assertIn(r["signature"], ("UNSIGNED", "VALID"))  # env key may exist
        self.assertEqual(r["overall"], "VALID")

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


if __name__ == "__main__":
    unittest.main()
