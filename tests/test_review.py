#!/usr/bin/env python3
"""Tests for provenance.review."""

import unittest

from warrantos.provenance.review import (
    ReviewFinding,
    consolidate_findings,
    render_review_markdown,
)


class TestConsolidateFindings(unittest.TestCase):

    def test_groups_convergent_distinct_and_deferred_findings(self):
        findings = [
            ReviewFinding(
                finding_id="a",
                title="Citation missing",
                detail="Claim needs a source.",
                severity="P1",
                location="paper.md:12",
                issue_key="citation-gap",
            ),
            ReviewFinding(
                finding_id="b",
                title="Citation absent",
                detail="Same claim is uncited.",
                severity="P2",
                location="paper.md:12",
                issue_key="citation-gap",
            ),
            ReviewFinding(
                finding_id="c",
                title="Table label unclear",
                detail="Reader cannot tell units.",
                severity="P2",
                location="paper.md:40",
            ),
            ReviewFinding(
                finding_id="d",
                title="Future quantitative audit",
                detail="Needs external data refresh.",
                severity="P3",
                location="paper.md:90",
                deferred=True,
            ),
        ]

        result = consolidate_findings(findings)

        self.assertEqual(len(result.convergent), 1)
        self.assertEqual(result.convergent[0].issue_key, "citation-gap")
        self.assertEqual(result.convergent[0].severity, "P1")
        self.assertEqual(result.convergent[0].finding_ids, ["a", "b"])
        self.assertEqual([group.finding_ids for group in result.distinct], [["c"]])
        self.assertEqual([group.finding_ids for group in result.deferred], [["d"]])

    def test_distinct_groups_preserve_first_seen_order(self):
        result = consolidate_findings(
            [
                ReviewFinding("one", "First", "Detail", "P2", "a.md:1"),
                ReviewFinding("two", "Second", "Detail", "P1", "a.md:2"),
            ]
        )

        self.assertEqual([group.title for group in result.distinct], ["First", "Second"])


class TestReviewMarkdown(unittest.TestCase):

    def test_markdown_renders_group_sections_and_locations(self):
        result = consolidate_findings(
            [
                ReviewFinding(
                    "a",
                    "Citation missing",
                    "Claim needs a source.",
                    "P1",
                    "paper.md:12",
                    issue_key="citation-gap",
                ),
                ReviewFinding(
                    "b",
                    "Citation absent",
                    "Same claim is uncited.",
                    "P2",
                    "paper.md:12",
                    issue_key="citation-gap",
                ),
                ReviewFinding("c", "Table label unclear", "Reader cannot tell units.", "P2", "paper.md:40"),
                ReviewFinding("d", "Future audit", "Needs external data refresh.", "P3", "paper.md:90", deferred=True),
            ]
        )

        markdown = render_review_markdown(result)

        self.assertIn("## Convergent", markdown)
        self.assertIn("## Distinct", markdown)
        self.assertIn("## Deferred", markdown)
        self.assertIn("Citation missing", markdown)
        self.assertIn("paper.md:12", markdown)
        self.assertIn("Sources: a, b", markdown)
        self.assertTrue(markdown.endswith("\n"))

    def test_markdown_handles_empty_review(self):
        markdown = render_review_markdown(consolidate_findings([]))

        self.assertIn("No findings.", markdown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
