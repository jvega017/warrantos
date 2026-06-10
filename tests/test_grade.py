#!/usr/bin/env python3
"""Tests for provenance.grade.

All tests are offline and deterministic. urllib and any LLM call are mocked
with unittest.mock. No network access, no sleeps.

Run from the repo root:
    python -m unittest tests.test_grade -v
"""

import os
import unittest
import unittest.mock
from unittest.mock import MagicMock, patch

from warrantos.provenance.grade import (
    CodexGrader,
    HeuristicGrader,
    LLMGrader,
    Verdict,
    get_grader,
)


class TestHeuristicGraderWithSource(unittest.TestCase):
    """HeuristicGrader when source_text is provided (fetch+heuristic path)."""

    def setUp(self):
        self.grader = HeuristicGrader()

    def test_verified_when_salient_tokens_present(self):
        claim = "Emissions fell 12 per cent in 2021."
        source = "Analysis showed a 12 per cent reduction in emissions during 2021 fiscal year."
        v = self.grader.grade(claim, source, "https://example.org/report")
        self.assertEqual(v.verdict, "verified")
        self.assertEqual(v.grader, "fetch+heuristic")
        self.assertIsInstance(v, Verdict)

    def test_not_addressed_when_tokens_absent(self):
        claim = "Revenue reached 4 billion dollars in 2023."
        source = "The policy document discusses governance frameworks and accountability."
        v = self.grader.grade(claim, source, "https://example.org/policy")
        self.assertEqual(v.verdict, "not_addressed")
        self.assertEqual(v.grader, "fetch+heuristic")

    def test_not_addressed_with_none_citation(self):
        # Source provided but no citation URL; still not_addressed if tokens absent.
        claim = "The budget exceeded 9 billion in 2022."
        source = "This report addresses structural reform only."
        v = self.grader.grade(claim, source, None)
        self.assertEqual(v.verdict, "not_addressed")
        self.assertEqual(v.grader, "fetch+heuristic")

    def test_verified_case_insensitive(self):
        # Token matching must be case-insensitive.
        claim = "The programme began in 2019."
        source = "Background: THE PROGRAMME BEGAN IN 2019 under new leadership."
        v = self.grader.grade(claim, source, None)
        self.assertEqual(v.verdict, "verified")

    def test_rationale_max_200_chars(self):
        claim = "Spending rose 7 per cent."
        source = "Unrelated content about something completely different."
        v = self.grader.grade(claim, source, None)
        self.assertLessEqual(len(v.rationale), 200)

    def test_verdict_is_dataclass(self):
        v = self.grader.grade("Output rose 5 per cent.", "Output rose 5 per cent.", None)
        self.assertTrue(hasattr(v, "claim_text"))
        self.assertTrue(hasattr(v, "citation"))
        self.assertTrue(hasattr(v, "verdict"))
        self.assertTrue(hasattr(v, "confidence"))
        self.assertTrue(hasattr(v, "rationale"))
        self.assertTrue(hasattr(v, "grader"))


class TestHeuristicGraderWithoutSource(unittest.TestCase):
    """HeuristicGrader when no source_text is available (heuristic path)."""

    def setUp(self):
        self.grader = HeuristicGrader()

    def test_unverifiable_when_citation_but_no_source(self):
        claim = "The rate reached 3.5 per cent in 2024."
        v = self.grader.grade(claim, None, "(Smith, 2024)")
        self.assertEqual(v.verdict, "unverifiable")
        self.assertEqual(v.grader, "heuristic")

    def test_unverifiable_grader_label(self):
        v = self.grader.grade("Revenue was 2 billion.", None, "https://example.org")
        # No source_text despite having a URL citation means unverifiable.
        self.assertEqual(v.verdict, "unverifiable")
        self.assertEqual(v.grader, "heuristic")

    def test_skipped_when_neither_citation_nor_source(self):
        claim = "Output grew 8 per cent."
        v = self.grader.grade(claim, None, None)
        self.assertEqual(v.verdict, "skipped")
        self.assertEqual(v.grader, "heuristic")

    def test_skipped_confidence_is_none(self):
        v = self.grader.grade("The year was 2020.", None, None)
        self.assertIsNone(v.confidence)


class TestLLMGraderFallback(unittest.TestCase):
    """LLMGrader falls back to heuristic and never raises."""

    def test_no_api_key_falls_back_to_heuristic(self):
        """With no ANTHROPIC_API_KEY, LLMGrader must use HeuristicGrader."""
        with patch.dict(os.environ, {}, clear=False):
            # Ensure the key is absent.
            os.environ.pop("ANTHROPIC_API_KEY", None)
            grader = LLMGrader()
            v = grader.grade("Output rose 5 per cent.", None, None)
        self.assertEqual(v.verdict, "skipped")
        self.assertIn("heuristic", v.grader)

    def test_no_api_key_never_raises(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            grader = LLMGrader()
            # Must not raise for any combination of inputs.
            try:
                grader.grade("Revenue was 4 billion in 2023.", None, None)
                grader.grade("Study shows 12 per cent decline.", "some source text", "https://x.org")
                grader.grade("According to the report, output fell.", None, "(Jones, 2022)")
            except Exception as exc:
                self.fail("LLMGrader raised an exception when no API key: %s" % exc)

    def test_api_key_set_but_urllib_raises_falls_back(self):
        """When urllib raises (network error), LLMGrader falls back without raising."""
        import urllib.error

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-abc"}):
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network error")):
                grader = LLMGrader()
                try:
                    v = grader.grade("Costs rose 9 per cent in 2023.", None, None)
                except Exception as exc:
                    self.fail("LLMGrader raised after urllib error: %s" % exc)
        # After fallback, result should be from heuristic.
        self.assertIn("heuristic", v.grader)

    def test_api_key_set_but_non_200_response_falls_back(self):
        """A non-200 HTTP status causes graceful fallback to heuristic."""
        mock_resp = MagicMock()
        mock_resp.status = 429
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-abc"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                grader = LLMGrader()
                try:
                    v = grader.grade("The fund held 2 billion.", None, "(ATO, 2023)")
                except Exception as exc:
                    self.fail("LLMGrader raised on non-200: %s" % exc)
        self.assertIn("heuristic", v.grader)

    def test_api_key_set_but_json_parse_fails_falls_back(self):
        """Malformed JSON from the API causes graceful fallback."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"NOT JSON {{{"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-abc"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                grader = LLMGrader()
                try:
                    v = grader.grade("Output fell 4 per cent.", "Some source text here.", "https://x.org")
                except Exception as exc:
                    self.fail("LLMGrader raised on bad JSON: %s" % exc)
        self.assertIn("heuristic", v.grader)

    def test_successful_llm_response_uses_llm_grader_label(self):
        """A well-formed LLM response should produce an llm:<model> grader label."""
        import json as _json

        response_body = _json.dumps({
            "content": [
                {"type": "text", "text": _json.dumps({
                    "verdict": "verified",
                    "confidence": 0.9,
                    "rationale": "Source confirms the claim.",
                })}
            ]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-abc"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                grader = LLMGrader()
                v = grader.grade(
                    "Costs rose 9 per cent.",
                    "Analysis confirms costs rose 9 per cent.",
                    "https://example.org/data",
                )
        self.assertEqual(v.verdict, "verified")
        self.assertAlmostEqual(v.confidence, 0.9)
        self.assertIn("llm:", v.grader)


class TestGetGrader(unittest.TestCase):
    """get_grader() returns the right type based on environment."""

    def test_returns_heuristic_when_no_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            grader = get_grader()
        self.assertIsInstance(grader, HeuristicGrader)

    def test_returns_llm_when_key_present(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            grader = get_grader()
        self.assertIsInstance(grader, LLMGrader)

    def test_returns_heuristic_when_key_empty_string(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            grader = get_grader()
        self.assertIsInstance(grader, HeuristicGrader)


class TestCodexGraderNoSource(unittest.TestCase):
    """CodexGrader is deterministic and spawns no subprocess without a source.

    These items match HeuristicGrader exactly so the two graders are compared
    on identical ground for the no-source classes.
    """

    def setUp(self):
        self.g = CodexGrader()

    def test_citation_without_source_is_unverifiable(self):
        v = self.g.grade("A claim.", None, "https://example.gov.au/x")
        self.assertEqual(v.verdict, "unverifiable")
        self.assertEqual(v.grader, "codex-cli")

    def test_no_citation_no_source_is_skipped(self):
        v = self.g.grade("A claim.", None, None)
        self.assertEqual(v.verdict, "skipped")
        self.assertEqual(v.grader, "codex-cli")


class TestCodexGraderGracefulFailure(unittest.TestCase):
    """CodexGrader degrades to verdict 'error' and never raises when the
    Codex CLI is absent. No real Codex invocation occurs in this test.
    """

    def setUp(self):
        self._saved = os.environ.get("PROVENANCE_CODEX_BIN")
        # Point the grader at a binary that cannot exist.
        os.environ["PROVENANCE_CODEX_BIN"] = "codex_definitely_not_a_real_binary_zzz"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("PROVENANCE_CODEX_BIN", None)
        else:
            os.environ["PROVENANCE_CODEX_BIN"] = self._saved

    def test_missing_binary_yields_error_verdict(self):
        v = CodexGrader().grade(
            "Spending rose 10 per cent in 2022.",
            "Spending fell 10 per cent in 2022.",
            None,
        )
        self.assertEqual(v.verdict, "error")
        self.assertEqual(v.grader, "codex-cli")
        self.assertIsInstance(v.rationale, str)

    def test_grade_never_raises(self):
        try:
            CodexGrader().grade("A claim with a source.", "Some source text.", None)
        except Exception as exc:  # pragma: no cover - failure path
            self.fail("CodexGrader.grade raised: %r" % exc)


class TestCodexGraderJSONExtraction(unittest.TestCase):
    """The tolerant JSON extractor handles clean and prose-wrapped output."""

    def test_clean_json(self):
        out = CodexGrader._extract_json('{"verdict": "verified", "confidence": 0.9, "rationale": "ok"}')
        self.assertEqual(out["verdict"], "verified")

    def test_prose_wrapped_json(self):
        raw = 'Here is the result:\n{"verdict": "contradicted", "confidence": 0.8, "rationale": "opposite"}\nDone.'
        out = CodexGrader._extract_json(raw)
        self.assertEqual(out["verdict"], "contradicted")

    def test_garbage_returns_none(self):
        self.assertIsNone(CodexGrader._extract_json("no json here at all"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
