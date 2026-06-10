#!/usr/bin/env python3
"""Tests for provenance.verify.

All tests are offline and deterministic. urllib is mocked with unittest.mock.
No network access, no sleeps.

Run from the repo root:
    python -m unittest tests.test_verify -v
"""

import socket
import unittest
import unittest.mock
from unittest.mock import MagicMock, patch

from provenance.grade import HeuristicGrader
import provenance.verify as _verify_module
from provenance.verify import (
    extract_citation,
    fetch_text,
    verify_claim,
    verify_text,
)

# A public IP used by tests that need _is_safe_url to pass without real DNS.
_PUBLIC_IP = "93.184.216.34"  # example.com


def _make_getaddrinfo_public(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (_PUBLIC_IP, port or 80))]


class TestFetchText(unittest.TestCase):
    """fetch_text: network errors return None and never raise."""

    def test_returns_none_on_urllib_error(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = fetch_text("https://example.org/data")
        self.assertIsNone(result)

    def test_returns_none_on_generic_exception(self):
        with patch("urllib.request.urlopen", side_effect=Exception("unexpected")):
            result = fetch_text("https://example.org/data")
        self.assertIsNone(result)

    def test_never_raises_on_bad_url(self):
        with patch("urllib.request.urlopen", side_effect=ValueError("bad URL")):
            try:
                result = fetch_text("not-a-url-at-all")
            except Exception as exc:
                self.fail("fetch_text raised an exception: %s" % exc)
            self.assertIsNone(result)

    def test_returns_text_on_plain_response(self):
        """A plain-text HTTP response is returned as a string."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"Hello world plain text content."
        mock_resp.headers.get.return_value = "text/plain"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("socket.getaddrinfo", _make_getaddrinfo_public):
            with patch.object(_verify_module._safe_opener, "open", return_value=mock_resp):
                result = fetch_text("https://example.org/plain")
        self.assertIsNotNone(result)
        self.assertIn("Hello world", result)

    def test_strips_html_tags(self):
        """HTML script and style content is dropped; body text is preserved."""
        html_bytes = (
            b"<html><head><style>body{color:red}</style></head>"
            b"<body><script>alert(1)</script><p>Visible content here.</p></body></html>"
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = html_bytes
        mock_resp.headers.get.return_value = "text/html; charset=utf-8"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("socket.getaddrinfo", _make_getaddrinfo_public):
            with patch.object(_verify_module._safe_opener, "open", return_value=mock_resp):
                result = fetch_text("https://example.org/page")
        self.assertIsNotNone(result)
        self.assertIn("Visible content", result)
        self.assertNotIn("alert", result)
        self.assertNotIn("color:red", result)

    def test_collapses_whitespace(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"Word1   \n\n  Word2\t\tWord3."
        mock_resp.headers.get.return_value = "text/plain"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("socket.getaddrinfo", _make_getaddrinfo_public):
            with patch.object(_verify_module._safe_opener, "open", return_value=mock_resp):
                result = fetch_text("https://example.org/spaced")
        self.assertIsNotNone(result)
        self.assertNotIn("  ", result)  # no double spaces
        self.assertNotIn("\n", result)


class TestExtractCitation(unittest.TestCase):
    """extract_citation: URL takes priority over APA."""

    def test_finds_url(self):
        sent = "Emissions fell 12 per cent (see https://example.org/data)."
        c = extract_citation(sent)
        self.assertIsNotNone(c)
        self.assertIn("https://example.org", c)

    def test_finds_apa_when_no_url(self):
        sent = "Output declined significantly (Smith, 2023)."
        c = extract_citation(sent)
        self.assertIsNotNone(c)
        self.assertIn("Smith, 2023", c)

    def test_url_priority_over_apa(self):
        sent = "See https://example.org/data (Jones, 2022) for more."
        c = extract_citation(sent)
        self.assertIsNotNone(c)
        self.assertIn("https://", c)

    def test_returns_none_when_neither(self):
        sent = "This sentence makes no factual claim at all."
        c = extract_citation(sent)
        self.assertIsNone(c)

    def test_apa_multiword_author(self):
        sent = "Output rose (Vega & Stone, 2025)."
        c = extract_citation(sent)
        self.assertIsNotNone(c)
        self.assertIn("2025", c)

    def test_url_with_path(self):
        sent = "Data available at https://data.qld.gov.au/dataset/budget/2024."
        c = extract_citation(sent)
        self.assertIsNotNone(c)
        self.assertTrue(c.startswith("https://"))


class TestVerifyClaim(unittest.TestCase):
    """verify_claim: URL citation triggers fetch; result varies with source."""

    def test_url_citation_fetches_source_and_verifies(self):
        """A URL citation causes fetch_text to be called; matching tokens -> verified."""
        source = "The fund held 4 billion dollars in 2023 according to Treasury."
        claim = "The fund held 4 billion in 2023."
        url = "https://example.org/treasury-report"

        with patch("provenance.verify.fetch_text", return_value=source) as mock_fetch:
            grader = HeuristicGrader()
            v = verify_claim(claim, url, grader=grader)
            mock_fetch.assert_called_once_with(url)

        self.assertEqual(v.verdict, "verified")

    def test_url_citation_fetch_returns_non_matching_source(self):
        """Fetched source that does not match tokens -> not_addressed."""
        source = "This page contains governance frameworks and audit procedures."
        claim = "Revenue rose 15 per cent in 2022."
        url = "https://example.org/governance"

        with patch("provenance.verify.fetch_text", return_value=source):
            grader = HeuristicGrader()
            v = verify_claim(claim, url, grader=grader)

        self.assertEqual(v.verdict, "not_addressed")

    def test_apa_citation_does_not_fetch(self):
        """An APA citation (non-URL) should not cause a network call."""
        claim = "Output fell 3 per cent (Jones, 2023)."
        with patch("provenance.verify.fetch_text") as mock_fetch:
            grader = HeuristicGrader()
            v = verify_claim(claim, "(Jones, 2023)", grader=grader)
            mock_fetch.assert_not_called()
        self.assertEqual(v.verdict, "unverifiable")

    def test_none_citation_yields_skipped(self):
        claim = "The programme ran for 5 per cent longer."
        grader = HeuristicGrader()
        v = verify_claim(claim, None, grader=grader)
        self.assertEqual(v.verdict, "skipped")

    def test_uses_get_grader_when_none_passed(self):
        """When grader=None, get_grader() is called automatically."""
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with patch("provenance.verify.fetch_text", return_value=None):
                v = verify_claim("Output rose 5 per cent.", None, grader=None)
        self.assertIsInstance(v.verdict, str)


class TestVerifyText(unittest.TestCase):
    """verify_text: processes all claim sentences; fetch=False suppresses network."""

    def test_fetch_false_does_not_call_network(self):
        """With fetch=False, fetch_text must never be called."""
        text = (
            "Emissions fell 12 per cent in 2021 (https://example.org/data). "
            "The 2023 review concluded the model underperformed."
        )
        grader = HeuristicGrader()

        def _fail_if_called(url):
            raise AssertionError("fetch_text called with fetch=False: url=%s" % url)

        with patch("provenance.verify.fetch_text", side_effect=_fail_if_called):
            verdicts = verify_text(text, grader=grader, fetch=False)

        self.assertIsInstance(verdicts, list)
        self.assertGreater(len(verdicts), 0)
        # All verdicts should be heuristic-based (no source text).
        for v in verdicts:
            self.assertIn("heuristic", v.grader)

    def test_returns_verdicts_for_all_claim_sentences(self):
        text = (
            "The budget rose 7 per cent. "
            "This is a normal sentence with no claim. "
            "Revenue reached 2 billion in 2022."
        )
        grader = HeuristicGrader()
        verdicts = verify_text(text, grader=grader, fetch=False)
        # Expect 2 claim sentences (percentage and magnitude/year).
        self.assertGreaterEqual(len(verdicts), 2)

    def test_non_claim_sentences_excluded(self):
        text = "This is a plain sentence. Another plain one here."
        grader = HeuristicGrader()
        verdicts = verify_text(text, grader=grader, fetch=False)
        self.assertEqual(len(verdicts), 0)

    def test_fetch_true_calls_fetch_for_url_citations(self):
        """With fetch=True and a URL in the claim, fetch_text is called."""
        text = "Emissions fell 12 per cent (https://example.org/data)."
        grader = HeuristicGrader()

        with patch("provenance.verify.fetch_text", return_value="emissions fell 12 per cent") as mock_fetch:
            verdicts = verify_text(text, grader=grader, fetch=True)
            mock_fetch.assert_called()

        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].verdict, "verified")

    def test_returns_list_of_verdict_instances(self):
        from provenance.grade import Verdict
        text = "The 2021 review found that output rose 5 per cent."
        grader = HeuristicGrader()
        verdicts = verify_text(text, grader=grader, fetch=False)
        for v in verdicts:
            self.assertIsInstance(v, Verdict)

    def test_uses_get_grader_when_none_passed(self):
        import os
        text = "Spending rose 6 per cent in 2023."
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            verdicts = verify_text(text, grader=None, fetch=False)
        self.assertIsInstance(verdicts, list)
        self.assertGreater(len(verdicts), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
