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

    # --- Phase 1b regression tests: expanded statute keywords ---

    def _named_trigger(self, name):
        """Return the compiled pattern for a named trigger."""
        return dict(extract.CLAIM_TRIGGERS)[name]

    def test_statute_keyword_regulation(self):
        """Phase 1b: 'regulation' triggers the statute pattern."""
        statute = self._named_trigger("statute")
        self.assertTrue(statute.search("The regulation requires annual reporting."))
        self.assertTrue(statute.search("New regulations came into force."))

    def test_statute_keyword_statute(self):
        """Phase 1b: 'statute' triggers the statute pattern."""
        statute = self._named_trigger("statute")
        self.assertTrue(statute.search("This statute states the maximum penalty."))

    def test_statute_keywords_expanded_set(self):
        """Phase 1b: newly added statute keywords all trigger."""
        statute = self._named_trigger("statute")
        samples = [
            "The legislation was amended last session.",
            "There is a statutory obligation to report.",
            "Code section 12 applies here.",
            "Division 3 covers exemptions.",
            "Schedule 2 lists the fees.",
            "Clause 7 was struck out.",
            "Article 5 guarantees due process.",
            "See subsection (b) for details.",
            "The legislative agenda stalled.",
            "The ordinance bans overnight parking.",
            "The act was repealed.",
            "The bill passed the senate.",
            "Congress voted on the measure.",
            "Parliament debated the amendment.",
            "The law prohibits this conduct.",
            "There are legal obligations involved.",
            "Judicial review is available.",
            "The court dismissed the appeal.",
            "The mandate expires next year.",
            "This requirement is binding.",
            "The authority granted approval.",
            "The provision sunsets in two years.",
        ]
        for s in samples:
            self.assertTrue(statute.search(s), "statute pattern should match: %r" % s)

    def test_statute_keywords_case_insensitive(self):
        """Phase 1b: keyword alternatives match regardless of case."""
        statute = self._named_trigger("statute")
        self.assertTrue(statute.search("REGULATION 7 applies."))
        self.assertTrue(statute.search("the Statute of limitations"))

    def test_statute_numbered_references_still_detected(self):
        """Original numbered statute references still trigger (regression)."""
        statute = self._named_trigger("statute")
        self.assertTrue(statute.search("section 42 of the Act provides..."))
        self.assertTrue(statute.search("The s. 3 requirement is clear."))
        self.assertTrue(statute.search("under the Privacy Act 1988"))

    # --- Phase 1b regression tests: expanded attribution phrases ---

    def test_attribution_phrase_demonstrates(self):
        """Phase 1b: 'demonstrates'/'demonstrated' trigger attribution."""
        attribution = self._named_trigger("attribution")
        self.assertTrue(attribution.search("The study demonstrated significant gains."))
        self.assertTrue(attribution.search("The evidence demonstrates a clear link."))

    def test_attribution_phrase_according_to_sources(self):
        """Phase 1b: 'According to sources' triggers attribution."""
        attribution = self._named_trigger("attribution")
        self.assertTrue(attribution.search("According to sources, the deal is close."))

    def test_attribution_phrases_expanded_set(self):
        """Phase 1b: newly added attribution phrases all trigger."""
        attribution = self._named_trigger("attribution")
        samples = [
            "The minister stated the policy was final.",
            "Officials confirmed the timeline.",
            "The audit revealed discrepancies.",
            "The company disclosed the breach.",
            "The trend indicates a slowdown.",
            "The report concludes the scheme failed.",
            "The reviewer notes several gaps.",
            "The paper cites earlier work.",
            "The tribunal determines eligibility.",
            "The panel assessed the damage.",
            "The team evaluated the options.",
            "The referee judged the appeal.",
            "Investigators found no wrongdoing.",
            "Auditors identified three risks.",
            "Analysts reported strong demand.",
            "The failures were documented in detail.",
            "The effect was shown in trials.",
            "The link was established by researchers.",
            "The results were verified independently.",
        ]
        for s in samples:
            self.assertTrue(attribution.search(s), "attribution pattern should match: %r" % s)

    def test_attribution_original_phrases_still_detected(self):
        """Original attribution phrases still trigger (regression)."""
        attribution = self._named_trigger("attribution")
        self.assertTrue(attribution.search("According to the OECD, growth was strong."))
        self.assertTrue(attribution.search("The study shows that exercise improves health."))
        self.assertTrue(attribution.search("Researchers found that sleep matters."))
        self.assertTrue(attribution.search("The agency reported that costs fell."))

    # --- Phase 1b sanity checks: numeric detection unchanged ---

    def test_numeric_detection_still_works(self):
        """Sanity: numeric/percentage detection is unaffected by phase 1b."""
        self.assertTrue(any(p[1].search("42 percent of respondents agreed.") for p in extract.CLAIM_TRIGGERS))
        percentage = self._named_trigger("percentage")
        self.assertTrue(percentage.search("42 percent of respondents agreed."))
        self.assertTrue(percentage.search("Unemployment was 5.5%."))
        year = self._named_trigger("year")
        self.assertTrue(year.search("In 2024, the population grew."))

    def test_hook_patterns_match_extract_patterns(self):
        """The hook's CLAIM_TRIGGERS must mirror extract.CLAIM_TRIGGERS exactly."""
        import importlib.util
        from pathlib import Path
        hook_path = (
            Path(extract.__file__).resolve().parents[1] / "hooks" / "provenance_check.py"
        )
        spec = importlib.util.spec_from_file_location("_hook_for_parity", str(hook_path))
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        self.assertEqual(
            [(n, p.pattern, p.flags) for n, p in extract.CLAIM_TRIGGERS],
            [(n, p.pattern, p.flags) for n, p in hook.CLAIM_TRIGGERS],
            "hooks/provenance_check.py and provenance/extract.py have diverged",
        )

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
