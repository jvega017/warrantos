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
    ClaudeCliGrader,
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


class TestHeuristicGraderNumericContradiction(unittest.TestCase):
    """The narrow, anchored same-kind numeric-contradiction check added to
    HeuristicGrader: it may fire on a genuine year/percentage/number
    mismatch, but must never fire on formatting variants, omissions, or
    unrelated low-overlap sentences that merely happen to share a number
    of the same kind."""

    def setUp(self):
        self.grader = HeuristicGrader()

    def test_year_mismatch_is_contradicted(self):
        claim = "The register shows the programme launched in 2021 following cabinet approval."
        source = (
            "The register shows the programme launched in 2022 following "
            "cabinet approval, a year late."
        )
        v = self.grader.grade(claim, source, None)
        self.assertEqual(v.verdict, "contradicted")
        self.assertEqual(v.grader, "fetch+heuristic")
        self.assertIn("2021", v.rationale)
        self.assertIn("2022", v.rationale)
        self.assertLessEqual(len(v.rationale), 200)

    def test_percentage_mismatch_is_contradicted(self):
        claim = "Customer satisfaction reached 40 per cent according to the annual survey."
        source = (
            "Customer satisfaction reached 25 per cent according to the "
            "annual survey, a sharp decline."
        )
        v = self.grader.grade(claim, source, None)
        self.assertEqual(v.verdict, "contradicted")
        self.assertIsNotNone(v.confidence)
        self.assertIn("25", v.rationale)
        self.assertIn("40", v.rationale)

    def test_plain_number_mismatch_is_contradicted(self):
        # Mirrors the "enrolled 12,000" vs "enrolled 1,200" shape: the
        # claim's number also reappears elsewhere in the source (as the
        # unmet projection), so a naive "is this substring anywhere in the
        # source" check would wrongly call it verified.
        claim = "The pilot enrolled 12,000 participants by 2021."
        source = (
            "The pilot enrolled only 1,200 participants by 2021, far short "
            "of the 12,000 originally projected."
        )
        v = self.grader.grade(claim, source, None)
        self.assertEqual(v.verdict, "contradicted")

    def test_percent_format_variants_not_flagged(self):
        # "40%" vs "40 per cent" must normalise to the same value.
        claim = "Efficiency improved by 40% following the upgrade, auditors reported."
        source = (
            "Efficiency improved by 40 per cent following the upgrade, "
            "according to auditors."
        )
        v = self.grader.grade(claim, source, None)
        self.assertNotEqual(v.verdict, "contradicted")

    def test_magnitude_format_variants_not_flagged(self):
        # "2 million" vs "2,000,000" must normalise to the same value.
        claim = "The scheme paid out 2 million dollars during the trial, records show."
        source = "The scheme paid out 2,000,000 dollars during the trial, records confirm."
        v = self.grader.grade(claim, source, None)
        self.assertNotEqual(v.verdict, "contradicted")

    def test_source_with_no_numbers_leaves_verdict_unchanged(self):
        claim = "Revenue reached 4 billion dollars in 2023."
        source = "The policy document discusses governance frameworks and accountability."
        v = self.grader.grade(claim, source, None)
        # Same outcome as before the numeric-contradiction check existed:
        # no numeric mention in the source means nothing to compare, so
        # this falls through to the existing not_addressed path.
        self.assertEqual(v.verdict, "not_addressed")

    def test_low_overlap_sentences_with_different_numbers_not_flagged(self):
        # A same-kind mismatch exists (40% vs 25%) anchored near a shared
        # word ("growth"), but the rest of the sentence shares almost no
        # content words, so the overlap gate must block the contradiction.
        claim = "The report highlighted 40 per cent growth in exports during the review."
        source = (
            "A completely unrelated document discusses zoo animal "
            "populations and shows 25 per cent growth in visitor numbers."
        )
        v = self.grader.grade(claim, source, None)
        self.assertNotEqual(v.verdict, "contradicted")


class TestHeuristicGraderDirectionContradiction(unittest.TestCase):
    """The narrow, anchored directional-antonym contradiction check added
    to HeuristicGrader: it may fire when a number the source confirms
    verbatim sits next to a directional word in the claim (e.g. "fell")
    and an opposite-polarity directional word in the source (e.g. "rose"),
    but must never fire on matching directions, unrelated metrics, or a
    negated directional word."""

    def setUp(self):
        self.grader = HeuristicGrader()

    def test_fell_rose_same_number_is_contradicted(self):
        claim = "Processing times fell by 18 per cent after the 2021 reform."
        source = (
            "Processing times rose by 18 per cent after the 2021 reform, "
            "according to the performance dashboard."
        )
        v = self.grader.grade(claim, source, None)
        self.assertEqual(v.verdict, "contradicted")
        self.assertEqual(v.grader, "fetch+heuristic")
        self.assertIn("fell", v.rationale)
        self.assertIn("rose", v.rationale)
        self.assertLessEqual(len(v.rationale), 200)

    def test_grew_shrank_same_number_is_contradicted(self):
        claim = "Regional offices grew to 40 branches by 2022."
        source = "Regional offices shrank to 40 branches by 2022, the annual report shows."
        v = self.grader.grade(claim, source, None)
        self.assertEqual(v.verdict, "contradicted")

    def test_same_direction_same_number_not_contradicted(self):
        # Both sides say "rose" -- no antonym conflict, must not fire.
        claim = "Citizen satisfaction rose to 78 per cent in 2022."
        source = "The 2022 customer survey found citizen satisfaction rose to 78 per cent."
        v = self.grader.grade(claim, source, None)
        self.assertNotEqual(v.verdict, "contradicted")

    def test_antonym_present_but_different_metric_not_flagged(self):
        # The source contains an antonym of the claim's direction word, but
        # attached to a different, unrelated number/subject -- the overlap
        # gate (and the requirement that the antonym sit near the SAME
        # matched number) must block this.
        claim = "Broadband coverage rose to 95 per cent of households by 2022."
        source = (
            "A separate unrelated survey found smartphone ownership fell to "
            "30 per cent among older residents in 2019."
        )
        v = self.grader.grade(claim, source, None)
        self.assertNotEqual(v.verdict, "contradicted")

    def test_negated_direction_word_not_flagged(self):
        # "did not rise" -- negation near the source's directional word
        # means it cannot be trusted as a confirmed opposite direction.
        claim = "Compliance rates rose to 92 per cent in 2022."
        source = (
            "Compliance rates did not rise to 92 per cent in 2022; "
            "the figure was never reached, auditors noted."
        )
        v = self.grader.grade(claim, source, None)
        self.assertNotEqual(v.verdict, "contradicted")

    def test_both_polarities_present_near_anchor_not_flagged(self):
        # Source mentions both "fell" and a higher figure near the same
        # anchor -- ambiguous, so the check must stay silent rather than
        # guess which direction word is the "real" one.
        claim = "AI spending rose to 700 million dollars in 2023."
        source = (
            "AI spending fell to 700 million dollars in 2023, down from a "
            "higher figure the prior year."
        )
        v = self.grader.grade(claim, source, None)
        self.assertNotEqual(v.verdict, "contradicted")

    def test_low_overlap_with_opposite_direction_not_flagged(self):
        # Same number and opposite direction word, but almost no other
        # content words in common -- the overlap gate must block this.
        claim = "The department reported that survey completions rose to 60 per cent in 2021."
        source = (
            "A completely unrelated council newsletter mentions that pothole "
            "complaints fell to 60 per cent in 2021 after roadworks began."
        )
        v = self.grader.grade(claim, source, None)
        self.assertNotEqual(v.verdict, "contradicted")


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

    def _clear_selectors(self):
        """Remove every env var that get_grader() inspects so tests run
        deterministically regardless of the host's installed tooling."""
        for var in (
            "ANTHROPIC_API_KEY",
            "PROVENANCE_LOCAL_GRADER_URL",
            "PROVENANCE_GRADER",
        ):
            os.environ.pop(var, None)

    def test_returns_heuristic_when_no_key(self):
        # Force claude unavailable so this isolates the no-key path.
        with patch.dict(os.environ, {}, clear=False):
            self._clear_selectors()
            with patch.object(ClaudeCliGrader, "is_available", return_value=False):
                grader = get_grader()
        self.assertIsInstance(grader, HeuristicGrader)

    def test_returns_llm_when_key_present(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            os.environ.pop("PROVENANCE_GRADER", None)
            grader = get_grader()
        self.assertIsInstance(grader, LLMGrader)

    def test_returns_heuristic_when_key_empty_string(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self._clear_selectors()
            os.environ["ANTHROPIC_API_KEY"] = ""
            with patch.object(ClaudeCliGrader, "is_available", return_value=False):
                grader = get_grader()
        self.assertIsInstance(grader, HeuristicGrader)

    def test_returns_claude_cli_when_available_and_no_key(self):
        """Subscription-over-API: with no key/local URL but claude on PATH,
        get_grader() auto-selects ClaudeCliGrader."""
        with patch.dict(os.environ, {}, clear=False):
            self._clear_selectors()
            with patch.object(ClaudeCliGrader, "is_available", return_value=True):
                grader = get_grader()
        self.assertIsInstance(grader, ClaudeCliGrader)

    def test_api_key_wins_over_claude_cli(self):
        """An explicit ANTHROPIC_API_KEY is honoured before the CLI."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            os.environ.pop("PROVENANCE_GRADER", None)
            with patch.object(ClaudeCliGrader, "is_available", return_value=True):
                grader = get_grader()
        self.assertIsInstance(grader, LLMGrader)

    def test_provenance_grader_override_selects_claude(self):
        with patch.dict(os.environ, {"PROVENANCE_GRADER": "claude"}):
            grader = get_grader()
        self.assertIsInstance(grader, ClaudeCliGrader)

    def test_provenance_grader_override_selects_heuristic_over_key(self):
        """The explicit override beats auto-selection even when a key is set."""
        with patch.dict(os.environ, {
            "PROVENANCE_GRADER": "heuristic",
            "ANTHROPIC_API_KEY": "test-key",
        }):
            grader = get_grader()
        self.assertIsInstance(grader, HeuristicGrader)

    def test_provenance_grader_override_selects_codex(self):
        with patch.dict(os.environ, {"PROVENANCE_GRADER": "codex"}):
            grader = get_grader()
        self.assertIsInstance(grader, CodexGrader)

    def test_unknown_override_falls_through_to_auto(self):
        with patch.dict(os.environ, {"PROVENANCE_GRADER": "not-a-grader"}):
            self._clear_selectors()
            os.environ["PROVENANCE_GRADER"] = "not-a-grader"
            with patch.object(ClaudeCliGrader, "is_available", return_value=False):
                grader = get_grader()
        self.assertIsInstance(grader, HeuristicGrader)


class TestClaudeCliGraderNoSource(unittest.TestCase):
    """No-source paths spawn no subprocess and fall back to heuristic
    verdicts via the HeuristicGrader, matching the no-source contract."""

    def setUp(self):
        self.g = ClaudeCliGrader()

    def test_citation_without_source_is_unverifiable(self):
        # claude binary missing forces the heuristic fallback path.
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude_not_real_zzz"}):
            v = self.g.grade("A claim.", None, "https://example.gov.au/x")
        self.assertEqual(v.verdict, "unverifiable")
        self.assertIn("heuristic", v.grader)

    def test_no_citation_no_source_is_skipped(self):
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude_not_real_zzz"}):
            v = self.g.grade("A claim.", None, None)
        self.assertEqual(v.verdict, "skipped")
        self.assertIn("heuristic", v.grader)


class TestClaudeCliGraderSubprocess(unittest.TestCase):
    """ClaudeCliGrader shells out to `claude --print`; the subprocess is
    fully mocked. No real CLI invocation occurs."""

    def _proc(self, returncode=0, stdout="", stderr=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_successful_call_parses_verdict(self):
        import json as _json
        payload = _json.dumps({
            "verdict": "contradicted",
            "confidence": 0.82,
            "rationale": "Source states the opposite.",
        })
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", return_value=self._proc(0, payload)):
                v = ClaudeCliGrader().grade(
                    "Spending rose 10 per cent in 2022.",
                    "Spending fell 10 per cent in 2022.",
                    None,
                )
        self.assertEqual(v.verdict, "contradicted")
        self.assertAlmostEqual(v.confidence, 0.82)
        self.assertEqual(v.grader, "fetch+claude-cli")

    def test_label_without_source(self):
        import json as _json
        payload = _json.dumps({
            "verdict": "unverifiable", "confidence": None, "rationale": "no source",
        })
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", return_value=self._proc(0, payload)):
                v = ClaudeCliGrader().grade("A claim.", "source text", "cite")
        # source_text present -> fetch+claude-cli label.
        self.assertEqual(v.grader, "fetch+claude-cli")

    def test_prose_wrapped_json_is_extracted(self):
        raw = 'Sure:\n{"verdict": "verified", "confidence": 0.9, "rationale": "ok"}\nDone.'
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", return_value=self._proc(0, raw)):
                v = ClaudeCliGrader().grade("c", "s", None)
        self.assertEqual(v.verdict, "verified")

    def test_nonzero_exit_falls_back_to_heuristic(self):
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", return_value=self._proc(1, "", "boom")):
                v = ClaudeCliGrader().grade(
                    "Output rose 5 per cent.", "Output rose 5 per cent.", None,
                )
        self.assertEqual(v.verdict, "verified")  # heuristic match
        self.assertIn("heuristic", v.grader)

    def test_empty_stdout_falls_back_to_heuristic(self):
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", return_value=self._proc(0, "   ")):
                v = ClaudeCliGrader().grade("c", "unrelated source", None)
        self.assertIn("heuristic", v.grader)

    def test_garbage_output_falls_back_to_heuristic(self):
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", return_value=self._proc(0, "no json here")):
                v = ClaudeCliGrader().grade("c", "unrelated source", None)
        self.assertIn("heuristic", v.grader)

    def test_missing_binary_falls_back_and_never_raises(self):
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", side_effect=FileNotFoundError("nope")):
                try:
                    v = ClaudeCliGrader().grade("c", "s", None)
                except Exception as exc:  # pragma: no cover
                    self.fail("ClaudeCliGrader raised: %r" % exc)
        self.assertIn("heuristic", v.grader)

    def test_timeout_falls_back_and_never_raises(self):
        import subprocess
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 1)):
                try:
                    v = ClaudeCliGrader().grade("c", "s", None)
                except Exception as exc:  # pragma: no cover
                    self.fail("ClaudeCliGrader raised on timeout: %r" % exc)
        self.assertIn("heuristic", v.grader)

    def test_invalid_verdict_label_coerced_to_error(self):
        import json as _json
        payload = _json.dumps({
            "verdict": "definitely_true", "confidence": 0.5, "rationale": "x",
        })
        with patch.dict(os.environ, {"PROVENANCE_CLAUDE_BIN": "claude"}):
            with patch("subprocess.run", return_value=self._proc(0, payload)):
                v = ClaudeCliGrader().grade("c", "s", None)
        self.assertEqual(v.verdict, "error")


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
