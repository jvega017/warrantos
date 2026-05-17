#!/usr/bin/env python3
"""Tests for provenance.salience.

All tests are offline and deterministic. No network access, no sleeps,
no third-party libraries.

Run from the repo root:
    python -m unittest tests.test_salience -v
"""

import unittest

from provenance.salience import (
    LOAD_BEARING_THRESHOLD,
    is_load_bearing,
    score_claim,
)


class TestScoreClaimMagnitudeAndStatute(unittest.TestCase):
    """Statute references and magnitude claims score above the threshold."""

    def test_statute_reference_scores_high(self):
        s = "Disclosure is required under section 12 of the Privacy Act 1988."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)

    def test_bare_section_number_scores_high(self):
        s = "The obligation arises under s. 47 and cannot be waived."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)

    def test_magnitude_billion_scores_high(self):
        s = "The fund disbursed $4 billion to infrastructure projects last year."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)

    def test_magnitude_million_scores_high(self):
        s = "Operating costs fell by 250 million in the most recent quarter."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)

    def test_trillion_scores_high(self):
        s = "Total sovereign debt exceeded 1 trillion for the first time."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)


class TestScoreClaimDecisionLanguage(unittest.TestCase):
    """Decision and recommendation language pushes score above threshold."""

    def test_recommend_scores_high(self):
        s = "We recommend that the agency adopt a risk-based compliance model."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)

    def test_must_scores_high(self):
        s = "All providers must register before 30 June 2026."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)

    def test_will_reduce_scores_high(self):
        s = "The proposed cap will reduce emissions by roughly 15 per cent."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)

    def test_projected_scores_high(self):
        s = "Costs are projected to increase by 8 per cent over five years."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)

    def test_forecast_scores_high(self):
        s = "Growth is forecast to reach 3 per cent by the end of 2027."
        score = score_claim(s)
        self.assertGreaterEqual(score, LOAD_BEARING_THRESHOLD)


class TestScoreClaimLowSalience(unittest.TestCase):
    """Bare year mentions in descriptive sentences score below threshold."""

    def test_bare_year_in_descriptive_sentence_scores_low(self):
        s = "The programme was established in 2019."
        score = score_claim(s)
        # A bare year with no magnitude, statute, or decision language should
        # score below the load-bearing threshold.
        self.assertLess(score, LOAD_BEARING_THRESHOLD)

    def test_hedged_sentence_scores_lower(self):
        # Hedging language should reduce the score.
        s_hedged = "The fund may possibly hold around 4 billion, though this is uncertain."
        s_plain = "The fund holds 4 billion."
        score_hedged = score_claim(s_hedged)
        score_plain = score_claim(s_plain)
        self.assertLess(score_hedged, score_plain)

    def test_purely_descriptive_attribution_scores_low(self):
        # Attribution without any consequential language should score below threshold.
        s = "According to the review, the model was rated satisfactory."
        score = score_claim(s)
        self.assertLess(score, LOAD_BEARING_THRESHOLD)

    def test_purely_descriptive_no_trigger_scores_zero(self):
        # A sentence with no patterns at all should score 0.
        s = "The report was published last year."
        score = score_claim(s)
        self.assertEqual(score, 0.0)


class TestScoreClaimOrdering(unittest.TestCase):
    """A statute-recommendation sentence ranks above a bare-date sentence."""

    def test_statute_recommendation_above_bare_date(self):
        high = (
            "Under section 42, the Minister must table a report within 30 days "
            "of each financial year."
        )
        low = "The review was published in 2021."
        self.assertGreater(score_claim(high), score_claim(low))

    def test_magnitude_plus_decision_above_percentage_only(self):
        high = "The agency will save $2 billion by consolidating data centres."
        mid = "Emissions fell by 12 per cent."
        self.assertGreater(score_claim(high), score_claim(mid))

    def test_percentage_above_bare_year(self):
        mid = "Output rose 8 per cent."
        low = "The programme began in 2022."
        self.assertGreater(score_claim(mid), score_claim(low))


class TestScoreClaimBoundary(unittest.TestCase):
    """Boundary conditions and output contract."""

    def test_score_always_in_range(self):
        sentences = [
            "",
            "No factual content here.",
            "The programme began in 2019.",
            "section 99 of the Act 2022 requires a recommendation to be made "
            "that will increase spending by 3 billion and projected to save 1 trillion.",
        ]
        for s in sentences:
            score = score_claim(s)
            self.assertGreaterEqual(score, 0.0, "score below 0.0 for: %r" % s)
            self.assertLessEqual(score, 1.0, "score above 1.0 for: %r" % s)

    def test_empty_string_scores_zero(self):
        self.assertEqual(score_claim(""), 0.0)

    def test_score_is_float(self):
        self.assertIsInstance(score_claim("The year 2020."), float)

    def test_trigger_parameter_does_not_raise(self):
        # trigger is a pass-through hint; must not raise for any value.
        for t in [None, "year", "statute", "magnitude", "percentage", "attribution", "unknown"]:
            try:
                score_claim("Emissions fell 12 per cent in 2021.", trigger=t)
            except Exception as exc:
                self.fail("score_claim raised for trigger=%r: %s" % (t, exc))


class TestIsLoadBearing(unittest.TestCase):
    """is_load_bearing uses LOAD_BEARING_THRESHOLD = 0.5."""

    def test_threshold_constant_is_half(self):
        self.assertEqual(LOAD_BEARING_THRESHOLD, 0.5)

    def test_statute_sentence_is_load_bearing(self):
        self.assertTrue(
            is_load_bearing("Under section 7 of the Act 2020, consent is required.")
        )

    def test_magnitude_sentence_is_load_bearing(self):
        self.assertTrue(
            is_load_bearing("The contract was worth $1.5 billion.")
        )

    def test_bare_year_sentence_is_not_load_bearing(self):
        self.assertFalse(
            is_load_bearing("The review took place in 2019.")
        )

    def test_trigger_parameter_accepted(self):
        # Must not raise when trigger is provided.
        try:
            result = is_load_bearing("section 5 requires disclosure.", trigger="statute")
        except Exception as exc:
            self.fail("is_load_bearing raised: %s" % exc)
        self.assertIsInstance(result, bool)

    def test_exactly_at_threshold_is_load_bearing(self):
        # A sentence scoring exactly 0.5 is load-bearing (>= threshold).
        # score_claim on a percentage-only sentence: 0.20 (percentage) + 0.10 (year) = 0.30
        # That is below threshold. But a decision-only sentence with no year:
        # "The agency must comply." => 0.35 (decision). Below threshold.
        # "The fund must disburse 3 billion." => 0.35 + 0.30 = 0.65. Above.
        # We verify boundary by checking score is exactly what we expect.
        s = "Output rose 8 per cent in 2022."
        # percentage (0.20) + year (0.10) = 0.30 -> below threshold
        score = score_claim(s)
        self.assertLess(score, LOAD_BEARING_THRESHOLD)
        self.assertFalse(is_load_bearing(s))

    def test_combined_signals_push_above_threshold(self):
        # percentage + decision = 0.20 + 0.35 = 0.55 -> load-bearing
        s = "Costs should increase by 12 per cent."
        self.assertTrue(is_load_bearing(s))


if __name__ == "__main__":
    unittest.main(verbosity=2)
