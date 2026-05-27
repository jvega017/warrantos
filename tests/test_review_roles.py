#!/usr/bin/env python3
"""Tests for review-role registry and the SPEC-L1-S005 override path.

Closes the A1 classification-laundering attack identified by the Wave A
policy-red-team review on 2026-05-26: a review-role agent's output cannot
be silently reclassified to ``private_reasoning`` (or any other class)
merely because its text contains a keyword the rule-based classifier
matches earlier in its decision tree.

The authoritative signal for review-role detection is the caller-supplied
``source_agent`` argument. Text-pattern heuristics are a best-effort
secondary signal that requires at least two independent signals to fire
to reduce false positives from policy or paper content that may quote
review terminology.
"""

import tempfile
import unittest
from pathlib import Path

from provenance.cbom import (
    CBOM,
    ClassificationOverrideRecord,
    ContextInput,
    build_cbom,
)
from provenance.context_admissibility import (
    classify_context,
    classify_with_override,
)
from provenance.overrides import record_override
from provenance.review_roles import (
    REVIEW_ROLE_REGISTRY,
    is_review_role_output,
)


class TestReviewRoleRegistry(unittest.TestCase):
    """Detection of review-role outputs by source_agent and by text."""

    def test_source_agent_in_registry_returns_true(self):
        """Authoritative signal: any agent in the registry is recognised."""
        for agent in REVIEW_ROLE_REGISTRY:
            with self.subTest(agent=agent):
                self.assertTrue(is_review_role_output("any text", source_agent=agent))

    def test_source_agent_normalisation(self):
        """Casing and hyphen variants resolve to the same registry entry."""
        for variant in ("Policy-Red-Team", "POLICY_RED_TEAM", "policy red team"):
            with self.subTest(variant=variant):
                self.assertTrue(is_review_role_output("any text", source_agent=variant))

    def test_unknown_source_agent_returns_false_without_text_signals(self):
        """An agent name outside the registry, with neutral text, is False."""
        self.assertFalse(
            is_review_role_output(
                "An ordinary brief paragraph about open data policy.",
                source_agent="brief-author",
            )
        )

    def test_text_heuristic_requires_two_signals(self):
        """A single mention is not enough; two independent signals are."""
        # One signal alone (a finding-id token).
        self.assertFalse(is_review_role_output("Finding A1 was discussed."))
        # Two signals: severity line and reviewer header.
        review_output = (
            "## Findings\n"
            "- Severity: P0\n"
            "- A1 Layer 1 classification laundering\n"
        )
        self.assertTrue(is_review_role_output(review_output))


class TestClassifyContextWithSourceAgent(unittest.TestCase):
    """SPEC-L1-S005: source_agent-driven classification gates review-role
    output to review_finding ahead of the text-pattern decision tree."""

    def test_policy_red_team_output_defaults_to_review_finding(self):
        """A policy-red-team output classifies as review_finding regardless of
        the text content, even when text would otherwise match a different
        rule (e.g. private reasoning, source citation)."""
        item = classify_context(
            "ctx_policy_001",
            "The attacker thesis depends on private reasoning escaping the gate.",
            source_agent="policy-red-team",
        )
        self.assertEqual(item.context_type, "review_finding")
        self.assertEqual(item.ledger_bucket, "synthesised")
        self.assertEqual(item.allowed_transformation, "applied_recommendation")
        # Critically: NOT routed to private_reasoning despite the keyword.
        self.assertNotEqual(item.context_type, "private_reasoning")

    def test_a1_attack_text_with_source_agent_is_not_silenced(self):
        """The A1 attack: a review_finding whose text contains
        'chain of thought' would, under v0.1, classify as private_reasoning
        and disappear. With source_agent set, it stays review_finding."""
        a1_text = (
            "The chain of thought attack works because the classifier sees "
            "this keyword and routes the entire finding to private_reasoning, "
            "removing it from the writer pack and the boundary gate."
        )
        item = classify_context(
            "ctx_a1_demo",
            a1_text,
            source_agent="fresh-critic",
        )
        self.assertEqual(item.context_type, "review_finding")
        self.assertNotEqual(item.context_type, "private_reasoning")
        self.assertEqual(item.audit_status, "recorded")
        self.assertNotEqual(item.audit_status, "excluded")

    def test_no_source_agent_preserves_v01_behaviour(self):
        """Backwards compatibility: without source_agent, the v0.1
        decision tree is unchanged. Chain-of-thought text classifies as
        private_reasoning because that branch fires before the review
        text pattern. This is the A1 attack at the rule level, the very
        bug source_agent closes when supplied."""
        item = classify_context(
            "ctx_legacy",
            "The chain of thought escapes the gate.",
        )
        # v0.1 behaviour: text-only detection routes to private_reasoning.
        self.assertEqual(item.context_type, "private_reasoning")


class TestClassifyWithOverride(unittest.TestCase):
    """SPEC-L1-S005: reclassification to private_reasoning requires a
    recorded override id. The function returns both the new ContextItem
    and a ClassificationOverrideRecord for CBOM inclusion."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "overrides.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_override_id_raises(self):
        """SPEC-L1-S005: override_id SHALL be non-empty."""
        for bad in ("", "  ", "\t"):
            with self.subTest(override_id=repr(bad)):
                with self.assertRaises(ValueError) as ctx:
                    classify_with_override(
                        "ctx_x",
                        "Severity: P0\n# Findings\nA1 attack.",
                        source_agent="policy-red-team",
                        override_id=bad,
                        target_class="private_reasoning",
                    )
                self.assertIn("SPEC-L1-S005", str(ctx.exception))

    def test_non_review_input_rejected(self):
        """The override path is only for review-role-shaped input."""
        with self.assertRaises(ValueError) as ctx:
            classify_with_override(
                "ctx_plain",
                "An ordinary policy paragraph about open data.",
                source_agent="brief-author",
                override_id="ovr_1",
                target_class="private_reasoning",
            )
        self.assertIn("review-role", str(ctx.exception))

    def test_valid_override_returns_item_and_override_record(self):
        """Round-trip: override_id is supplied, source_agent is in the
        registry, target_class is private_reasoning. Returns the
        reclassified ContextItem and the ClassificationOverrideRecord."""
        # First record a human_override row (the SPEC-L8-S004 ledger).
        override = record_override(
            self.db_path,
            run_id="run_demo",
            reviewer="human:director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Finding is speculative, not load-bearing for any claim.",
            compensating_control="Reviewer cross-checked the finding against the source-data audit.",
        )

        item, record = classify_with_override(
            "ctx_review_001",
            "Severity: P0\n# Findings\nA1 laundering attack vector.",
            source_agent="policy-red-team",
            override_id=str(override.id),
            target_class="private_reasoning",
            override_rationale_summary="Finding deferred to v0.3 pending second-coder review.",
        )

        # Item: reclassified to private_reasoning.
        self.assertEqual(item.context_type, "private_reasoning")
        self.assertEqual(item.audit_status, "excluded")
        self.assertFalse(item.can_influence_output)
        self.assertFalse(item.can_appear_in_final_prose)

        # Record: carries the override id and the default class.
        self.assertIsInstance(record, ClassificationOverrideRecord)
        self.assertEqual(record.context_id, "ctx_review_001")
        self.assertEqual(record.classified_as, "private_reasoning")
        self.assertEqual(record.default_would_be, "review_finding")
        self.assertEqual(record.override_id, str(override.id))
        self.assertIn("Finding deferred", record.override_rationale_summary)

    def test_override_record_threads_into_cbom_classification_overrides(self):
        """End-to-end: the ClassificationOverrideRecord from
        classify_with_override is accepted by build_cbom() and appears in
        the CBOM's classification_overrides field. This is the SPEC-L1-S005
        contract: the override is visible to any auditor reading the CBOM."""
        override = record_override(
            self.db_path,
            run_id="run_cbom_demo",
            reviewer="human:director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Test rationale.",
            compensating_control="Test compensating control.",
        )

        item, record = classify_with_override(
            "ctx_in_cbom",
            "Severity: P1\n# Findings\nA2 conflicted auditor.",
            source_agent="policy-red-team",
            override_id=str(override.id),
            target_class="private_reasoning",
            override_rationale_summary="Test summary.",
        )

        # Build a CBOM that includes the context input (to satisfy the
        # known-context_id check in _validate_classification_overrides)
        # and the override record.
        cbom = build_cbom(
            context_inputs=[
                ContextInput(
                    context_id="ctx_in_cbom",
                    text=item.raw_text,
                    material_type="review_finding",
                )
            ],
            classification_overrides=[record],
            override_ledger_refs=[str(override.id)],
            actor_identity={
                "context_classifier": "agent:auto",
                "auditor": "human:director.so",
            },
        )
        data = cbom.to_dict()

        self.assertEqual(data["summary"]["classification_overrides"], 1)
        ledger_row = data["classification_overrides"][0]
        self.assertEqual(ledger_row["context_id"], "ctx_in_cbom")
        self.assertEqual(ledger_row["classified_as"], "private_reasoning")
        self.assertEqual(ledger_row["default_would_be"], "review_finding")
        self.assertEqual(ledger_row["override_id"], str(override.id))
        self.assertEqual(data["override_ledger_refs"], [str(override.id)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
