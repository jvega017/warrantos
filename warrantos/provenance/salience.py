"""provenance.salience: out-of-band claim-consequence weighting.

Assigns a salience score (0.0 to 1.0) to each claim sentence based on
transparent heuristic rules. The hook (hooks/provenance_check.py) remains
a dumb tripwire that fires on syntactic triggers; salience is applied here
when reading the ledger to distinguish load-bearing claims from incidental
ones.

LOAD-BEARING THRESHOLD: 0.5
A claim is considered load-bearing when score_claim() >= 0.5. This threshold
was chosen to include statute/section references, large-magnitude numbers,
and decision-language sentences while excluding bare year mentions and purely
descriptive sentences that happen to contain a number.

Scoring heuristics (additive, capped at 1.0):
  +0.55  statute/section reference (s. N, section N, Act YYYY)
          Statute references alone exceed the 0.5 load-bearing threshold.
  +0.55  decision/recommendation language (recommend, must, should, will reduce,
          will increase, projected, forecast, save, cost as a verb, require)
          Decision language alone exceeds the 0.5 load-bearing threshold.
  +0.55  magnitude reference (million, billion, trillion, $N, bn, tn)
          Magnitude claims alone exceed the 0.5 load-bearing threshold.
  +0.30  causal language (caused, led to, results in, due to, driven by)
  +0.30  empirical comparison (compared to, twice as, increase of, higher than)
  +0.30  named-body attribution (OECD, ABS, Treasury, ANAO and similar)
          These three fall below the 0.5 threshold alone but push a claim
          load-bearing in combination with magnitude, percentage or each other.
  +0.15  percentage in a non-hedged context
  +0.10  year in a non-trivial sentence (penalised if hedged or descriptive)
  -0.20  hedging language (may, might, could, perhaps, possibly, unclear,
          uncertain, approximately, around, estimated at)
  -0.15  purely descriptive attribution without consequential language
          (e.g., "according to the review, the model was rated ...")

No ML, no third-party libraries. Python 3.8 compatible. Stdlib only.
Australian English throughout.
"""

import re
from typing import Optional

from .config import MAX_SENTENCE_CHARS

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Statute/section references — high salience; these are binding obligations.
_STATUTE = re.compile(
    r"\b(?:s\.?\s?\d+|section\s+\d+|Act\s+(?:18|19|20)\d{2})\b",
    re.I,
)

# Decision and recommendation language — signals load-bearing assertions.
_DECISION = re.compile(
    r"\b(?:recommend|recommends|recommended|must|should|shall|will\s+reduce|will\s+increase|"
    r"will\s+save|will\s+cost|projected|forecast|forecasts|forecasted|"
    r"require|requires|required)\b",
    re.I,
)

# Magnitude — large numbers that matter to policy or financial analysis.
_MAGNITUDE = re.compile(
    r"\b\d[\d,]*(?:\.\d+)?\s?(?:million|billion|trillion|bn|tn)\b"
    r"|\$\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|trillion|bn|tn))?\b",
    re.I,
)

# Percentage in sentence (plain numeric).
_PERCENTAGE = re.compile(
    r"\b\d+(?:\.\d+)?\s?%|\bper\s?cent\b|\bpercent\b",
    re.I,
)

# Year token (bare four-digit year).
_YEAR = re.compile(r"\b(?:18|19|20)\d{2}\b")

# Hedging language — reduces confidence in salience.
_HEDGE = re.compile(
    r"\b(?:may|might|could|perhaps|possibly|unclear|uncertain|"
    r"approximately|around|estimated\s+at|roughly|about)\b",
    re.I,
)

# Purely descriptive attribution without consequence.
# Matches patterns like "according to X, Y was rated..." where no consequential
# verb follows in close proximity.
_DESCRIPTIVE_ATTRIBUTION = re.compile(
    r"\b(?:according\s+to|found\s+that|reported\s+that|shows?\s+that|"
    r"study\s+found|survey\s+found|data\s+show)\b",
    re.I,
)

# Causal language — asserting a cause-effect relationship is consequential and
# load-bearing when unsupported. Weight +0.30 (Phase 1 item 4).
_CAUSAL = re.compile(
    r"\b(?:caused|causes|causing|led\s+to|leads?\s+to|results?\s+in|"
    r"resulted\s+in|due\s+to|as\s+a\s+result\s+of|because\s+of|"
    r"driven\s+by|attributable\s+to)\b",
    re.I,
)

# Empirical comparison — quantified comparative claims. Weight +0.30.
_COMPARISON = re.compile(
    r"\b(?:compared\s+(?:to|with)|relative\s+to|twice\s+as|half\s+as|"
    r"\d+\s+times\s+(?:more|less|higher|lower)|increase\s+of|decrease\s+of|"
    r"outperform(?:s|ed)?|higher\s+than|lower\s+than)\b",
    re.I,
)

# Named-body attribution (OECD, ABS, Treasury, ANAO and similar). A claim
# attributed to a named authoritative body carries reputational weight and is
# load-bearing when uncited. Weight +0.30.
_BODY_ATTRIBUTION = re.compile(
    r"\b(?:OECD|ABS|Treasury|ANAO|APSC|DTA|Productivity\s+Commission|"
    r"World\s+Bank|IMF|United\s+Nations|UN|Reserve\s+Bank|RBA|"
    r"Bureau\s+of\s+Statistics)\b"
)


def score_claim(sentence: str, trigger: Optional[str] = None) -> float:
    """Return a salience score between 0.0 and 1.0 for *sentence*.

    Higher scores indicate load-bearing assertions that are more likely to
    matter if wrong: statute references, magnitude claims, and sentences
    containing decision or recommendation language score above 0.5 by default.

    Lower scores arise from bare year mentions in descriptive sentences,
    hedged assertions, or purely attributive sentences with no consequential
    language.

    Parameters
    ----------
    sentence:
        The claim sentence to score.
    trigger:
        Optional name of the heuristic trigger that fired for this sentence
        (e.g., 'statute', 'magnitude', 'year', 'percentage', 'attribution').
        When provided, the trigger is used to adjust base scores without
        re-running all patterns. When None, all patterns are evaluated.

    Returns
    -------
    float
        Score in [0.0, 1.0].
    """
    # ReDoS prevention: reject oversized inputs before regex processing.
    if len(sentence) > MAX_SENTENCE_CHARS:
        return 0.0

    score = 0.0

    # Statute reference: binding legal obligations are always load-bearing.
    # Weight is 0.55 so a statute reference alone exceeds the 0.5 threshold.
    if _STATUTE.search(sentence):
        score += 0.55

    # Decision/recommendation language.
    # Weight is 0.55 so decision language alone exceeds the 0.5 threshold.
    if _DECISION.search(sentence):
        score += 0.55

    # Magnitude: a specific large number in a non-trivial sentence.
    # Weight is 0.55 so a magnitude claim alone exceeds the 0.5 threshold.
    if _MAGNITUDE.search(sentence):
        score += 0.55

    # Causal, comparison and named-body attribution: each +0.30. On their own
    # they fall below the 0.5 threshold, but in combination with a magnitude,
    # percentage, or each other they push a consequential claim load-bearing.
    if _CAUSAL.search(sentence):
        score += 0.30
    if _COMPARISON.search(sentence):
        score += 0.30
    if _BODY_ATTRIBUTION.search(sentence):
        score += 0.30

    # Percentage: directional but not always decisive on its own.
    if _PERCENTAGE.search(sentence):
        score += 0.15

    # Year mention: modest contribution unless no other signal.
    if _YEAR.search(sentence):
        score += 0.10

    # Hedging language: reduces confidence.
    if _HEDGE.search(sentence):
        score -= 0.20

    # Purely descriptive attribution without decision language:
    # penalise only when _DECISION is absent (otherwise decision language
    # already raised the score).
    if _DESCRIPTIVE_ATTRIBUTION.search(sentence) and not _DECISION.search(sentence):
        score -= 0.15

    # Clamp to [0.0, 1.0].
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Load-bearing threshold
# ---------------------------------------------------------------------------

#: Minimum score for a claim to be considered load-bearing.
#: Documented here so that ledger.py and tests import the constant rather
#: than repeating the magic number.
LOAD_BEARING_THRESHOLD = 0.5


def is_load_bearing(sentence: str, trigger: Optional[str] = None) -> bool:
    """Return True when *sentence* is a load-bearing claim.

    A claim is load-bearing when score_claim() >= LOAD_BEARING_THRESHOLD (0.5).
    This threshold was chosen so that statute references, large-magnitude
    assertions, and decision-language sentences all qualify, while bare year
    mentions in purely descriptive sentences do not.

    Parameters
    ----------
    sentence:
        The claim sentence to evaluate.
    trigger:
        Passed through to score_claim(); may be None.

    Returns
    -------
    bool
    """
    return score_claim(sentence, trigger=trigger) >= LOAD_BEARING_THRESHOLD
