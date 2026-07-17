"""Tests for the Ed25519 attestation layer (provenance.attestation).

These exercise the real signing path, which requires the optional [attestation]
extra. If cryptography is absent the whole module is skipped, matching the
optional-dependency design.
"""

import unittest

from warrantos.provenance import attestation

try:
    attestation.generate_keypair()
    _HAVE = True
except (attestation.AttestationUnavailable, BaseException):
    # Catch AttestationUnavailable and any pyo3/cryptography import errors
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


class TestCanonicalBytes(unittest.TestCase):
    """canonical_bytes is the byte-exact contract the JS web verifier must match.
    These are known-answer vectors: if any of these change, the web verifier and
    every previously-signed checkpoint break, so they are pinned deliberately."""

    def kat(self, obj, expected):
        self.assertEqual(attestation.canonical_bytes(obj), expected)

    def test_key_ordering_is_sorted(self):
        self.kat({"b": 1, "a": 2}, b'{"a":2,"b":1}')

    def test_no_whitespace(self):
        self.kat({"x": [1, 2, 3]}, b'{"x":[1,2,3]}')

    def test_nested(self):
        self.kat({"o": {"z": 1, "a": 2}, "l": [{"k": "v"}]}, b'{"l":[{"k":"v"}],"o":{"a":2,"z":1}}')

    def test_empty_string_and_null_and_bools(self):
        self.kat({"e": "", "n": None, "t": True, "f": False}, b'{"e":"","f":false,"n":null,"t":true}')

    def test_non_ascii_is_escaped(self):
        # ensure_ascii: e-acute escapes to é (matching Python json.dumps default).
        self.kat({"s": "é"}, b'{"s":"\\u00e9"}')

    def test_astral_uses_surrogate_pair(self):
        # U+1F600 escapes to a surrogate pair, which the JS verifier must reproduce.
        self.kat({"s": "\U0001f600"}, b'{"s":"\\ud83d\\ude00"}')

    def test_integer_formatting(self):
        self.kat({"n": 1000000}, b'{"n":1000000}')

    def test_nan_and_infinity_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                attestation.canonical_bytes({"x": bad})

    def test_signature_and_public_key_excluded(self):
        self.kat({"a": 1, "signature": "x", "public_key": "y"}, b'{"a":1}')


if __name__ == "__main__":
    unittest.main()
