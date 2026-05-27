#!/usr/bin/env python3
"""Tests for context admissibility and prose-boundary controls.

The context layer extends claim provenance to fuzzy process material:
feedback, prior drafts, operator notes, tool traces, and style signals. It
must let the insight travel while blocking process narration in final prose.
"""

import json
import unittest

from provenance.context_admissibility import (
    ContextItem,
    admissibility_summary,
    classify_context,
    compile_cbom,
    derive_requirement,
    scan_prose_boundary,
)


class TestContextClassification(unittest.TestCase):

    def test_feedback_can_influence_but_cannot_appear_in_final_prose(self):
        item = classify_context(
            "feedback_017",
            "This is not commercial enough and mentions the previous version.",
        )

        self.assertEqual(item.context_type, "user_feedback")
        self.assertEqual(item.ledger_bucket, "synthesised")
        self.assertTrue(item.can_influence_output)
        self.assertFalse(item.can_appear_in_final_prose)
        self.assertEqual(item.allowed_transformation, "derived_requirement")

    def test_source_document_can_appear_when_cited(self):
        item = classify_context(
            "source_001",
            "Source: Queensland Health strategy, 2026, page 4.",
        )

        self.assertEqual(item.context_type, "empirical_evidence")
        self.assertEqual(item.ledger_bucket, "empirical")
        self.assertTrue(item.can_influence_output)
        self.assertTrue(item.can_appear_in_final_prose)
        self.assertEqual(item.allowed_transformation, "claim_or_citation")

    def test_private_reasoning_is_excluded(self):
        item = classify_context(
            "reasoning_001",
            "My private reasoning chain is that the user really means X.",
        )

        self.assertEqual(item.context_type, "private_reasoning")
        self.assertEqual(item.ledger_bucket, "excluded")
        self.assertFalse(item.can_influence_output)
        self.assertFalse(item.can_appear_in_final_prose)


class TestRequirementDerivation(unittest.TestCase):

    def test_feedback_is_transformed_into_requirement_not_process_narration(self):
        item = classify_context(
            "feedback_017",
            "This is not commercial enough and it keeps mentioning the previous version.",
        )

        req = derive_requirement(item)

        self.assertEqual(req.context_id, "feedback_017")
        self.assertEqual(req.kind, "derived_requirement")
        self.assertIn("Strengthen commercial positioning", req.text)
        self.assertIn("standalone", req.text)
        self.assertNotIn("feedback", req.text.lower())
        self.assertNotIn("previous version", req.text.lower())

    def test_source_document_derives_claim_source_requirement(self):
        item = classify_context(
            "source_001",
            "Source document: AIHW public health expenditure data.",
        )

        req = derive_requirement(item)

        self.assertEqual(req.kind, "claim_or_citation")
        self.assertIn("Use as source-supported material", req.text)


class TestProseBoundary(unittest.TestCase):

    def test_process_to_prose_leakage_is_blocked(self):
        result = scan_prose_boundary(
            "Based on your feedback, this version is now more commercial."
        )

        self.assertEqual(result.verdict, "blocked")
        self.assertEqual(len(result.violations), 3)
        self.assertIn("based on your feedback", result.violations[0].matched_text.lower())

    def test_applied_insight_passes(self):
        result = scan_prose_boundary(
            "The product targets professional AI users who need final-ready "
            "artefacts from messy drafting workflows."
        )

        self.assertEqual(result.verdict, "pass")
        self.assertEqual(result.violations, [])

    def test_audit_context_can_be_allowed_explicitly(self):
        result = scan_prose_boundary(
            "The audit records feedback from the workshop.",
            artefact_role="audit",
        )

        self.assertEqual(result.verdict, "pass")


class TestCbom(unittest.TestCase):

    def test_cbom_records_admitted_transformed_blocked_and_boundary_status(self):
        items = [
            classify_context("feedback_017", "This is not commercial enough."),
            classify_context("source_001", "Source: official strategy, 2026."),
            classify_context("trace_001", "Tool trace: fetched three URLs."),
        ]
        final_text = "The product targets professional AI users."

        cbom = compile_cbom(items, final_text)

        self.assertEqual(cbom["schema"], "context-bill-of-materials/v1")
        self.assertEqual(cbom["summary"]["total_context_items"], 3)
        self.assertEqual(cbom["summary"]["can_influence_output"], 2)
        self.assertEqual(cbom["summary"]["can_appear_in_final_prose"], 1)
        self.assertEqual(cbom["prose_boundary"]["verdict"], "pass")
        json.dumps(cbom)

    def test_admissibility_summary_is_stable(self):
        """Stable v0.2 shape: the seven v0.1 keys plus the three v0.2
        actor-visibility keys (can_be_seen_by, cannot_be_seen_by,
        prohibited_use). Per INV-007 the v0.2 additions are additive;
        the v0.1 keys still appear with the same semantics."""
        item = ContextItem(
            context_id="style_001",
            raw_text="Use Australian English.",
            context_type="style_signal",
            ledger_bucket="synthesised",
            can_influence_output=True,
            can_appear_in_final_prose=False,
            allowed_transformation="style_rule",
            audit_status="recorded",
        )

        self.assertEqual(
            admissibility_summary(item),
            {
                "context_id": "style_001",
                "context_type": "style_signal",
                "ledger_bucket": "synthesised",
                "can_influence_output": True,
                "can_appear_in_final_prose": False,
                "allowed_transformation": "style_rule",
                "audit_status": "recorded",
                "can_be_seen_by": [],
                "cannot_be_seen_by": [],
                "prohibited_use": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
