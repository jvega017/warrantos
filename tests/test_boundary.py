#!/usr/bin/env python3
"""Tests for the reusable prose-boundary gate."""

import unittest

from provenance.boundary import check_boundary


class TestBoundaryProfiles(unittest.TestCase):

    def test_final_prose_blocks_original_process_leakage_examples(self):
        text = "\n".join([
            "Based on your feedback, this version is more commercial.",
            "Build policy-r6-1716-2026-05-23.",
            "[archive only] LinkedIn: draft hook.",
        ])

        result = check_boundary(text, profile="final-prose")

        self.assertEqual(result.verdict, "blocked")
        self.assertGreaterEqual(len(result.violations), 4)
        self.assertEqual(result.violations[0].line_number, 1)
        self.assertTrue(any(v.rule_id == "archive_only" for v in result.violations))
        self.assertTrue(any(v.rule_id == "build_label" for v in result.violations))

    def test_final_prose_catches_ai_assistant_residue(self):
        # The core value proposition: AI scaffold and conversational residue that
        # bleeds from the chat into the final artefact must be caught.
        text = "\n".join([
            "Certainly! Here's the revised version.",
            "As an AI language model, I cannot verify every figure.",
            "I have updated the analysis as requested, based on the information provided.",
            "[TODO: add the costing table here]",
            "I hope this helps. Let me know if you would like me to expand. "
            "Is there anything else you would like me to change?",
        ])
        result = check_boundary(text, profile="final-prose")
        self.assertEqual(result.verdict, "blocked")
        caught = {v.rule_id for v in result.violations}
        for expected in (
            "assistant_opener", "ai_self_reference", "ai_capability_disclaimer",
            "scaffold_placeholder", "assistant_closer", "delivery_framing",
            "hedge_provenance", "request_acknowledgement",
        ):
            self.assertIn(expected, caught, "missed AI residue rule: %s" % expected)

    def test_clean_final_prose_has_no_ai_residue_false_positives(self):
        # A genuine policy paragraph must not trip the residue rules.
        text = (
            "The agency should adopt the framework. Section 23 of the Privacy Act "
            "1988 requires a documented basis for each disclosure. The cost is "
            "estimated at $4.2 million over three years."
        )
        result = check_boundary(text, profile="final-prose")
        self.assertEqual(result.verdict, "pass")

    def test_audit_profile_allows_process_language(self):
        result = check_boundary(
            "Based on your feedback, this version records the review history.",
            profile="audit",
        )

        self.assertEqual(result.verdict, "pass")
        self.assertEqual(result.violations, [])

    def test_paper_full_blocks_process_narration_but_not_word_build_in_normal_use(self):
        result = check_boundary(
            "This version incorporates review feedback. Institutions build capability over time.",
            profile="paper-full",
        )

        self.assertEqual(result.verdict, "blocked")
        self.assertTrue(any(v.rule_id == "version_narration" for v in result.violations))
        self.assertFalse(any(v.rule_id == "build_label" for v in result.violations))


if __name__ == "__main__":
    unittest.main()

