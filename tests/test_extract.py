"""Tests for citation-trigger detection patterns (provenance.extract).

Tests verify that the extraction patterns correctly identify sentences with
citation-trigger patterns (years, percentages, etc.) while also documenting
that copular claims and common knowledge are intentionally NOT detected.

See docs/LIMITATIONS.md for the design rationale.
"""

import unittest

from warrantos.provenance import extract


class TestCitationTriggerDetection(unittest.TestCase):
    """Citation-trigger pattern matching."""

    def test_year_trigger(self):
        """Years (1800-2999) trigger."""
        self.assertTrue(any(p[1].search("In 2024, the population grew.") for p in extract.CLAIM_TRIGGERS))
        self.assertTrue(any(p[1].search("The year 1920 was transformative.") for p in extract.CLAIM_TRIGGERS))

    def test_percentage_trigger(self):
        """Percentages trigger."""
        self.assertTrue(any(p[1].search("Unemployment was 5.5%.") for p in extract.CLAIM_TRIGGERS))
        self.assertTrue(any(p[1].search("Output rose 12 per cent.") for p in extract.CLAIM_TRIGGERS))

    def test_magnitude_trigger(self):
        """Million/billion/trillion magnitudes trigger."""
        self.assertTrue(any(p[1].search("The GDP reached 2.5 trillion dollars.") for p in extract.CLAIM_TRIGGERS))
        self.assertTrue(any(p[1].search("12 million people attended.") for p in extract.CLAIM_TRIGGERS))

    def test_statute_trigger(self):
        """Statute references trigger."""
        self.assertTrue(any(p[1].search("section 42 of the Act provides...") for p in extract.CLAIM_TRIGGERS))
        self.assertTrue(any(p[1].search("The s. 3 requirement is clear.") for p in extract.CLAIM_TRIGGERS))

    def test_attribution_trigger(self):
        """Attribution language triggers."""
        self.assertTrue(any(p[1].search("According to the OECD, growth was strong.") for p in extract.CLAIM_TRIGGERS))
        self.assertTrue(any(p[1].search("The study shows that exercise improves health.") for p in extract.CLAIM_TRIGGERS))

    def test_superlative_trigger(self):
        """Superlatives trigger."""
        self.assertTrue(any(p[1].search("This is the largest ecosystem.") for p in extract.CLAIM_TRIGGERS))
        self.assertTrue(any(p[1].search("The fastest-growing sector.") for p in extract.CLAIM_TRIGGERS))

    # --- Regression tests: intentional non-detections ---

    def test_copular_claim_not_detected(self):
        """Copular claims (X is Y) are NOT detected. This is intentional."""
        # "Canberra is the capital of Australia" has no citation-trigger pattern
        # so it will not be flagged for sourcing.
        claim = "Canberra is the capital of Australia."
        detected = any(p[1].search(claim) for p in extract.CLAIM_TRIGGERS)
        self.assertFalse(detected,
            "Copular claim should not trigger. See docs/LIMITATIONS.md: copular claims "
            "are intentionally not detected because they are often common knowledge.")

    def test_common_knowledge_claim_not_detected(self):
        """Common-knowledge factual claims are NOT detected. This is intentional."""
        # "Australia has a population of 27 million" has a magnitude trigger, so it WOULD be detected
        # Let's use a claim without triggers: "The Earth orbits the Sun."
        claim = "The Earth orbits the Sun."
        detected = any(p[1].search(claim) for p in extract.CLAIM_TRIGGERS)
        self.assertFalse(detected,
            "Common-knowledge claim without explicit markers should not trigger. "
            "See docs/LIMITATIONS.md: many factual claims lack citation-trigger patterns.")

    def test_population_claim_with_magnitude_is_detected(self):
        """Population figures with magnitudes (millions, billions) ARE detected (they have triggers)."""
        # This is a boundary case: it has a magnitude trigger, so it will be detected,
        # even though it might be common knowledge.
        claim = "Australia has a population of 27 million people."
        detected = any(p[1].search(claim) for p in extract.CLAIM_TRIGGERS)
        self.assertTrue(detected, "Magnitude pattern should trigger detection.")

    def test_cite_needed_tag_is_recognized(self):
        """[CITE NEEDED] tag is recognized as an explicit citation marker."""
        self.assertTrue(extract.CITE_NEEDED.search("[cite needed]"))
        self.assertTrue(extract.CITE_NEEDED.search("[CITE NEEDED]"))
        self.assertTrue(extract.CITE_NEEDED.search("[cite-needed]"))
        self.assertTrue(extract.CITE_NEEDED.search("[cite_needed]"))


class TestSentenceSplitting(unittest.TestCase):
    """Sentence boundary detection."""

    def test_period_sentence_split(self):
        """Sentences are split on periods followed by space."""
        text = "First sentence. Second sentence. Third sentence."
        sents = extract.sentences(text)
        self.assertEqual(len(sents), 3)
        self.assertEqual(sents[0], "First sentence.")
        self.assertEqual(sents[1], "Second sentence.")
        self.assertEqual(sents[2], "Third sentence.")

    def test_newline_sentence_split(self):
        """Sentences are split on newlines."""
        text = "First sentence\nSecond sentence\nThird sentence"
        sents = extract.sentences(text)
        self.assertGreaterEqual(len(sents), 2)

    def test_bullet_point_split(self):
        """Bullet points are treated as sentence boundaries."""
        text = "Intro. - First bullet point - Second bullet point"
        sents = extract.sentences(text)
        self.assertGreater(len(sents), 1)

    def test_empty_and_whitespace_handled(self):
        """Empty strings and pure whitespace are filtered out."""
        text = "Sentence one.   \n\n   Sentence two."
        sents = extract.sentences(text)
        self.assertTrue(all(s.strip() for s in sents), "No empty strings in output")


if __name__ == "__main__":
    unittest.main()
