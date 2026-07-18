"""Tests for provenance.llm_filter (Phase 1b-ME LLM-assisted claim filtering).

Three tiers:

1. Offline unit tests (always run): mode parsing, graceful degradation
   without an API key or without the optional `anthropic` package.
2. Mocked-client tests (always run): a stub Anthropic client exercises the
   yes/no/unsure/error answer handling and the WARRANTOS_LLM_VERIFY routing
   through verify_text, detect_claims, and sentences_with_llm_filter without
   any network access.
3. Live tests (run only when ANTHROPIC_API_KEY is set AND the `anthropic`
   package is installed): the false-positive/genuine-claim acceptance
   criteria from the Phase 1b-ME brief.

Standard library unittest only.
"""

import os
import unittest
from unittest import mock

from warrantos.provenance import llm_filter
from warrantos.provenance.extract import sentences_with_llm_filter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    """Answers 'no' for sentences in reject_set, 'yes' otherwise.

    Sentences in error_set raise; sentences in unsure_set answer with
    text that starts with neither yes nor no.
    """

    def __init__(self, reject_set=(), error_set=(), unsure_set=()):
        self.reject_set = set(reject_set)
        self.error_set = set(error_set)
        self.unsure_set = set(unsure_set)
        self.calls = []

    def create(self, model, max_tokens, messages):
        prompt = messages[0]["content"]
        self.calls.append(prompt)
        for sent in self.error_set:
            if sent in prompt:
                raise RuntimeError("simulated API failure")
        for sent in self.unsure_set:
            if sent in prompt:
                return _FakeResponse("I am not certain about this one.")
        for sent in self.reject_set:
            if sent in prompt:
                return _FakeResponse("No")
        return _FakeResponse("Yes")


def _fake_client_factory(messages_obj):
    class _FakeAnthropic:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.messages = messages_obj

    return _FakeAnthropic


def _patched_llm(messages_obj):
    """Patch llm_filter so filter_claims_with_llm uses the fake client."""
    return mock.patch.multiple(
        llm_filter,
        Anthropic=_fake_client_factory(messages_obj),
        _HAVE_ANTHROPIC=True,
    )


FALSE_POSITIVES = [
    "I found my keys under the couch.",
    "The doctor prescribed antibiotics.",
    "We settled the restaurant bill.",
    "The annual chess congress drew a crowd.",
]

GENUINE_CLAIMS = [
    "Pursuant to section 5 of the Act, the regulation was gazetted.",
    "The 2020 survey found that compliance rose by 34 percent.",
    "The minister's mandate requires annual reporting.",
]

_HAVE_LIVE = bool(os.environ.get("ANTHROPIC_API_KEY")) and llm_filter._HAVE_ANTHROPIC


# ---------------------------------------------------------------------------
# Mode parsing
# ---------------------------------------------------------------------------

class TestModeParsing(unittest.TestCase):
    def _mode_with_env(self, value):
        env = {k: v for k, v in os.environ.items() if k != "WARRANTOS_LLM_VERIFY"}
        if value is not None:
            env["WARRANTOS_LLM_VERIFY"] = value
        with mock.patch.dict(os.environ, env, clear=True):
            return llm_filter.llm_verify_mode()

    def test_default_is_off(self):
        self.assertEqual(self._mode_with_env(None), "off")

    def test_on_and_only_recognised(self):
        self.assertEqual(self._mode_with_env("on"), "on")
        self.assertEqual(self._mode_with_env("only"), "only")
        self.assertEqual(self._mode_with_env("OFF"), "off")
        self.assertEqual(self._mode_with_env(" On "), "on")

    def test_unrecognised_value_is_off(self):
        self.assertEqual(self._mode_with_env("yes"), "off")
        self.assertEqual(self._mode_with_env("1"), "off")
        self.assertEqual(self._mode_with_env(""), "off")


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation(unittest.TestCase):
    def test_graceful_degradation_without_api_key(self):
        """Without API key, should return all True (no filtering)."""
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            results = llm_filter.filter_claims_with_llm(["any sentence"])
            self.assertEqual(results, [("any sentence", True)])
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    def test_graceful_degradation_without_sdk(self):
        """Without the anthropic package, everything is kept even with a key."""
        with mock.patch.object(llm_filter, "_HAVE_ANTHROPIC", False):
            results = llm_filter.filter_claims_with_llm(
                FALSE_POSITIVES, api_key="sk-test-not-a-real-key"
            )
        self.assertEqual(results, [(s, True) for s in FALSE_POSITIVES])

    def test_empty_input(self):
        self.assertEqual(llm_filter.filter_claims_with_llm([]), [])

    def test_client_construction_failure_keeps_all(self):
        class _Boom:
            def __init__(self, api_key=None):
                raise RuntimeError("cannot build client")

        with mock.patch.multiple(llm_filter, Anthropic=_Boom, _HAVE_ANTHROPIC=True):
            results = llm_filter.filter_claims_with_llm(["s1", "s2"], api_key="k")
        self.assertEqual(results, [("s1", True), ("s2", True)])


# ---------------------------------------------------------------------------
# Mocked-client answer handling
# ---------------------------------------------------------------------------

class TestMockedFiltering(unittest.TestCase):
    def test_no_answer_rejects_sentence(self):
        fake = _FakeMessages(reject_set={"The doctor prescribed antibiotics."})
        with _patched_llm(fake):
            results = llm_filter.filter_claims_with_llm(
                ["The doctor prescribed antibiotics.", "The Act was amended in 2020."],
                api_key="k",
            )
        self.assertEqual(
            results,
            [
                ("The doctor prescribed antibiotics.", False),
                ("The Act was amended in 2020.", True),
            ],
        )

    def test_unsure_answer_keeps_sentence(self):
        fake = _FakeMessages(unsure_set={"Ambiguous sentence."})
        with _patched_llm(fake):
            results = llm_filter.filter_claims_with_llm(["Ambiguous sentence."], api_key="k")
        self.assertEqual(results, [("Ambiguous sentence.", True)])

    def test_api_error_keeps_sentence(self):
        fake = _FakeMessages(error_set={"Erroring sentence."})
        with _patched_llm(fake):
            results = llm_filter.filter_claims_with_llm(["Erroring sentence."], api_key="k")
        self.assertEqual(results, [("Erroring sentence.", True)])

    def test_filter_sentences_drops_rejected(self):
        fake = _FakeMessages(reject_set={"We settled the restaurant bill."})
        with _patched_llm(fake):
            kept = llm_filter.filter_sentences(
                ["We settled the restaurant bill.", "Compliance rose by 34 percent."],
                api_key="k",
            )
        self.assertEqual(kept, ["Compliance rose by 34 percent."])


# ---------------------------------------------------------------------------
# Routing: verify_text / detect_claims / sentences_with_llm_filter
# ---------------------------------------------------------------------------

class TestRouting(unittest.TestCase):
    TEXT = (
        "The doctor prescribed antibiotics. "
        "The 2020 survey found that compliance rose by 34 percent. "
        "It was a nice day."
    )

    def test_verify_text_off_mode_is_regex_only(self):
        from warrantos.provenance.verify import verify_text

        env = dict(os.environ)
        env["WARRANTOS_LLM_VERIFY"] = "off"
        with mock.patch.dict(os.environ, env, clear=True):
            verdicts = verify_text(self.TEXT, fetch=False)
        texts = [v.claim_text for v in verdicts]
        # Regex flags both the false positive (prescribed) and the genuine claim.
        self.assertIn("The doctor prescribed antibiotics.", texts)
        self.assertIn(
            "The 2020 survey found that compliance rose by 34 percent.", texts
        )

    def test_verify_text_on_mode_filters_false_positive(self):
        from warrantos.provenance.verify import verify_text

        fake = _FakeMessages(reject_set={"The doctor prescribed antibiotics."})
        env = dict(os.environ)
        env["WARRANTOS_LLM_VERIFY"] = "on"
        env["ANTHROPIC_API_KEY"] = "sk-test-not-a-real-key"
        with mock.patch.dict(os.environ, env, clear=True), _patched_llm(fake):
            verdicts = verify_text(self.TEXT, fetch=False)
        texts = [v.claim_text for v in verdicts]
        self.assertNotIn("The doctor prescribed antibiotics.", texts)
        self.assertIn(
            "The 2020 survey found that compliance rose by 34 percent.", texts
        )
        # "It was a nice day." never reached the LLM: regex gate excluded it.
        self.assertTrue(all("nice day" not in c for c in fake.calls))

    def test_verify_text_only_mode_bypasses_regex_gate(self):
        from warrantos.provenance.verify import verify_text

        fake = _FakeMessages(reject_set={"It was a nice day."})
        env = dict(os.environ)
        env["WARRANTOS_LLM_VERIFY"] = "only"
        env["ANTHROPIC_API_KEY"] = "sk-test-not-a-real-key"
        with mock.patch.dict(os.environ, env, clear=True), _patched_llm(fake):
            verdicts = verify_text(self.TEXT, fetch=False)
        texts = [v.claim_text for v in verdicts]
        # All sentences were put to the LLM; only the rejected one dropped.
        self.assertIn("The doctor prescribed antibiotics.", texts)
        self.assertNotIn("It was a nice day.", texts)
        self.assertTrue(any("nice day" in c for c in fake.calls))

    def test_detect_claims_on_mode_filters_false_positive(self):
        from warrantos.cli.warrantos_cli import detect_claims

        fake = _FakeMessages(reject_set={"The doctor prescribed antibiotics."})
        env = dict(os.environ)
        env["WARRANTOS_LLM_VERIFY"] = "on"
        env["ANTHROPIC_API_KEY"] = "sk-test-not-a-real-key"
        with mock.patch.dict(os.environ, env, clear=True), _patched_llm(fake):
            rows = detect_claims(self.TEXT)
        sents = [r["sentence"] for r in rows]
        self.assertNotIn("The doctor prescribed antibiotics.", sents)
        self.assertIn(
            "The 2020 survey found that compliance rose by 34 percent.", sents
        )

    def test_detect_claims_only_mode_marks_llm_trigger(self):
        from warrantos.cli.warrantos_cli import detect_claims

        fake = _FakeMessages()  # keeps everything
        env = dict(os.environ)
        env["WARRANTOS_LLM_VERIFY"] = "only"
        env["ANTHROPIC_API_KEY"] = "sk-test-not-a-real-key"
        with mock.patch.dict(os.environ, env, clear=True), _patched_llm(fake):
            rows = detect_claims(self.TEXT)
        by_sentence = {r["sentence"]: r for r in rows}
        self.assertIn("It was a nice day.", by_sentence)
        self.assertEqual(by_sentence["It was a nice day."]["triggers"], ["llm"])

    def test_detect_claims_off_mode_unchanged(self):
        from warrantos.cli.warrantos_cli import detect_claims

        env = dict(os.environ)
        env["WARRANTOS_LLM_VERIFY"] = "off"
        with mock.patch.dict(os.environ, env, clear=True):
            rows = detect_claims(self.TEXT)
        sents = [r["sentence"] for r in rows]
        self.assertIn("The doctor prescribed antibiotics.", sents)
        self.assertNotIn("It was a nice day.", sents)

    def test_sentences_with_llm_filter_off_matches_sentences(self):
        from warrantos.provenance.extract import sentences

        env = dict(os.environ)
        env["WARRANTOS_LLM_VERIFY"] = "off"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                sentences_with_llm_filter(self.TEXT), sentences(self.TEXT)
            )

    def test_sentences_with_llm_filter_explicit_true(self):
        fake = _FakeMessages(reject_set={"It was a nice day."})
        env = dict(os.environ)
        env["ANTHROPIC_API_KEY"] = "sk-test-not-a-real-key"
        with mock.patch.dict(os.environ, env, clear=True), _patched_llm(fake):
            kept = sentences_with_llm_filter(self.TEXT, use_llm=True)
        self.assertNotIn("It was a nice day.", kept)
        self.assertIn("The doctor prescribed antibiotics.", kept)


# ---------------------------------------------------------------------------
# Live tests (need ANTHROPIC_API_KEY + anthropic package)
# ---------------------------------------------------------------------------

@unittest.skipUnless(
    _HAVE_LIVE, "live LLM tests need ANTHROPIC_API_KEY and the anthropic package"
)
class TestLiveLLMFilter(unittest.TestCase):
    def test_filter_rejects_everyday_false_positives(self):
        """LLM should reject common-word false positives."""
        results = llm_filter.filter_claims_with_llm(FALSE_POSITIVES)
        rejected = sum(1 for _, keep in results if not keep)
        # Target: <10% FP on everyday prose. Require all four rejected.
        self.assertEqual(
            rejected,
            len(FALSE_POSITIVES),
            "expected all everyday-prose sentences rejected, got %r" % (results,),
        )

    def test_filter_accepts_legal_claims(self):
        """LLM should accept genuine legal/empirical claims (recall >= 90%)."""
        results = llm_filter.filter_claims_with_llm(GENUINE_CLAIMS)
        self.assertTrue(
            all(keep for _, keep in results),
            "expected all genuine claims kept, got %r" % (results,),
        )


if __name__ == "__main__":
    unittest.main()
