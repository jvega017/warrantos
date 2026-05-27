#!/usr/bin/env python3
"""Tests for provenance.gates (Layer 7 G3/G4/G5).

G3 self-grounding is BUILT; G4 contamination and G5 calibration are
NOT BUILT in v0.5 and their stubs raise NotImplementedError. The
deferred state is explicit and tested so a future caller can detect
the gap.
"""

import unittest

from provenance.gates import (
    SelfGroundingResult,
    check_calibration,
    check_contamination,
    check_self_grounding,
    declare_family,
)


class TestDeclareFamily(unittest.TestCase):
    """SPEC-L7-N004 family registry: each documented family resolves."""

    def test_anthropic_claude_family(self):
        for ident in ("claude-opus-4-7", "claude-3.5-sonnet", "Claude-Haiku-4-5"):
            with self.subTest(ident=ident):
                self.assertEqual(declare_family(ident), "anthropic-claude")

    def test_openai_gpt_family(self):
        for ident in ("gpt-5.4", "gpt-4o", "GPT-3.5-turbo"):
            with self.subTest(ident=ident):
                self.assertEqual(declare_family(ident), "openai-gpt")

    def test_google_gemini_family(self):
        for ident in ("gemini-2.5-pro", "gemini-flash-lite"):
            with self.subTest(ident=ident):
                self.assertEqual(declare_family(ident), "google-gemini")

    def test_meta_llama_family(self):
        for ident in ("llama-3.2-90b", "Llama-3-70b"):
            with self.subTest(ident=ident):
                self.assertEqual(declare_family(ident), "meta-llama")

    def test_xai_grok_family(self):
        self.assertEqual(declare_family("grok-fast-1"), "xai-grok")

    def test_unknown_family(self):
        self.assertEqual(declare_family(""), "unknown")
        self.assertEqual(declare_family("some-internal-prototype"), "unknown")


class TestCheckSelfGrounding(unittest.TestCase):
    """SPEC-L7-S003/N003/N004 + INV-006."""

    def test_same_model_identifier_flags_requires_external_grounding(self):
        """INV-006: writer == verifier identifier triggers the gate."""
        result = check_self_grounding(
            writer_model="claude-opus-4-7",
            verifier_model="claude-opus-4-7",
        )
        self.assertIsInstance(result, SelfGroundingResult)
        self.assertEqual(result.verdict, "requires_external_grounding")
        self.assertEqual(result.cross_model, "self")
        self.assertIn("INV-006", result.reason)

    def test_same_model_case_insensitive(self):
        result = check_self_grounding(
            writer_model="Claude-Opus-4-7",
            verifier_model="claude-opus-4-7",
        )
        self.assertEqual(result.verdict, "requires_external_grounding")

    def test_same_family_different_version_flags_family_match(self):
        """SPEC-L7-N004: same family, different version is permitted
        but flagged."""
        result = check_self_grounding(
            writer_model="claude-opus-4-7",
            verifier_model="claude-haiku-4-5",
        )
        self.assertEqual(result.verdict, "family_match")
        self.assertEqual(result.cross_model, "family_match")
        self.assertEqual(result.writer_family, "anthropic-claude")
        self.assertEqual(result.verifier_family, "anthropic-claude")

    def test_different_families_pass(self):
        result = check_self_grounding(
            writer_model="claude-opus-4-7",
            verifier_model="gpt-5.4",
        )
        self.assertEqual(result.verdict, "ok")
        self.assertEqual(result.cross_model, "family_distinct")

    def test_no_verifier_returns_ok_with_no_verifier_flag(self):
        """When no verifier ran, G3 is not triggered. The result
        records the absence in cross_model so the CBOM still has a
        positive signal."""
        for missing in (None, "", "  "):
            with self.subTest(verifier=repr(missing)):
                result = check_self_grounding(
                    writer_model="claude-opus-4-7",
                    verifier_model=missing,
                )
                self.assertEqual(result.verdict, "ok")
                self.assertEqual(result.cross_model, "no_verifier")

    def test_result_to_dict_carries_all_fields(self):
        result = check_self_grounding(
            writer_model="claude-opus-4-7",
            verifier_model="gpt-5.4",
        )
        d = result.to_dict()
        for key in (
            "verdict",
            "writer_model",
            "verifier_model",
            "writer_family",
            "verifier_family",
            "cross_model",
            "reason",
        ):
            self.assertIn(key, d)


class TestDeferredGates(unittest.TestCase):
    """G4 and G5 are NOT BUILT in v0.5; the stubs raise to make the
    deferral explicit and detectable."""

    def test_g4_contamination_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError) as ctx:
            check_contamination()
        self.assertIn("G4", str(ctx.exception))
        self.assertIn("NOT BUILT", str(ctx.exception))

    def test_g5_calibration_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError) as ctx:
            check_calibration()
        self.assertIn("G5", str(ctx.exception))
        self.assertIn("NOT BUILT", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
