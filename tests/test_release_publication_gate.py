from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.check_release_truth import _check_acquisition_truth, check


class ReleasePublicationGateTests(unittest.TestCase):
    def test_local_candidate_truth_is_consistent_but_publication_fails_closed(self):
        self.assertEqual(check(), [])
        errors = check("public")
        self.assertIn("public publication requires release_status public-beta", errors)
        self.assertIn("public publication requires git_tag v0.11.0b2", errors)
        self.assertIn(
            "public publication requires the GitHub Action to install the release version",
            errors,
        )
        self.assertIn(
            "public publication requires Claude plugin surfaces to match the release version",
            errors,
        )
        self.assertIn(
            "public publication requires the P0 acquisition block to be replaced by a promoted-version contract",
            errors,
        )
        self.assertIn("public truth surfaces still contain local-acquisition blockers", errors)

    def test_current_acquisition_surfaces_recommend_only_authenticated_candidate(self):
        self.assertEqual(_check_acquisition_truth(Path(__file__).resolve().parents[1], {
            "distribution_surface_versions": {
                "public_recommendation": "blocked-p0-advisory",
                "recommended_current_path": "authenticated-0.11.0b2-candidate-bundle",
            }
        }), [])

    def test_blocked_public_ctas_cannot_regress(self):
        unsafe_rows = {
            "package-index install": "pip install warrantos\n",
            "zero-install package execution": "uvx warrantos demo\n",
            "advisory-affected GitHub Action": "- uses: jvega017/warrantos@v0.10.0\n",
            "advisory-affected pre-commit ref": "    rev: v0.10.0\n",
        }
        manifest = {
            "distribution_surface_versions": {
                "public_recommendation": "blocked-p0-advisory",
                "recommended_current_path": "authenticated-0.11.0b2-candidate-bundle",
            }
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            safe = {
                "README.md": "authenticated 0.11.0b2\nExpectedManifestSha256\n",
                "docs/index.md": "authenticated 0.11.0b2\nExpectedManifestSha256\n",
                "docs/QUICKSTART.md": "authenticated 0.11.0b2\nExpectedManifestSha256\n",
                "docs/DISTRIBUTION.md": "authenticated\n0.11.0b2\nP0 artefact-binding\n",
                "docs/FULL-OVERVIEW.md": "candidate bundle only\n",
                "docs/MCP-CONFIG.md": "source developer evaluation only\n",
                "docs/NO-API-KEY.md": "candidate bundle only\n",
                "docs/VERIFICATION.md": "candidate bundle only\n",
            }
            for relative, text in safe.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            for label, unsafe in unsafe_rows.items():
                with self.subTest(label=label):
                    path = root / "README.md"
                    path.write_text(safe["README.md"] + unsafe, encoding="utf-8")
                    errors = _check_acquisition_truth(root, manifest)
                    self.assertTrue(any(label in error for error in errors), errors)
                    path.write_text(safe["README.md"], encoding="utf-8")

    def test_every_published_adopter_page_is_scanned(self):
        manifest = {
            "distribution_surface_versions": {
                "public_recommendation": "blocked-p0-advisory",
                "recommended_current_path": "authenticated-0.11.0b2-candidate-bundle",
            }
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            safe = {
                "README.md": "authenticated 0.11.0b2\nExpectedManifestSha256\n",
                "docs/index.md": "authenticated 0.11.0b2\nExpectedManifestSha256\n",
                "docs/QUICKSTART.md": "authenticated 0.11.0b2\nExpectedManifestSha256\n",
                "docs/DISTRIBUTION.md": "authenticated\n0.11.0b2\nP0 artefact-binding\n",
                "docs/FULL-OVERVIEW.md": "candidate bundle only\n",
                "docs/MCP-CONFIG.md": "candidate bundle only\n",
                "docs/NO-API-KEY.md": "candidate bundle only\n",
                "docs/VERIFICATION.md": "candidate bundle only\n",
            }
            for relative, text in safe.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            for relative in (
                "docs/FULL-OVERVIEW.md", "docs/MCP-CONFIG.md",
                "docs/NO-API-KEY.md", "docs/VERIFICATION.md",
            ):
                with self.subTest(relative=relative):
                    path = root / relative
                    path.write_text("pip install claude-provenance\n", encoding="utf-8")
                    errors = _check_acquisition_truth(root, manifest)
                    self.assertTrue(any(relative in error for error in errors), errors)
                    path.write_text(safe[relative], encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
