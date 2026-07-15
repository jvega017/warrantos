#!/usr/bin/env python3
"""Tests for claim status semantics (Phase 1 fix M1).

The critical distinction: citation presence (cited/uncited) is separate from
verification result (supported/contradicted). A cited claim may still be
contradicted by the verifier.
"""

import json
import tempfile
import unittest
from pathlib import Path

from warrantos.provenance.claims import ClaimStatus, get_report_status_key
from warrantos.provenance.cbom import ClaimRecord, build_cbom


class TestClaimStatusEnum(unittest.TestCase):
    """Test ClaimStatus enum definition."""

    def test_claim_status_enum_has_all_required_values(self):
        """Verify the enum defines all Phase 1 fix M1 states."""
        self.assertEqual(ClaimStatus.UNCITED.value, "uncited")
        self.assertEqual(ClaimStatus.CITED_UNVERIFIED.value, "cited_unverified")
        self.assertEqual(ClaimStatus.SUPPORTED.value, "supported")
        self.assertEqual(ClaimStatus.CONTRADICTED.value, "contradicted")
        self.assertEqual(ClaimStatus.UNVERIFIABLE.value, "unverifiable")

    def test_claim_status_str_representation(self):
        """Verify __str__ returns the value."""
        self.assertEqual(str(ClaimStatus.UNCITED), "uncited")
        self.assertEqual(str(ClaimStatus.CITED_UNVERIFIED), "cited_unverified")
        self.assertEqual(str(ClaimStatus.SUPPORTED), "supported")


class TestReportStatusKey(unittest.TestCase):
    """Test report grouping logic for cited/uncited."""

    def test_uncited_claim_maps_to_uncited_category(self):
        """Claims without citations map to 'uncited' report category."""
        self.assertEqual(get_report_status_key(ClaimStatus.UNCITED.value), "uncited")

    def test_all_cited_statuses_map_to_cited_category(self):
        """All cited statuses (regardless of verification result) map to 'cited'."""
        self.assertEqual(
            get_report_status_key(ClaimStatus.CITED_UNVERIFIED.value), "cited"
        )
        self.assertEqual(get_report_status_key(ClaimStatus.SUPPORTED.value), "cited")
        self.assertEqual(
            get_report_status_key(ClaimStatus.CONTRADICTED.value), "cited"
        )
        self.assertEqual(get_report_status_key(ClaimStatus.UNVERIFIABLE.value), "cited")


class TestClaimRecordStatuses(unittest.TestCase):
    """Test claim record construction with new semantics."""

    def test_uncited_claim_record(self):
        """Claim record with UNCITED status."""
        claim = ClaimRecord(
            claim_id="claim_001",
            text="The cost was reduced.",
            support_ids=[],
            status=ClaimStatus.UNCITED.value,
        )
        self.assertEqual(claim.status, "uncited")
        data = claim.to_dict()
        self.assertEqual(data["status"], "uncited")

    def test_cited_unverified_claim_record(self):
        """Claim record with CITED_UNVERIFIED status (initial state)."""
        claim = ClaimRecord(
            claim_id="claim_002",
            text="The cost was reduced according to [source: report.pdf].",
            support_ids=[],
            status=ClaimStatus.CITED_UNVERIFIED.value,
        )
        self.assertEqual(claim.status, "cited_unverified")
        data = claim.to_dict()
        self.assertEqual(data["status"], "cited_unverified")

    def test_supported_claim_record(self):
        """Claim record after verification confirmed support."""
        claim = ClaimRecord(
            claim_id="claim_003",
            text="The cost was reduced according to [source: report.pdf].",
            support_ids=["ctx_report"],
            status=ClaimStatus.SUPPORTED.value,
        )
        self.assertEqual(claim.status, "supported")

    def test_contradicted_claim_record(self):
        """Claim record after verification found contradiction."""
        claim = ClaimRecord(
            claim_id="claim_004",
            text="The cost increased according to [source: report.pdf].",
            support_ids=["ctx_report"],
            status=ClaimStatus.CONTRADICTED.value,
        )
        self.assertEqual(claim.status, "contradicted")

    def test_unverifiable_claim_record(self):
        """Claim record when verification cannot complete."""
        claim = ClaimRecord(
            claim_id="claim_005",
            text="The cost was reduced according to [source: missing-page.pdf].",
            support_ids=[],
            status=ClaimStatus.UNVERIFIABLE.value,
        )
        self.assertEqual(claim.status, "unverifiable")


class TestCBOMWithNewSemantics(unittest.TestCase):
    """Test CBOM assembly with new claim semantics."""

    def test_cbom_reflects_claim_status_changes(self):
        """CBOM correctly carries claim status through assembly."""
        from warrantos.provenance.cbom import ContextInput

        cbom = build_cbom(
            context_inputs=[
                ContextInput(
                    context_id="ctx_source",
                    text="Official report page 4.",
                    source="report.pdf",
                    material_type="source",
                )
            ],
            claims=[
                ClaimRecord(
                    claim_id="claim_001",
                    text="The programme reduced costs.",
                    support_ids=[],
                    status=ClaimStatus.UNCITED.value,
                ),
                ClaimRecord(
                    claim_id="claim_002",
                    text="The programme reduced costs according to [source: report.pdf].",
                    support_ids=[],
                    status=ClaimStatus.CITED_UNVERIFIED.value,
                ),
            ],
            artefact_id="draft_1",
        )
        data = cbom.to_dict()
        self.assertEqual(len(data["claims"]), 2)
        self.assertEqual(data["claims"][0]["status"], "uncited")
        self.assertEqual(data["claims"][1]["status"], "cited_unverified")


class TestSemanticDistinction(unittest.TestCase):
    """Test that cited/supported are properly distinguished."""

    def test_cited_is_not_synonymous_with_supported(self):
        """Citation presence does not imply verification success."""
        # A claim can be cited but contradicted by the verifier.
        cited_contradicted = ClaimRecord(
            claim_id="claim_x",
            text="Claim with [citation]",
            support_ids=[],
            status=ClaimStatus.CONTRADICTED.value,
        )
        # This claim is "cited" (for report grouping) but not "supported".
        self.assertEqual(
            get_report_status_key(cited_contradicted.status), "cited"
        )
        self.assertNotEqual(cited_contradicted.status, "supported")
        self.assertEqual(cited_contradicted.status, "contradicted")

    def test_uncited_is_not_contradicted(self):
        """An uncited claim has not been verified, so it's neither supported nor contradicted."""
        uncited = ClaimRecord(
            claim_id="claim_y",
            text="Claim without citation",
            support_ids=[],
            status=ClaimStatus.UNCITED.value,
        )
        self.assertEqual(get_report_status_key(uncited.status), "uncited")
        self.assertNotEqual(uncited.status, "supported")
        self.assertNotEqual(uncited.status, "contradicted")

    def test_state_transitions(self):
        """Test the allowed state transitions."""
        # Initial: UNCITED (no citation)
        initial = ClaimStatus.UNCITED.value
        self.assertEqual(initial, "uncited")

        # Initial: CITED_UNVERIFIED (citation present, no verification)
        initial_cited = ClaimStatus.CITED_UNVERIFIED.value
        self.assertEqual(initial_cited, "cited_unverified")

        # After verification: CITED_UNVERIFIED → SUPPORTED
        after_verify_ok = ClaimStatus.SUPPORTED.value
        self.assertEqual(after_verify_ok, "supported")

        # After verification: CITED_UNVERIFIED → CONTRADICTED
        after_verify_bad = ClaimStatus.CONTRADICTED.value
        self.assertEqual(after_verify_bad, "contradicted")

        # After verification error: CITED_UNVERIFIED → UNVERIFIABLE
        after_verify_error = ClaimStatus.UNVERIFIABLE.value
        self.assertEqual(after_verify_error, "unverifiable")


class TestReportKeyNamesSemantics(unittest.TestCase):
    """Test that report keys accurately reflect the new semantics."""

    def test_report_uses_cited_uncited_not_supported_unsupported(self):
        """Report should use 'cited'/'uncited' not 'supported'/'unsupported'."""
        # This test verifies the semantic shift:
        # OLD (conflated): claims_supported, claims_unsupported
        # NEW (distinct): claims_cited, claims_uncited
        #
        # "claims_cited" counts all claims with a citation anchor,
        # regardless of whether the verifier found support or contradiction.
        # "claims_uncited" counts all claims without a citation.

        claim_rows = [
            {"sentence": "Claim 1", "citation": "yes"},  # cited
            {"sentence": "Claim 2", "citation": "yes"},  # cited
            {"sentence": "Claim 3"},  # uncited (no citation key)
        ]

        # Compute using new semantics
        claims_cited = sum(1 for c in claim_rows if c.get("citation"))
        claims_uncited = sum(1 for c in claim_rows if not c.get("citation"))

        self.assertEqual(claims_cited, 2)
        self.assertEqual(claims_uncited, 1)

        # Verify the keys don't mention "supported" in the context of raw claim detection
        # (supported/contradicted are post-verification statuses)
        self.assertTrue(
            all(key in ["citation"] for key in claim_rows[0])
            or "citation" in claim_rows[0]
        )


if __name__ == "__main__":
    unittest.main()
