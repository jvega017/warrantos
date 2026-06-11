#!/usr/bin/env python3
"""Tests for provenance.classification (Foundation F-classification).

The default 4-tier registry mirrors the reference adopter's data gate:
Public, Official, Sensitive/Protected, Credentials. The keyword
heuristics are a documented starter set; these tests assert the gate
fires on the canonical markers and fails closed on blocking tiers.
"""

import unittest

from warrantos.provenance.classification import (
    DEFAULT_TIERS,
    ClassificationResult,
    SensitivityBlock,
    SensitivityTier,
    TIER_CREDENTIALS,
    TIER_OFFICIAL,
    TIER_PUBLIC,
    TIER_SENSITIVE,
    classify_sensitivity,
    gate_sensitivity,
)


class TestRegistry(unittest.TestCase):
    """The default registry is the four-tier data gate."""

    def test_four_tiers_present_and_ordered(self):
        self.assertEqual(len(DEFAULT_TIERS), 4)
        ranks = [t.rank for t in DEFAULT_TIERS]
        self.assertEqual(ranks, sorted(ranks))
        ids = [t.tier_id for t in DEFAULT_TIERS]
        self.assertEqual(ids, ["public", "official", "sensitive", "credentials"])

    def test_blocking_tiers_are_sensitive_and_credentials(self):
        self.assertFalse(TIER_PUBLIC.blocks_processing)
        self.assertFalse(TIER_OFFICIAL.blocks_processing)
        self.assertTrue(TIER_SENSITIVE.blocks_processing)
        self.assertTrue(TIER_CREDENTIALS.blocks_processing)

    def test_tier_to_dict_round_trips(self):
        d = TIER_SENSITIVE.to_dict()
        for key in ("tier_id", "name", "rank", "action", "blocks_processing", "examples"):
            self.assertIn(key, d)

    def test_tier_is_a_dataclass_instance(self):
        self.assertIsInstance(TIER_PUBLIC, SensitivityTier)


class TestClassifySensitivity(unittest.TestCase):
    """Keyword heuristics for the QPS-style gate."""

    def test_empty_text_defaults_to_official_floor(self):
        result = classify_sensitivity("")
        self.assertIsInstance(result, ClassificationResult)
        self.assertEqual(result.tier.tier_id, "official")
        self.assertEqual(result.matches, [])

    def test_unmatched_text_defaults_to_official_not_public(self):
        """Honesty rule: unmatched text is Official, never silently Public."""
        result = classify_sensitivity(
            "This is a routine working note about open data templates."
        )
        self.assertEqual(result.tier.tier_id, "official")
        self.assertFalse(result.blocks_processing)

    def test_cabinet_marker_is_sensitive(self):
        result = classify_sensitivity("This is a Cabinet-in-confidence submission.")
        self.assertEqual(result.tier.tier_id, "sensitive")
        self.assertTrue(result.blocks_processing)
        self.assertTrue(any(m.rule_id == "cabinet" for m in result.matches))

    def test_ministerial_marker_is_sensitive(self):
        result = classify_sensitivity("The ministerial decision is recorded here.")
        self.assertEqual(result.tier.tier_id, "sensitive")

    def test_legal_advice_marker_is_sensitive(self):
        result = classify_sensitivity("Per the legal advice received last week.")
        self.assertEqual(result.tier.tier_id, "sensitive")
        self.assertTrue(any(m.rule_id == "legal_advice" for m in result.matches))

    def test_crown_solicitor_marker_is_sensitive(self):
        result = classify_sensitivity("Advice from the Crown Solicitor follows.")
        self.assertEqual(result.tier.tier_id, "sensitive")

    def test_hr_pip_termination_markers_are_sensitive(self):
        for text in (
            "The employee was placed on a PIP.",
            "A performance improvement plan was issued.",
            "This relates to the termination of the contractor.",
        ):
            with self.subTest(text=text):
                result = classify_sensitivity(text)
                self.assertEqual(result.tier.tier_id, "sensitive")

    def test_budget_million_billion_markers_are_sensitive(self):
        for text in (
            "The package allocates $250M next year.",
            "An unpublished figure of $1.2B is involved.",
            "Spending of $40 million is proposed.",
        ):
            with self.subTest(text=text):
                result = classify_sensitivity(text)
                self.assertEqual(result.tier.tier_id, "sensitive")
                self.assertTrue(any(m.rule_id == "budget_figure" for m in result.matches))

    def test_credential_assignment_is_credentials_tier(self):
        result = classify_sensitivity("api_key: sk-abc123")
        self.assertEqual(result.tier.tier_id, "credentials")
        self.assertTrue(result.blocks_processing)

    def test_openai_key_pattern_is_credentials(self):
        result = classify_sensitivity(
            "Use sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890 to authenticate."
        )
        self.assertEqual(result.tier.tier_id, "credentials")

    def test_private_key_block_is_credentials(self):
        result = classify_sensitivity("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        self.assertEqual(result.tier.tier_id, "credentials")

    def test_credentials_outrank_sensitive(self):
        """When both fire, the highest-rank tier wins."""
        result = classify_sensitivity(
            "Cabinet note. api_key: sk-secret-token-here"
        )
        self.assertEqual(result.tier.tier_id, "credentials")

    def test_result_to_dict_carries_starter_note(self):
        result = classify_sensitivity("Cabinet material.")
        d = result.to_dict()
        self.assertEqual(d["corpus_completeness"], "starter")
        self.assertTrue(d["blocks_processing"])
        self.assertIn("starter", d["note"].lower())
        self.assertIn("Official", d["note"])


class TestGateSensitivity(unittest.TestCase):
    """The fail-closed gate raises SensitivityBlock on blocking tiers."""

    def test_public_or_official_passes(self):
        result = gate_sensitivity("A routine open-data note about templates.")
        self.assertFalse(result.blocks_processing)
        self.assertEqual(result.tier.tier_id, "official")

    def test_sensitive_material_raises(self):
        with self.assertRaises(SensitivityBlock) as ctx:
            gate_sensitivity("This Cabinet submission is confidential.")
        self.assertEqual(ctx.exception.result.tier.tier_id, "sensitive")
        self.assertIn("BLOCKED", str(ctx.exception))

    def test_credentials_raise(self):
        with self.assertRaises(SensitivityBlock):
            gate_sensitivity("password: hunter2hunter2")

    def test_block_message_names_triggering_rules(self):
        with self.assertRaises(SensitivityBlock) as ctx:
            gate_sensitivity("Cabinet allocation of $250M.")
        msg = str(ctx.exception)
        self.assertIn("cabinet", msg)
        self.assertIn("budget_figure", msg)

    def test_custom_floor_is_respected(self):
        """A caller can pass Public as the floor for an already-public corpus."""
        result = gate_sensitivity(
            "A plain factual sentence.", floor=TIER_PUBLIC,
        )
        self.assertEqual(result.tier.tier_id, "public")


if __name__ == "__main__":
    unittest.main(verbosity=2)
