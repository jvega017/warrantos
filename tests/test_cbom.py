#!/usr/bin/env python3
"""Tests for provenance.cbom."""

import json
import unittest

from provenance.cbom import (
    CBOM,
    ClaimRecord,
    ClassificationOverrideRecord,
    ContextInput,
    ReviewFindingRecord,
    TransformationRecord,
    build_cbom,
)


class TestCbomBuild(unittest.TestCase):

    def test_cbom_represents_inputs_transformations_material_claims_and_findings(self):
        cbom = build_cbom(
            context_inputs=[
                ContextInput(
                    context_id="ctx_source",
                    text="Official report page 4.",
                    source="report.pdf",
                    material_type="source",
                ),
                ContextInput(
                    context_id="ctx_sensitive",
                    text="Private drafting notes.",
                    source="session",
                    material_type="process",
                    admitted=False,
                    reason="process material cannot appear in final prose",
                ),
            ],
            transformations=[
                TransformationRecord(
                    transform_id="tx_001",
                    input_ids=["ctx_source"],
                    output_id="claim_001",
                    kind="extract_claim",
                    description="Converted source paragraph into a factual claim.",
                )
            ],
            claims=[
                ClaimRecord(
                    claim_id="claim_001",
                    text="The programme reduced costs by 12 per cent.",
                    support_ids=["ctx_source"],
                    status="supported",
                )
            ],
            review_findings=[
                ReviewFindingRecord(
                    finding_id="f_001",
                    severity="P1",
                    title="Unsupported comparator",
                    disposition="distinct",
                )
            ],
            artefact_id="draft_7",
        )

        data = cbom.to_dict()

        self.assertEqual(data["schema"], "warrantos-cbom/v1")
        self.assertEqual(data["artefact_id"], "draft_7")
        self.assertEqual(data["summary"]["context_inputs"], 2)
        self.assertEqual(data["summary"]["admitted_material"], 1)
        self.assertEqual(data["summary"]["blocked_material"], 1)
        self.assertEqual(data["summary"]["claims"], 1)
        self.assertEqual(data["summary"]["review_findings"], 1)
        self.assertEqual(data["blocked_material"][0]["context_id"], "ctx_sensitive")
        self.assertEqual(data["admitted_material"][0]["context_id"], "ctx_source")
        json.dumps(data)

    def test_empty_cbom_has_stable_shape(self):
        cbom = build_cbom()
        data = cbom.to_dict()

        self.assertIsInstance(cbom, CBOM)
        self.assertEqual(data["summary"]["context_inputs"], 0)
        self.assertEqual(data["context_inputs"], [])
        self.assertEqual(data["transformations"], [])
        self.assertEqual(data["claims"], [])
        self.assertEqual(data["review_findings"], [])


class TestCbomValidation(unittest.TestCase):

    def test_transformation_input_ids_must_reference_context_inputs(self):
        with self.assertRaises(ValueError):
            build_cbom(
                context_inputs=[ContextInput("ctx_001", "Source text.")],
                transformations=[
                    TransformationRecord(
                        transform_id="tx_bad",
                        input_ids=["missing"],
                        output_id="claim_001",
                        kind="extract_claim",
                        description="Bad reference.",
                    )
                ],
            )

    def test_claim_support_ids_must_reference_admitted_inputs(self):
        with self.assertRaises(ValueError):
            build_cbom(
                context_inputs=[
                    ContextInput(
                        context_id="ctx_blocked",
                        text="Private notes.",
                        admitted=False,
                    )
                ],
                claims=[
                    ClaimRecord(
                        claim_id="claim_001",
                        text="A derived claim.",
                        support_ids=["ctx_blocked"],
                    )
                ],
            )


class TestCbomSpecV02Fields(unittest.TestCase):
    """Tests for SPEC-v0.2 schema additions: actor_identity,
    classification_overrides, override_ledger_refs.

    Additive per INV-007: existing callers must continue to work unchanged
    with the new fields defaulting to empty.
    """

    def test_empty_actor_identity_backwards_compatible(self):
        cbom = build_cbom()
        data = cbom.to_dict()

        self.assertEqual(data["actor_identity"], {})
        self.assertEqual(data["classification_overrides"], [])
        self.assertEqual(data["override_ledger_refs"], [])
        self.assertEqual(data["summary"]["classification_overrides"], 0)
        self.assertEqual(data["summary"]["override_ledger_refs"], 0)
        json.dumps(data)

    def test_full_six_role_actor_identity_roundtrips(self):
        actor_map = {
            "context_classifier": "agent:fresh-critic",
            "insight_compiler": "human:juan.vega",
            "source_curator": "human:juan.vega",
            "clean_room_writer": "model:claude-opus-4-7",
            "reviewer_qa": "agent:policy-red-team",
            "auditor": "human:director.so",
        }
        cbom = build_cbom(actor_identity=actor_map, artefact_id="draft_x3_1")
        data = cbom.to_dict()

        self.assertEqual(data["actor_identity"], actor_map)
        self.assertEqual(len(data["actor_identity"]), 6)
        for role in (
            "context_classifier",
            "insight_compiler",
            "source_curator",
            "clean_room_writer",
            "reviewer_qa",
            "auditor",
        ):
            self.assertIn(role, data["actor_identity"])
        json.dumps(data)

    def test_classification_override_row_serialises(self):
        override = ClassificationOverrideRecord(
            context_id="ctx_review_001",
            classified_as="private_reasoning",
            default_would_be="review_finding",
            override_id="ovr_42",
            override_rationale_summary="Reviewer agreed finding was speculative not load-bearing.",
        )
        cbom = build_cbom(
            context_inputs=[
                ContextInput(
                    context_id="ctx_review_001",
                    text="The recommendation may overstate the policy benefit.",
                    material_type="review_finding",
                )
            ],
            classification_overrides=[override],
        )
        data = cbom.to_dict()

        self.assertEqual(len(data["classification_overrides"]), 1)
        self.assertEqual(data["summary"]["classification_overrides"], 1)
        row = data["classification_overrides"][0]
        self.assertEqual(row["context_id"], "ctx_review_001")
        self.assertEqual(row["classified_as"], "private_reasoning")
        self.assertEqual(row["default_would_be"], "review_finding")
        self.assertEqual(row["override_id"], "ovr_42")
        self.assertIn("speculative", row["override_rationale_summary"])
        json.dumps(data)

    def test_override_ledger_refs_serialise_in_order(self):
        cbom = build_cbom(override_ledger_refs=["ovr_001", "ovr_002", "ovr_003"])
        data = cbom.to_dict()

        self.assertEqual(data["override_ledger_refs"], ["ovr_001", "ovr_002", "ovr_003"])
        self.assertEqual(data["summary"]["override_ledger_refs"], 3)

    def test_schema_name_remains_warrantos_cbom_v1(self):
        """INV-007: schema stability within the v0.x series.

        The v0.2 additions are field-additive only. The canonical schema
        name SHALL NOT change.
        """
        cbom = build_cbom(
            actor_identity={"context_classifier": "x"},
            classification_overrides=[
                ClassificationOverrideRecord(
                    context_id="c1",
                    classified_as="x",
                    default_would_be="y",
                    override_id="o1",
                )
            ],
            override_ledger_refs=["o1"],
            context_inputs=[ContextInput("c1", "t")],
        )
        data = cbom.to_dict()

        self.assertEqual(data["schema"], "warrantos-cbom/v1")
        self.assertEqual(cbom.schema, "warrantos-cbom/v1")

    def test_classification_override_referencing_unknown_context_id_raises(self):
        """A classification override must point to a known context_id.

        Catches the laundering-via-override attack at CBOM assembly time:
        if the override claims to reclassify a context_id that was never
        admitted into the CBOM, assembly fails.
        """
        with self.assertRaises(ValueError):
            build_cbom(
                context_inputs=[ContextInput("ctx_known", "Known input.")],
                classification_overrides=[
                    ClassificationOverrideRecord(
                        context_id="ctx_unknown",
                        classified_as="private_reasoning",
                        default_would_be="review_finding",
                        override_id="ovr_99",
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
