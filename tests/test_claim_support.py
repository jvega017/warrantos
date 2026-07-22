import json
import unittest
from pathlib import Path

from tools.check_release_truth import check
from warrantos.provenance.cbom import ClaimRecord
from warrantos.provenance.claim_support import (
    SUPPORT_STATES, ClaimBinding, SourceSnapshot, SupportLink,
    sha256_text, state_for_legacy_claim, validate_binding_sources,
)

ROOT = Path(__file__).resolve().parents[1]

class ClaimSupportBridgeTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SourceSnapshot(
            source_snapshot_id="src_1", canonical_uri="https://example.invalid/report",
            retrieved_at="2026-07-19T00:00:00Z", content_sha256=sha256_text("source"),
        )
        self.link = SupportLink(source_snapshot_id="src_1", relation="direct_support",
                                locator={"page": 3}, verdict="supports", confidence=0.9)

    def test_vocabulary_matches_manifest(self):
        manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(list(SUPPORT_STATES), manifest["claim_support_vocabulary"])

    def test_legacy_supported_maps_only_to_citation_present(self):
        self.assertEqual(state_for_legacy_claim("supported"), "citation_present")
        self.assertIsNone(state_for_legacy_claim("unsupported"))

    def test_cbom_additive_fields_are_optional(self):
        legacy = ClaimRecord("c1", "claim").to_dict()
        self.assertNotIn("support_state", legacy)
        current = ClaimRecord("c2", "claim", status="supported",
                              support_state="citation_present", binding_ids=["bind_1"]).to_dict()
        self.assertEqual(current["support_state"], "citation_present")
        self.assertEqual(current["binding_ids"], ["bind_1"])

    def test_verified_support_requires_reviewer_and_support_verdict(self):
        with self.assertRaises(ValueError):
            ClaimBinding("b1", "c1", sha256_text("artefact"), "support_verified",
                         supports=[self.link])
        binding = ClaimBinding("b1", "c1", sha256_text("artefact"), "support_verified",
                               supports=[self.link], created_by="agent:binder", reviewed_by="model:reviewer")
        validate_binding_sources(binding, [self.snapshot])

    def test_cli_adapter_does_not_inflate_citation_to_verified_support(self):
        from warrantos.cli.warrantos_cli import to_claim_record
        record = to_claim_record({"sentence": "Claim (Source, 2026).", "citation": "(Source, 2026)"}, [])
        data = record.to_dict()
        self.assertEqual(data["status"], "supported")
        self.assertEqual(data["support_state"], "citation_present")
        self.assertEqual(data["support_ids"], [])
    def test_non_citation_state_requires_source_link(self):
        with self.assertRaises(ValueError):
            ClaimBinding("b1", "c1", sha256_text("artefact"), "source_resolved")

    def test_passage_and_assertion_states_require_evidence_metadata(self):
        bare = SupportLink(source_snapshot_id="src_1", relation="direct_support")
        with self.assertRaises(ValueError):
            ClaimBinding("b1", "c1", sha256_text("artefact"), "passage_located",
                         supports=[bare])
        with self.assertRaises(ValueError):
            ClaimBinding("b1", "c1", sha256_text("artefact"), "support_asserted",
                         supports=[self.link])

    def test_adverse_states_require_matching_verdict(self):
        with self.assertRaises(ValueError):
            ClaimBinding("b1", "c1", sha256_text("artefact"), "contradicted",
                         supports=[self.link], created_by="agent:binder")
    def test_binding_rejects_unknown_snapshot(self):
        binding = ClaimBinding("b1", "c1", sha256_text("artefact"), "source_resolved",
                               supports=[self.link])
        with self.assertRaises(ValueError):
            validate_binding_sources(binding, [])

class ReleaseTruthDriftTests(unittest.TestCase):
    def test_public_truth_surfaces_match_manifest(self):
        self.assertEqual(check(), [])

if __name__ == "__main__":
    unittest.main()
