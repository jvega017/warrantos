import json
import unittest
from pathlib import Path

import warrantos
from warrantos.provenance.merkle import build_checkpoint


ROOT = Path(__file__).resolve().parents[1]


class ReleaseTruthManifestTests(unittest.TestCase):
    def test_manifest_version_is_package_version(self):
        manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], warrantos.__version__)

    def test_local_release_candidate_is_not_claimed_as_tagged_or_qualified(self):
        manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["release_status"], "local-release-candidate")
        self.assertEqual(manifest["candidate_id"], "warrantos-0.11.0-local-rc.1")
        self.assertIsNone(manifest["git_tag"])
        self.assertFalse(manifest["production_qualified"])

    def test_declared_checkpoint_schema_is_observed(self):
        manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
        checkpoint = build_checkpoint([], run_id="truth-test", timestamp="2026-07-19T00:00:00Z",
                                      prose_sha256="sha256:" + "1" * 64,
                                      cbom_sha256="sha256:" + "2" * 64)
        self.assertEqual(checkpoint["version"], manifest["checkpoint_schema"])

    def test_manifest_does_not_overstate_standalone_reviewer_identity(self):
        manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["binding_protocol"]["semantic_verdict_authenticated"])
        self.assertFalse(
            manifest["identity_boundary"]["standalone_binding_reviewer_authenticated"]
        )
        self.assertTrue(
            manifest["identity_boundary"]["host_authentication_must_be_supplied_by_embedding_runtime"]
        )


if __name__ == "__main__":
    unittest.main()
