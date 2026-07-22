import json
import tempfile
import unittest
from pathlib import Path

from warrantos.provenance import attestation, warrant_bundle
from warrantos.provenance.trust import TrustRoot, load_trust_root, verify_release_warrant


class TrustRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.seed, cls.public = attestation.generate_keypair()
            cls.other_seed, cls.other_public = attestation.generate_keypair()
        except attestation.AttestationUnavailable:
            raise unittest.SkipTest("cryptography not installed")

    def bundle(self, seed=None):
        cbom = {"schema": "warrantos-cbom/v1", "claims": []}
        bundle = warrant_bundle.create_warrant(
            prose="release", cbom=cbom, ledger_entries=[{"event": "checked"}],
            run_id="run_1", timestamp="2026-07-20T00:00:00Z",
            private_seed_b64=seed or self.seed,
        )
        return bundle, cbom

    def test_pinned_signer_is_valid(self):
        bundle, cbom = self.bundle()
        result = verify_release_warrant(
            bundle, prose="release", cbom=cbom,
            trust_root=TrustRoot("prod-2026", self.public),
        )
        self.assertEqual(result["overall"], "VALID")
        self.assertEqual(result["trust"], "PINNED")

    def test_attacker_self_signed_bundle_is_rejected(self):
        bundle, cbom = self.bundle(self.other_seed)
        result = verify_release_warrant(
            bundle, prose="release", cbom=cbom,
            trust_root=TrustRoot("prod-2026", self.public),
        )
        self.assertEqual(result["overall"], "INVALID")
        self.assertEqual(result["signature"], "UNKNOWN_KEY")

    def test_embedded_cbom_substitution_is_rejected_even_with_original_external_cbom(self):
        bundle, cbom = self.bundle()
        bundle["cbom"] = {"schema": "warrantos-cbom/v1", "claims": [{"fabricated": True}]}
        result = verify_release_warrant(
            bundle, prose="release", cbom=cbom,
            trust_root=TrustRoot("prod-2026", self.public),
        )
        self.assertEqual(result["binding"], "INVALID")
        self.assertEqual(result["cbom"], "INVALID")
        self.assertEqual(result["overall"], "INVALID")

    def test_trust_root_fingerprint_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust.json"
            path.write_text(json.dumps({
                "schema": "warrantos-trust-root/v1", "key_id": "prod",
                "algorithm": "ed25519", "public_key": self.public,
                "fingerprint": "sha256:" + "0" * 64,
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_trust_root(path)

    def test_malformed_key_is_rejected(self):
        with self.assertRaises(ValueError):
            TrustRoot("prod", "not-a-key")


if __name__ == "__main__":
    unittest.main()
