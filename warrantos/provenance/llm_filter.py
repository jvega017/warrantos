"""provenance.llm_filter: optional LLM-assisted claim filtering (Phase 1b-ME).

The regex layer in provenance.extract (CLAIM_TRIGGERS) achieves high recall
on legal/empirical keywords but fires on everyday prose that shares the same
vocabulary ("the doctor prescribed antibiotics", "we settled the restaurant
bill", "the annual chess congress"). This module adds an opt-in second pass:
each regex-flagged sentence is shown to Claude with the question "is this a
legal/empirical claim that would need fact-checking?" Sentences Claude
rejects are dropped as false positives; anything Claude affirms, is unsure
about, or that fails to reach the API is kept (conservative: never silently
lose a genuine claim).

Routing is controlled by the WARRANTOS_LLM_VERIFY environment variable:

    off   (default) pure regex mode; this module is never consulted and
          behaviour is byte-identical to Phase 1b-QW.
    on    regex flags candidates, then the LLM filters them.
    only  every sentence is sent to the LLM; the regex gate is bypassed
          (research mode; slower and costlier).

Honesty properties:
    * Opt-in only. The default is off and nothing here runs.
    * Graceful degradation. A missing `anthropic` package, missing
      ANTHROPIC_API_KEY, or ANY API failure degrades to keeping the
      sentence, i.e. regex-only behaviour. Never raises.
    * Rate limits and transient 5xx errors are retried by the Anthropic
      SDK's built-in retry policy (default 2 retries with backoff); a
      request that still fails simply keeps the sentence.

Model note: the Phase 1b-ME brief named claude-3-5-sonnet-20241022, but that
model was retired on 2025-10-28 and the API now returns 404 for it. The
documented drop-in replacement at the same tier is claude-sonnet-5, used as
the default here. Override with WARRANTOS_LLM_FILTER_MODEL.

The `anthropic` package is an optional dependency (pip install
"warrantos[llm]"). The core package remains stdlib-only.

Australian English throughout.
"""

import os
from typing import List, Optional, Tuple

try:
    from anthropic import Anthropic

    _HAVE_ANTHROPIC = True
except ImportError:  # pragma: no cover - exercised via monkeypatching in tests
    Anthropic = None  # type: ignore[assignment]
    _HAVE_ANTHROPIC = False

# ---------------------------------------------------------------------------
# Mode routing
# ---------------------------------------------------------------------------

_ENV_MODE = "WARRANTOS_LLM_VERIFY"
_VALID_MODES = ("off", "on", "only")

# claude-3-5-sonnet-20241022 (named in the Phase 1b-ME brief) retired
# 2025-10-28; claude-sonnet-5 is its documented drop-in replacement.
_DEFAULT_MODEL = "claude-sonnet-5"
_ENV_MODEL = "WARRANTOS_LLM_FILTER_MODEL"

# Enough head-room for "yes"/"no" plus the occasional hedge word; answers
# beyond a leading yes/no are treated as "unsure" and kept anyway.
_MAX_TOKENS = 16


def llm_verify_mode() -> str:
    """Return the active routing mode: 'off', 'on', or 'only'.

    Reads WARRANTOS_LLM_VERIFY. Any unrecognised value is treated as 'off'
    so a typo can never silently change verification behaviour to a mode
    the operator did not ask for.
    """
    raw = os.environ.get(_ENV_MODE, "off").strip().lower()
    return raw if raw in _VALID_MODES else "off"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """Given this sentence from a policy document, is it a legal/empirical claim that would need fact-checking? Answer only "yes" or "no".

Sentence: {sentence}

A legal/empirical claim is one that:
- References specific laws, acts, regulations, or legal instruments
- Makes a factual assertion (numbers, dates, attributed statements)
- Describes obligations or requirements

Counter-examples (answer "no"):
- "I found my keys." (everyday, not policy-relevant)
- "The meeting was concluded at noon." (status report, not claim)
- "We surveyed the property." (operational, not evidentiary claim)

Answer:"""


# ---------------------------------------------------------------------------
# Core filter
# ---------------------------------------------------------------------------

def _classify_sentence(client, model: str, sentence: str) -> bool:
    """Ask Claude whether *sentence* is a genuine claim.

    Returns True (keep) unless Claude answers an unambiguous "no".
    An answer that starts with neither "yes" nor "no" counts as unsure
    and the sentence is kept. Any exception also keeps the sentence.
    """
    try:
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": _PROMPT_TEMPLATE.format(sentence=sentence),
                }
            ],
        )
        answer = response.content[0].text.strip().lower()
    except Exception:
        # API error (network, rate-limit after SDK retries, refusal,
        # malformed response): conservatively keep the sentence.
        return True

    if answer.startswith("no"):
        return False
    # "yes" -> genuine claim; anything else -> unsure -> keep.
    return True


def filter_claims_with_llm(
    sentences: List[str],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Tuple[str, bool]]:
    """Classify each sentence: return (sentence, is_genuine_claim) pairs.

    For each sentence, asks Claude: "Is this a legal/empirical claim in a
    policy context?" A "no" marks the sentence False (regex false positive);
    "yes", an ambiguous answer, or any API failure marks it True.

    Parameters
    ----------
    sentences:
        Candidate sentences (normally the regex-flagged subset).
    api_key:
        Anthropic API key. When None, ANTHROPIC_API_KEY is read from the
        environment. When neither is available, no filtering happens and
        every sentence is returned as True.
    model:
        Model identifier. Defaults to WARRANTOS_LLM_FILTER_MODEL, falling
        back to claude-sonnet-5.

    Returns
    -------
    List[Tuple[str, bool]]
        One (sentence, keep) pair per input sentence, in input order.

    Never raises. If the `anthropic` package is not installed, or the key
    is missing, or the client cannot be constructed, every sentence is
    kept (graceful degradation to pure regex behaviour).
    """
    if api_key is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or None

    if not sentences:
        return []

    if not api_key or not _HAVE_ANTHROPIC:
        return [(s, True) for s in sentences]

    if model is None:
        model = os.environ.get(_ENV_MODEL, "") or _DEFAULT_MODEL

    try:
        # The SDK retries rate-limited (429) and transient 5xx responses
        # automatically with exponential backoff (max_retries default 2).
        client = Anthropic(api_key=api_key)
    except Exception:
        return [(s, True) for s in sentences]

    return [(s, _classify_sentence(client, model, s)) for s in sentences]


def filter_sentences(
    sentences: List[str],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> List[str]:
    """Convenience wrapper: return only the sentences the LLM kept."""
    return [
        s for s, keep in filter_claims_with_llm(sentences, api_key=api_key, model=model)
        if keep
    ]
