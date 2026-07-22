import dataclasses
import unittest

from warrantos.provenance.claim_support import (
    ClaimSupportState, SupportLink, assert_binding, passage_at, sha256_bytes,
    sha256_text, snapshot_text, verify_binding, verify_recorded_binding,
)


class BindingVerificationTests(unittest.TestCase):
    def setUp(self):
        self.source = "The programme reduced processing time by 18 percent in the pilot."
        self.artefact = "Pilot results show an 18 percent reduction in processing time."
        self.claim = "an 18 percent reduction in processing time"
        self.passage = "reduced processing time by 18 percent in the pilot"
        self.snapshot = snapshot_text(
            source_snapshot_id="src_1", canonical_uri="file:pilot.txt",
            retrieved_at="2026-07-20T00:00:00Z", content=self.source.encode(),
        )
        self.binding = assert_binding(
            binding_id="bind_1", claim_id="claim_1", claim_text=self.claim,
            artefact_text=self.artefact, snapshot=self.snapshot,
            source_text=self.source, passage=self.passage,
            created_by="agent:binder", created_at="2026-07-20T00:00:01Z",
        )

    def verify(self, **changes):
        args = dict(
            artefact_text=self.artefact, snapshots=[self.snapshot],
            source_bytes={"src_1": self.source.encode()}, reviewer="human:reviewer",
            semantic_verdict="supports",
        )
        args.update(changes)
        return verify_binding(self.binding, **args)

    def test_reproduction_requires_exact_bytes_and_passages(self):
        result = self.verify()
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.binding.support_state, "passage_reproduced")
        self.assertIsNone(result.binding.supports[0].verdict)
        self.assertIsNone(result.binding.reviewed_by)
        self.assertEqual(passage_at(self.source, self.binding.supports[0].locator), self.passage)

    def test_raw_reviewer_and_verdict_cannot_mint_verified_support(self):
        result = self.verify(
            reviewer="human:any-label",
            semantic_verdict="supports",
        )
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.binding.support_state, "passage_reproduced")
        self.assertNotEqual(result.binding.support_state, "support_verified")
        self.assertIsNone(result.binding.reviewed_by)
        self.assertIsNone(result.binding.supports[0].verdict)
        self.assertTrue(result.checks["legacy_semantic_inputs_ignored"])

    def test_legacy_recorded_semantic_label_is_downgraded_on_reverification(self):
        legacy = dataclasses.replace(
            self.binding,
            support_state=ClaimSupportState.SUPPORT_VERIFIED.value,
            supports=[dataclasses.replace(self.binding.supports[0], verdict="supports")],
            reviewed_by="human:any-label",
        )
        result = verify_recorded_binding(
            legacy,
            artefact_text=self.artefact,
            snapshots=[self.snapshot],
            source_bytes={"src_1": self.source.encode()},
        )
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.binding.support_state, "passage_reproduced")
        self.assertIsNone(result.binding.reviewed_by)
        self.assertIsNone(result.binding.supports[0].verdict)

    def test_source_substitution_fails_closed(self):
        result = self.verify(source_bytes={"src_1": b"fabricated source"})
        self.assertFalse(result.valid)
        self.assertFalse(result.checks["support_0_content_digest"])

    def test_locator_or_quote_substitution_fails_closed(self):
        link = dataclasses.replace(self.binding.supports[0], quoted_span_sha256=sha256_text("other"))
        altered = dataclasses.replace(self.binding, supports=[link])
        result = verify_binding(
            altered, artefact_text=self.artefact, snapshots=[self.snapshot],
            source_bytes={"src_1": self.source.encode()}, reviewer="human:reviewer",
            semantic_verdict="supports",
        )
        self.assertFalse(result.valid)
        self.assertFalse(result.checks["support_0_passage_digest"])

    def test_artefact_substitution_fails_closed(self):
        result = self.verify(artefact_text=self.artefact + " Changed.")
        self.assertFalse(result.valid)
        self.assertFalse(result.checks["artefact_revision"])

    def test_self_review_label_is_ignored_not_treated_as_authentication(self):
        result = self.verify(reviewer="agent:binder")
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.binding.support_state, "passage_reproduced")
        self.assertIsNone(result.binding.reviewed_by)

    def test_snapshot_hashes_exact_bytes_and_extracted_text(self):
        self.assertEqual(self.snapshot.content_sha256, sha256_bytes(self.source.encode()))
        self.assertEqual(self.snapshot.extraction_sha256, sha256_text(self.source))


if __name__ == "__main__":
    unittest.main()
