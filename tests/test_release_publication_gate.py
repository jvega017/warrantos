from __future__ import annotations

import unittest

from tools.check_release_truth import check


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
        self.assertIn("public truth surfaces still contain local-acquisition blockers", errors)


if __name__ == "__main__":
    unittest.main()
