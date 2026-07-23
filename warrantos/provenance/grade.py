"""provenance.grade: heuristic and LLM-based claim graders.

Provides two grader classes and a Verdict dataclass. The graders implement
Axis 2 verdict classification (verified, contradicted, not_addressed,
unverifiable, skipped, error). Axis 1 (supported/tagged/unsupported) remains
in the hook and is not modified here.

HeuristicGrader can emit "contradicted" in two narrow, conservative
circumstances: (1) a same-kind numeric mismatch anchored to shared
surrounding content words (see _find_numeric_contradiction below), and (2)
a directional-word antonym (from a small closed vocabulary: rose/fell,
increased/decreased, opened/closed, and similar) anchored to a number the
source confirms verbatim (see _find_direction_contradiction below). Any
contradiction outside that closed vocabulary, or expressed without a
lexical antonym at all, remains out of reach for a token/number heuristic
by construction and is the LLM-backed graders' job.

The LLM grader is optional. It is activated only when the environment variable
ANTHROPIC_API_KEY is set, and degrades gracefully to the heuristic on ANY
failure (missing key, network error, non-200 response, JSON parse failure).
The hook is never called from this module: this is strictly out-of-band.

Stdlib only: urllib, json, os, re, dataclasses, typing. No third-party packages.
Python 3.8 compatible.

Australian English throughout.
"""

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Verdict dataclass — shared interface contract for Agents 2-4
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    """The result of grading a single claim against its cited source.

    Attributes
    ----------
    claim_text:
        The full text of the sentence that contains the factual claim.
    citation:
        The URL or APA reference string extracted from the claim sentence,
        or None if no citation was found.
    verdict:
        One of: verified | contradicted | not_addressed |
                unverifiable | skipped | error.
    confidence:
        Float 0.0-1.0 when a grader can express confidence; None otherwise.
    rationale:
        Human-readable explanation, at most 200 characters, plain text.
    grader:
        Which grader produced this result. One of:
        heuristic | fetch+heuristic | llm:<model> | fetch+llm:<model>.
    """

    claim_text: str
    citation: Optional[str]
    verdict: str
    confidence: Optional[float]
    rationale: str
    grader: str


# ---------------------------------------------------------------------------
# Salient-token extraction for heuristic matching
# ---------------------------------------------------------------------------

# Patterns that identify tokens worth checking (numbers, years, percentages,
# and longer content words).
_NUMBER_TOKEN = re.compile(r"\b\d[\d,./%-]*\b")
_YEAR_TOKEN = re.compile(r"\b(?:18|19|20)\d{2}\b")
_PCT_TOKEN = re.compile(r"\b\d+(?:\.\d+)?\s?%|\bper\s?cent\b|\bpercent\b", re.I)


_URL_STRIP = re.compile(r"https?://\S+", re.I)

# Common function words excluded from the >=6-char content-word tokeniser.
# Module-level so both _salient_tokens and the numeric-contradiction content
# overlap gate share one definition.
_STOP = {
    "according", "because", "however", "although", "through",
    "within", "between", "before", "during", "against",
    "should", "would", "could", "might", "their", "which",
    "there", "where", "these", "those", "other",
}


def _salient_tokens(claim_text: str):
    """Return a list of tokens that are worth checking in the source text.

    Includes: all digit sequences, 4-digit years, percentage expressions,
    and content words of 6 or more characters (excluding common function
    words). URLs are stripped from the claim before extraction so that
    URL hostnames and paths do not contribute noise tokens.
    """
    # Strip embedded URLs before extracting tokens so that URL components
    # (hostnames, path segments) are not treated as salient content tokens.
    claim_text = _URL_STRIP.sub("", claim_text)

    tokens = []

    # Numeric and percentage tokens.
    for m in _NUMBER_TOKEN.finditer(claim_text):
        tokens.append(m.group(0).lower())
    for m in _PCT_TOKEN.finditer(claim_text):
        tokens.append(m.group(0).lower())

    # Longer content words (>=6 chars) to catch distinctive terminology.
    for word in re.findall(r"\b[a-zA-Z]{6,}\b", claim_text):
        if word.lower() not in _STOP:
            tokens.append(word.lower())

    # Deduplicate while preserving order.
    seen = set()
    result = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# Conservative numeric-contradiction detection
# ---------------------------------------------------------------------------
#
# Token-overlap alone cannot tell "enrolled 12,000" from "enrolled 1,200":
# both share every content word, so the claim looks fully corroborated. The
# functions below add one narrow, deliberately cautious signal on top of
# that: a claim number is flagged as contradicted only when (a) a *different*
# number of the *same kind* (year / percentage / plain number) sits right
# next to the same anchor word in the source, i.e. the same "slot" in a
# near-paraphrase sentence, and (b) the claim's other content words still
# overlap the source highly (see _content_overlap_ok). This deliberately
# does NOT try to detect purely semantic contradictions such as an antonym
# ("rose" vs "fell") attached to an unchanged figure -- those are not numeric
# mismatches and flagging them would require real language understanding,
# which is exactly what this heuristic does not have.

_MAGNITUDE_WORDS = {"thousand": 1e3, "million": 1e6, "billion": 1e9}

# A number immediately followed by "%" or by "per cent"/"percent".
_PERCENT_MENTION = re.compile(r"\b(\d+(?:\.\d+)?)\s?(?:%|per\s?cent|percent)\b", re.I)
# A bare 4-digit year (kept separate from generic numbers so that "2021" is
# compared against other years, never against an unrelated magnitude).
_YEAR_MENTION = re.compile(r"\b((?:18|19|20)\d{2})\b")
# Any other digit group, optionally followed by a magnitude word.
_PLAIN_NUMBER_MENTION = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?)\b(?:\s+(thousand|million|billion))?", re.I
)

# Words too common to anchor a positional match; deliberately short so that
# ordinary content words ("enrolled", "reached", "dropped"...) still qualify.
_ANCHOR_STOPWORDS = {
    "the", "a", "an", "to", "of", "in", "by", "at", "on", "for", "and",
    "or", "is", "was", "were", "are", "be", "than", "that", "this",
    "with", "from", "as", "it", "its", "per", "per cent",
}

# Characters either side of an anchor-word occurrence searched for a
# same-kind numeric mention in the source text.
_ANCHOR_WINDOW = 40


def _numeric_mentions(text: str):
    """Return non-overlapping numeric mentions in text.

    Each mention is a dict: {"kind": "percent"|"year"|"number", "value":
    float, "start": int, "end": int, "raw": str}. Values are normalised so
    that formatting variants compare equal: "2 million" == "2,000,000";
    "40%" == "40 per cent". Percentages are extracted first (claiming their
    span), then years, then plain numbers, each pass skipping spans an
    earlier pass already claimed -- this keeps "12,000" from also being
    read as the year-like digits of a plain number, etc.
    """
    claimed = []

    def _overlaps(s, e):
        return any(s < ce and e > cs for cs, ce in claimed)

    mentions = []

    for m in _PERCENT_MENTION.finditer(text):
        s, e = m.span()
        if _overlaps(s, e):
            continue
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        mentions.append({"kind": "percent", "value": value, "start": s, "end": e,
                          "raw": text[s:e]})
        claimed.append((s, e))

    for m in _YEAR_MENTION.finditer(text):
        s, e = m.span()
        if _overlaps(s, e):
            continue
        mentions.append({"kind": "year", "value": float(m.group(1)), "start": s,
                          "end": e, "raw": text[s:e]})
        claimed.append((s, e))

    for m in _PLAIN_NUMBER_MENTION.finditer(text):
        s, e = m.span()
        if _overlaps(s, e):
            continue
        digits = m.group(1).replace(",", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        unit = m.group(2)
        if unit:
            value *= _MAGNITUDE_WORDS[unit.lower()]
        mentions.append({"kind": "number", "value": value, "start": s, "end": e,
                          "raw": text[s:e]})
        claimed.append((s, e))

    mentions.sort(key=lambda d: d["start"])
    return mentions


def _nearby_anchor_word(text: str, start: int, end: int):
    """Return a content word touching a numeric mention's span, or None.

    Checks the word immediately before the mention, then immediately after;
    returns the first one that is at least 4 letters and not a common
    stop-word. Used to locate the equivalent "slot" in the source text so
    that two numbers are only ever compared when they occupy the same
    position in an otherwise matching sentence.
    """
    before = re.findall(r"[a-zA-Z]+", text[:start])
    after = re.findall(r"[a-zA-Z]+", text[end:])
    candidates = []
    if before:
        candidates.append(before[-1])
    if after:
        candidates.append(after[0])
    for word in candidates:
        if len(word) >= 4 and word.lower() not in _ANCHOR_STOPWORDS:
            return word.lower()
    return None


def _find_numeric_contradiction(claim_text: str, source_text: str):
    """Look for a same-kind numeric mismatch anchored to shared context.

    Returns (claim_mention, source_mention) for the first mismatch found,
    or None. A mismatch requires: an anchor content word touching the
    claim's numeric mention, that same anchor word appearing in the source
    text, and -- within a small character window of that anchor occurrence
    -- a numeric mention of the SAME kind whose value differs from the
    claim's. If the anchored source value instead equals the claim's value,
    that claim mention is treated as confirmed (not a mismatch), even if
    the exact same value also happens to occur elsewhere in the source
    outside the anchor window.
    """
    claim_mentions = _numeric_mentions(claim_text)
    if not claim_mentions:
        return None
    source_mentions = _numeric_mentions(source_text)
    if not source_mentions:
        return None
    source_lower = source_text.lower()

    for cm in claim_mentions:
        anchor = _nearby_anchor_word(claim_text, cm["start"], cm["end"])
        if not anchor:
            continue

        matched_same = False
        mismatch = None
        for occ in re.finditer(re.escape(anchor), source_lower):
            a_start, a_end = occ.span()
            window_start = max(0, a_start - _ANCHOR_WINDOW)
            window_end = min(len(source_text), a_end + _ANCHOR_WINDOW)
            for sm in source_mentions:
                if sm["kind"] != cm["kind"]:
                    continue
                if sm["end"] <= window_start or sm["start"] >= window_end:
                    continue
                if sm["value"] == cm["value"]:
                    matched_same = True
                elif mismatch is None:
                    mismatch = sm
        if matched_same:
            # This token's value is corroborated near the same anchor;
            # do not let an unrelated mismatch elsewhere override it.
            continue
        if mismatch is not None:
            return (cm, mismatch)
    return None


def _content_overlap_ok(claim_text: str, source_lower: str, exclude=frozenset(),
                         min_words: int = 1) -> bool:
    """Return True when the claim's non-numeric content words all appear
    in the (already lower-cased) source text.

    This is the "high content-word overlap" gate: a numeric mismatch is
    only trusted as a genuine contradiction when the surrounding sentence
    is otherwise clearly about the same subject, not just two unrelated
    numbers that happen to share a common word. Requires at least
    ``min_words`` content words (default 1) so a claim with too few
    >=6-char content words never fires. ``exclude`` removes words from the
    requirement before counting or checking -- used by the direction-word
    contradiction check below to exclude the directional vocabulary itself
    (which is expected to differ between claim and source; that is the
    whole point of the check) from the "must appear in source" rule.
    """
    words = {w.lower() for w in re.findall(r"\b[a-zA-Z]{6,}\b", claim_text)
             if w.lower() not in _STOP and w.lower() not in exclude}
    return len(words) >= min_words and all(w in source_lower for w in words)


# ---------------------------------------------------------------------------
# Conservative direction/antonym contradiction detection
# ---------------------------------------------------------------------------
#
# Token overlap also cannot tell "fell 18 per cent" from "rose 18 per
# cent": the number is identical, so every salient token matches and the
# claim looks fully corroborated. This adds one further narrow, conservative
# signal on top of _find_numeric_contradiction: when a numeric value in the
# claim is confirmed VERBATIM in the source (the "anchor"), check whether a
# directional word next to that anchor in the claim is contradicted by an
# opposite-polarity directional word next to the SAME anchor in the source.
#
# This is deliberately not a sentiment or negation model -- it is a small,
# closed vocabulary of directional verbs/adjectives split into two
# polarities, plus safety valves that make it fail closed rather than open:
#   1. If the source contains directional words of BOTH polarities near the
#      anchor, the signal is ambiguous and nothing fires for that anchor.
#   2. If a negation word ("not"/"no"/"never"/"none"/"nor") sits within a
#      few words of a directional word, that occurrence is discarded rather
#      than trusted, on either side.
#   3. The claim's other content words must still overlap the source highly
#      (the same _content_overlap_ok gate above), so a shared directional
#      word alone is never enough.
# When neither claim nor source has any numeric mention at all, a stricter
# fallback compares directional words across the whole sentence pair
# instead of a numeric anchor -- gated by a higher overlap threshold, since
# there is no number to localise the comparison to the same subject.

_UP_WORDS = {
    "rose", "rise", "rises", "rising", "risen",
    "increased", "increase", "increases", "increasing",
    "grew", "grow", "grows", "growing", "grown",
    "gained", "gain", "gains", "gaining",
    "opened", "opens", "opening",
    "expanded", "expand", "expands", "expanding",
    "retained", "retain", "retains", "retaining",
    "strengthened", "strengthen", "strengthens", "strengthening",
    "improved", "improve", "improves", "improving",
    "widened", "widen", "widens", "widening",
    "above", "more", "up", "higher", "highest", "surplus",
}

_DOWN_WORDS = {
    "fell", "fall", "falls", "falling", "fallen",
    "decreased", "decrease", "decreases", "decreasing",
    "dropped", "drop", "drops", "dropping",
    "shrank", "shrink", "shrinks", "shrinking", "shrunk",
    "sank", "sink", "sinks", "sinking", "sunk",
    "lost", "lose", "loses", "losing",
    "closed", "close", "closes", "closing",
    "abolished", "abolish", "abolishes", "abolishing",
    "reduced", "reduce", "reduces", "reducing",
    "declined", "decline", "declines", "declining",
    "narrowed", "narrow", "narrows", "narrowing",
    "worsened", "worsen", "worsens", "worsening",
    "below", "fewer", "down", "lower", "lowest", "deficit",
}

# word -> "up" | "down". Built from the two vocabularies above so there is
# one source of truth for both membership and polarity lookup.
_DIRECTION_WORDS = {w: "up" for w in _UP_WORDS}
_DIRECTION_WORDS.update({w: "down" for w in _DOWN_WORDS})

_NEGATION_WORDS = {"not", "no", "never", "none", "nor", "cannot", "n't"}

# Characters either side of a numeric anchor searched for a directional
# word. Deliberately wider than _ANCHOR_WINDOW: a direction verb is often
# further from its number than the single adjacent word _nearby_anchor_word
# looks for (e.g. "rose ... by 9 per cent ... by 2022").
_DIRECTION_WINDOW = 60

# Characters either side of a directional-word occurrence searched for a
# negation word before that occurrence is trusted.
_NEGATION_WINDOW = 20


def _direction_words_near(text: str, center_start: int, center_end: int, window: int):
    """Return (word, polarity, negated) tuples for directional vocabulary
    found within `window` characters of [center_start, center_end) in text.

    `negated` is True when a negation word ("not"/"no"/"never"/"none"/
    "nor"/"cannot"/"n't") occurs within _NEGATION_WINDOW characters of the
    directional word, on either side -- callers should treat such
    occurrences as untrustworthy rather than as a confirmed direction.
    """
    window_start = max(0, center_start - window)
    window_end = min(len(text), center_end + window)
    snippet = text[window_start:window_end]

    results = []
    for m in re.finditer(r"[a-zA-Z']+", snippet):
        word = m.group(0).lower()
        polarity = _DIRECTION_WORDS.get(word)
        if polarity is None:
            continue
        local_start = max(0, m.start() - _NEGATION_WINDOW)
        local_end = min(len(snippet), m.end() + _NEGATION_WINDOW)
        local_words = re.findall(r"[a-zA-Z']+", snippet[local_start:local_end].lower())
        negated = any(w in _NEGATION_WORDS for w in local_words)
        results.append((word, polarity, negated))
    return results


def _single_polarity(direction_hits):
    """Return the one polarity present among non-negated hits, or None if
    zero or more than one distinct polarity is present (i.e. ambiguous:
    nothing nearby, or both "up" and "down" words appear near the same
    anchor)."""
    clean = [h for h in direction_hits if not h[2]]
    polarities = {h[1] for h in clean}
    if len(polarities) != 1:
        return None, clean
    return next(iter(polarities)), clean


def _find_direction_contradiction(claim_text: str, source_text: str):
    """Look for a claim directional word contradicted by an opposite-
    polarity directional word anchored to the same matched numeric value.

    Returns (claim_word, source_word, anchor_kind) for the first
    contradiction found, or None. `anchor_kind` is a numeric kind
    ("year"/"percent"/"number") when anchored to a matching number, or the
    literal string "sentence" for the stricter number-free fallback (used
    only when neither claim nor source contains any numeric mention at
    all). See the module notes above for the conservative safety valves.
    """
    claim_mentions = _numeric_mentions(claim_text)
    source_mentions = _numeric_mentions(source_text)

    if claim_mentions:
        # Number-anchored path: only ever compare directional words next
        # to a numeric value confirmed verbatim in both texts.
        for cm in claim_mentions:
            source_matches = [
                sm for sm in source_mentions
                if sm["kind"] == cm["kind"] and sm["value"] == cm["value"]
            ]
            if not source_matches:
                continue

            claim_polarity, claim_clean = _single_polarity(
                _direction_words_near(claim_text, cm["start"], cm["end"], _DIRECTION_WINDOW)
            )
            if claim_polarity is None or not claim_clean:
                continue

            for sm in source_matches:
                source_polarity, source_clean = _single_polarity(
                    _direction_words_near(source_text, sm["start"], sm["end"], _DIRECTION_WINDOW)
                )
                if source_polarity is None:
                    # No directional word nearby, only negated occurrences,
                    # or both polarities present at once: ambiguous either
                    # way, so this anchor stays silent.
                    continue
                if source_polarity != claim_polarity:
                    return (claim_clean[0][0], source_clean[0][0], cm["kind"])
        return None

    # Number-free fallback: only when BOTH claim and source have zero
    # numeric mentions. A number present in one but not the other is the
    # "omission" case this feature must not touch.
    if source_mentions:
        return None

    claim_polarity, claim_clean = _single_polarity(
        _direction_words_near(claim_text, 0, len(claim_text), 0)
    )
    if claim_polarity is None or not claim_clean:
        return None
    source_polarity, source_clean = _single_polarity(
        _direction_words_near(source_text, 0, len(source_text), 0)
    )
    if source_polarity is None or source_polarity == claim_polarity:
        return None
    return (claim_clean[0][0], source_clean[0][0], "sentence")


# ---------------------------------------------------------------------------
# HeuristicGrader
# ---------------------------------------------------------------------------

class HeuristicGrader:
    """Token-overlap heuristic grader, with two narrow contradiction checks
    layered on top. No network I/O. Stdlib only.

    This is still fundamentally a token/number/small-vocabulary heuristic,
    not a language understanding model. It can emit "contradicted" in two
    deliberately narrow circumstances:

    1. A claim's numeric value is undermined by a different, same-kind
       value anchored to shared surrounding words in the source (see
       _find_numeric_contradiction) -- "enrolled 12,000" vs "enrolled
       1,200".
    2. A claim's numeric value is CONFIRMED verbatim in the source, but a
       directional word next to it in the claim (from a small closed
       vocabulary: rose/fell, increased/decreased, opened/closed, and
       similar) is contradicted by an opposite-polarity directional word
       next to the same number in the source (see
       _find_direction_contradiction) -- "fell 18 per cent" vs "rose 18
       per cent".

    Contradictions outside this closed vocabulary, or expressed without a
    lexical antonym at all (e.g. free-form negation, implication, or
    domain reasoning), remain structurally out of reach for this grader.
    """

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        """Grade a claim against optional source text.

        Parameters
        ----------
        claim_text:
            The sentence asserting the fact.
        source_text:
            The text fetched from the citation URL, or None if not fetched.
        citation:
            The raw citation string from the claim sentence (URL or APA ref).

        Returns
        -------
        Verdict
            verdict="contradicted" when either (a) a numeric token in the
            claim (a year, percentage, or plain number) is undermined by a
            different, same-kind numeric token anchored to shared context
            words in the source (see _find_numeric_contradiction), or (b)
            a directional word next to a numeric value the source confirms
            verbatim is contradicted by an opposite-polarity directional
            word next to that same value in the source (see
            _find_direction_contradiction) -- in both cases only when the
            claim's other content words still overlap the source highly
            (see _content_overlap_ok); verdict="verified" when salient
            tokens are present in source_text; verdict="not_addressed"
            when source text is available but tokens are absent;
            verdict="unverifiable" when a citation exists but no source
            text was obtained; verdict="skipped" when neither citation nor
            source text is present.
        """
        if source_text is not None:
            src_lower = source_text.lower()

            contradiction = _find_numeric_contradiction(claim_text, source_text)
            if contradiction is not None and _content_overlap_ok(claim_text, src_lower):
                claim_mention, source_mention = contradiction
                rationale = (
                    "Source gives a different %s (%s) than the claim's %s."
                    % (claim_mention["kind"], source_mention["raw"], claim_mention["raw"])
                )[:200]
                return Verdict(
                    claim_text=claim_text,
                    citation=citation,
                    verdict="contradicted",
                    confidence=0.65,
                    rationale=rationale,
                    grader="fetch+heuristic",
                )

            direction = _find_direction_contradiction(claim_text, source_text)
            if direction is not None:
                claim_word, source_word, anchor_kind = direction
                min_words = 2 if anchor_kind == "sentence" else 1
                if _content_overlap_ok(claim_text, src_lower,
                                       exclude=_DIRECTION_WORDS, min_words=min_words):
                    rationale = (
                        "Source says '%s' where the claim says '%s' for the same figure."
                        % (source_word, claim_word)
                    )[:200]
                    return Verdict(
                        claim_text=claim_text,
                        citation=citation,
                        verdict="contradicted",
                        confidence=0.6,
                        rationale=rationale,
                        grader="fetch+heuristic",
                    )

            tokens = _salient_tokens(claim_text)
            if tokens and all(t in src_lower for t in tokens):
                return Verdict(
                    claim_text=claim_text,
                    citation=citation,
                    verdict="verified",
                    confidence=None,
                    rationale="All salient tokens found in source text.",
                    grader="fetch+heuristic",
                )
            # Either no salient tokens or at least one was absent.
            missing = [t for t in tokens if t not in src_lower]
            snippet = (", ".join(missing[:3]) + ("..." if len(missing) > 3 else ""))
            rationale = (
                ("No salient tokens matched in source." if not tokens
                 else "Token(s) not found in source: " + snippet)
            )[:200]
            return Verdict(
                claim_text=claim_text,
                citation=citation,
                verdict="not_addressed",
                confidence=None,
                rationale=rationale,
                grader="fetch+heuristic",
            )

        if citation is not None:
            return Verdict(
                claim_text=claim_text,
                citation=citation,
                verdict="unverifiable",
                confidence=None,
                rationale="Citation present but source text could not be retrieved.",
                grader="heuristic",
            )

        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict="skipped",
            confidence=None,
            rationale="No citation and no source text; nothing to check.",
            grader="heuristic",
        )


# ---------------------------------------------------------------------------
# LLMGrader
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_API_URL = "https://api.anthropic.com/v1/messages"
_VALID_VERDICTS = {"verified", "contradicted", "not_addressed", "unverifiable", "skipped", "error"}

_SYSTEM_PROMPT = (
    "You are a provenance grader. You will be given a factual claim and the "
    "text of a cited source. Assess whether the source text supports, "
    "contradicts, or does not address the claim. "
    "Respond with ONLY a JSON object in this exact format: "
    '{"verdict": "<one of: verified|contradicted|not_addressed|unverifiable|skipped|error>", '
    '"confidence": <float 0.0 to 1.0>, '
    '"rationale": "<explanation under 200 characters>"}'
    " No additional text, no markdown fencing."
)


def _build_user_message(claim_text: str, source_text: Optional[str], citation: Optional[str]) -> str:
    parts = ["Claim: " + claim_text]
    if citation:
        parts.append("Citation: " + citation)
    if source_text:
        # Truncate to avoid very large prompts; 3000 chars is enough context.
        excerpt = source_text[:3000]
        parts.append("Source text (excerpt):\n" + excerpt)
    else:
        parts.append("Source text: (not available)")
    return "\n\n".join(parts)


class LLMGrader:
    """LLM-backed grader using the Anthropic Messages API.

    Requires ANTHROPIC_API_KEY in the environment. Falls back to
    HeuristicGrader on any failure: missing key, network error, non-200
    HTTP response, or JSON parse failure. Never raises.
    """

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        """Grade a claim, attempting an LLM call first.

        Falls back to HeuristicGrader on any failure. Never raises.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        model = os.environ.get("PROVENANCE_GRADER_MODEL", _DEFAULT_MODEL)
        grader_label = ("fetch+llm:" + model) if source_text is not None else ("llm:" + model)

        payload = json.dumps({
            "model": model,
            "max_tokens": 256,
            "system": _SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": _build_user_message(claim_text, source_text, citation)},
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            _API_URL,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    return HeuristicGrader().grade(claim_text, source_text, citation)
                body = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        try:
            outer = json.loads(body)
            # The API returns content as a list of blocks.
            raw_text = ""
            content = outer.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        raw_text = block.get("text", "")
                        break
            elif isinstance(content, str):
                raw_text = content
            parsed = json.loads(raw_text)
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        verdict_str = str(parsed.get("verdict", "error"))
        if verdict_str not in _VALID_VERDICTS:
            verdict_str = "error"

        raw_conf = parsed.get("confidence")
        try:
            confidence = float(raw_conf) if raw_conf is not None else None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = None

        raw_rationale = str(parsed.get("rationale", ""))[:200]

        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict=verdict_str,
            confidence=confidence,
            rationale=raw_rationale,
            grader=grader_label,
        )


# ---------------------------------------------------------------------------
# LocalLLMGrader (OpenAI-compatible endpoint; no Anthropic API key required)
# ---------------------------------------------------------------------------

# Speaks the OpenAI-compatible /v1/chat/completions request shape, which
# Ollama, llama.cpp's server, LM Studio, vLLM, and most local-LLM tools
# implement. Activated by setting PROVENANCE_LOCAL_GRADER_URL; falls
# back to HeuristicGrader on any failure. No data leaves the local
# host.


_LOCAL_DEFAULT_MODEL = "llama3.2"


class LocalLLMGrader:
    """OpenAI-compatible grader for local LLM servers.

    Posts a chat-completions request to ``PROVENANCE_LOCAL_GRADER_URL``
    (e.g. ``http://localhost:11434/v1/chat/completions`` for Ollama).
    Returns a Verdict using the same JSON envelope as ``LLMGrader``.
    Falls back to ``HeuristicGrader`` on any failure: missing env var,
    network error, non-200 response, JSON parse failure.

    Environment variables:

    - ``PROVENANCE_LOCAL_GRADER_URL`` (required to activate): the full
      URL to the chat-completions endpoint.
    - ``PROVENANCE_LOCAL_GRADER_MODEL`` (default ``llama3.2``): model
      name passed in the request body.
    - ``PROVENANCE_LOCAL_GRADER_API_KEY`` (optional): bearer token for
      hosts that require auth (e.g. self-hosted vLLM behind nginx).
      Most local-LLM tools accept no key at all.
    - ``PROVENANCE_LOCAL_GRADER_TIMEOUT`` (default 60s).

    The grader never imports any third-party SDK; the request is built
    with ``urllib.request`` so the stdlib-only guarantee holds.
    """

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        endpoint = os.environ.get("PROVENANCE_LOCAL_GRADER_URL", "").strip()
        if not endpoint:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        model = os.environ.get("PROVENANCE_LOCAL_GRADER_MODEL", _LOCAL_DEFAULT_MODEL)
        api_key = os.environ.get("PROVENANCE_LOCAL_GRADER_API_KEY", "").strip()
        try:
            timeout = float(os.environ.get("PROVENANCE_LOCAL_GRADER_TIMEOUT", "60"))
        except (TypeError, ValueError):
            timeout = 60.0

        grader_label = (
            "fetch+local-llm:" + model
            if source_text is not None
            else "local-llm:" + model
        )

        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(claim_text, source_text, citation)},
            ],
            "max_tokens": 256,
            "temperature": 0.0,
            # OpenAI-style response_format request for structured JSON;
            # many local servers honour this, but the grader does not
            # depend on it (the JSON parser handles raw text too).
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key

        req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return HeuristicGrader().grade(claim_text, source_text, citation)
                body = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        try:
            outer = json.loads(body)
            # OpenAI shape: choices[0].message.content
            choices = outer.get("choices") or []
            if not choices:
                return HeuristicGrader().grade(claim_text, source_text, citation)
            raw_text = choices[0].get("message", {}).get("content", "")
            if not isinstance(raw_text, str):
                raw_text = ""
            # Some local servers wrap the JSON in ```json fences; strip
            # them defensively.
            raw_text = raw_text.strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.I | re.M)
            parsed = json.loads(raw_text)
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        verdict_str = str(parsed.get("verdict", "error"))
        if verdict_str not in _VALID_VERDICTS:
            verdict_str = "error"

        raw_conf = parsed.get("confidence")
        try:
            confidence = float(raw_conf) if raw_conf is not None else None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = None

        raw_rationale = str(parsed.get("rationale", ""))[:200]

        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict=verdict_str,
            confidence=confidence,
            rationale=raw_rationale,
            grader=grader_label,
        )


# ---------------------------------------------------------------------------
# CodexGrader
# ---------------------------------------------------------------------------

_CODEX_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(_VALID_VERDICTS)},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "confidence", "rationale"],
    "additionalProperties": False,
}


class CodexGrader:
    """Cross-model grader driven by the local Codex CLI (out of band).

    This grader exists for evaluation only. It is never auto-selected by
    get_grader() and is never reachable from the hook. It shells out to
    `codex exec` as a separate, read-only, ephemeral subprocess and feeds it
    exactly the same system prompt, claim, source and citation that
    LLMGrader uses, so the two are a same-task, same-inputs, different-model
    comparison.

    It measures whether a different vendor's model recovers the contradiction
    class that the token-overlap heuristic structurally cannot. Numbers are
    model-dependent and not bit-reproducible. Requires the Codex CLI to be
    installed and authenticated. Degrades to verdict "error" on ANY failure
    (binary missing, non-zero exit, timeout, schema or JSON failure); never
    raises.

    Configuration (environment, all optional):
        PROVENANCE_CODEX_BIN      codex binary name or path (default "codex")
        PROVENANCE_CODEX_TIMEOUT  per-call timeout in seconds (default 120)
        PROVENANCE_CODEX_MODEL    model passed to `codex exec -m` (default:
                                  Codex config default; not overridden)

    Stdlib only: subprocess, tempfile, json, os, re. Python 3.8 compatible.
    """

    grader_label = "codex-cli"

    def _error(self, claim_text, citation, reason):
        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict="error",
            confidence=None,
            rationale=str(reason)[:200],
            grader=self.grader_label,
        )

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        """Grade a claim. Deterministic when there is no source text;
        otherwise delegates the judgement to `codex exec`.
        """
        # No-source path is deterministic and matches HeuristicGrader, so the
        # two graders are compared on identical ground for these items and no
        # Codex call is spent.
        if source_text is None:
            if citation is not None:
                return Verdict(
                    claim_text=claim_text,
                    citation=citation,
                    verdict="unverifiable",
                    confidence=None,
                    rationale="Citation present but source text could not be retrieved.",
                    grader=self.grader_label,
                )
            return Verdict(
                claim_text=claim_text,
                citation=citation,
                verdict="skipped",
                confidence=None,
                rationale="No citation and no source text; nothing to check.",
                grader=self.grader_label,
            )

        import subprocess
        import tempfile

        codex_bin = os.environ.get("PROVENANCE_CODEX_BIN") or self._resolve_codex_bin()
        try:
            timeout = int(os.environ.get("PROVENANCE_CODEX_TIMEOUT", "120"))
        except (TypeError, ValueError):
            timeout = 120
        model = os.environ.get("PROVENANCE_CODEX_MODEL", "")

        prompt = (
            _SYSTEM_PROMPT
            + "\n\n"
            + _build_user_message(claim_text, source_text, citation)
            + "\n\nDo not browse the filesystem or run commands. Answer only "
            "with the JSON object described above."
        )

        schema_path = None
        out_path = None
        try:
            sfd, schema_path = tempfile.mkstemp(suffix=".json", prefix="pv_codex_schema_")
            with os.fdopen(sfd, "w", encoding="utf-8") as fh:
                json.dump(_CODEX_SCHEMA, fh)
            ofd, out_path = tempfile.mkstemp(suffix=".txt", prefix="pv_codex_out_")
            os.close(ofd)

            cmd = [
                codex_bin, "exec",
                "-s", "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color", "never",
                "--output-schema", schema_path,
                "--output-last-message", out_path,
            ]
            if model:
                cmd += ["-m", model]
            cmd.append("-")  # read the prompt from stdin

            with tempfile.TemporaryDirectory(prefix="pv_codex_cwd_") as workdir:
                try:
                    proc = subprocess.run(
                        cmd,
                        input=prompt,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        cwd=workdir,
                    )
                except FileNotFoundError:
                    return self._error(claim_text, citation,
                                       "Codex CLI not found: " + codex_bin)
                except subprocess.TimeoutExpired:
                    return self._error(claim_text, citation,
                                       "Codex call timed out after %ds" % timeout)

            try:
                with open(out_path, "r", encoding="utf-8", errors="replace") as fh:
                    raw = fh.read().strip()
            except OSError:
                raw = ""

            if not raw:
                if proc.returncode != 0:
                    return self._error(
                        claim_text, citation,
                        "Codex exited %d: %s" % (proc.returncode,
                                                 (proc.stderr or "").strip()[:120]))
                return self._error(claim_text, citation,
                                   "Codex produced no final message.")

            parsed = self._extract_json(raw)
            if parsed is None:
                return self._error(claim_text, citation,
                                   "Could not parse JSON from Codex output.")

            verdict_str = str(parsed.get("verdict", "error"))
            if verdict_str not in _VALID_VERDICTS:
                verdict_str = "error"

            raw_conf = parsed.get("confidence")
            try:
                confidence = float(raw_conf) if raw_conf is not None else None
                if confidence is not None:
                    confidence = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = None

            rationale = str(parsed.get("rationale", ""))[:200]

            return Verdict(
                claim_text=claim_text,
                citation=citation,
                verdict=verdict_str,
                confidence=confidence,
                rationale=rationale,
                grader=self.grader_label,
            )
        except Exception as exc:  # never raise out of a grader
            return self._error(claim_text, citation, "Codex grader failure: %s" % exc)
        finally:
            for p in (schema_path, out_path):
                if p:
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    @staticmethod
    def _resolve_codex_bin():
        """Resolve the codex executable robustly across platforms.

        On Windows the npm-installed `codex` shim is an extensionless shell
        script that CreateProcess cannot launch, so a bare "codex" fails
        with FileNotFoundError and the grader degrades to verdict "error"
        for every item. The `.cmd` shim runs correctly through subprocess.
        Prefer an extension Windows can execute, then fall back to the bare
        name so behaviour is unchanged on POSIX (where shutil.which for the
        Windows-only names returns None and "codex" resolves normally).
        """
        import shutil
        for name in ("codex.cmd", "codex.exe", "codex"):
            found = shutil.which(name)
            if found:
                return found
        return "codex"

    @staticmethod
    def _extract_json(raw: str):
        """Parse a JSON object from Codex output, tolerating wrapping prose."""
        try:
            return json.loads(raw)
        except Exception:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                return None
        return None


# ---------------------------------------------------------------------------
# ClaudeCliGrader (subscription-over-API: shells out to `claude --print`)
# ---------------------------------------------------------------------------

class ClaudeCliGrader:
    """Grader driven by the local ``claude`` CLI in non-interactive mode.

    This is the subscription-over-API path: it shells out to
    ``claude --print`` (the headless one-shot mode) instead of calling the
    Anthropic Messages API with an ``ANTHROPIC_API_KEY``. It is auto-selected
    by ``get_grader()`` when the ``claude`` binary is on PATH and neither
    ``ANTHROPIC_API_KEY`` nor ``PROVENANCE_LOCAL_GRADER_URL`` is set, so a
    user on a Claude subscription verifies through their plan rather than
    spending API credits.

    It feeds ``claude --print`` exactly the same system prompt, claim, source
    and citation as ``LLMGrader``, so the two are a same-task, same-inputs
    comparison. Degrades to ``HeuristicGrader`` on ANY failure (binary
    missing, non-zero exit, timeout, empty output, JSON parse failure) so the
    grader never raises and never blocks.

    Configuration (environment, all optional):
        PROVENANCE_CLAUDE_BIN      claude binary name or path (default
                                   "claude"; resolved across platforms)
        PROVENANCE_CLAUDE_TIMEOUT  per-call timeout in seconds (default 120)
        PROVENANCE_CLAUDE_MODEL    model passed to `claude --model` (default:
                                   the CLI's configured default; not overridden)

    Stdlib only: subprocess, json, os, re. Python 3.8 compatible.
    """

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        """Grade a claim via `claude --print`.

        Falls back to HeuristicGrader on any failure. Never raises.
        """
        import subprocess

        claude_bin = os.environ.get("PROVENANCE_CLAUDE_BIN") or self._resolve_claude_bin()
        try:
            timeout = int(os.environ.get("PROVENANCE_CLAUDE_TIMEOUT", "120"))
        except (TypeError, ValueError):
            timeout = 120
        model = os.environ.get("PROVENANCE_CLAUDE_MODEL", "")

        grader_label = (
            "fetch+claude-cli" if source_text is not None else "claude-cli"
        )

        prompt = (
            _SYSTEM_PROMPT
            + "\n\n"
            + _build_user_message(claim_text, source_text, citation)
            + "\n\nAnswer only with the JSON object described above."
        )

        cmd = [claude_bin, "--print"]
        if model:
            cmd += ["--model", model]

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return HeuristicGrader().grade(claim_text, source_text, citation)
        except subprocess.TimeoutExpired:
            return HeuristicGrader().grade(claim_text, source_text, citation)
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        if proc.returncode != 0:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        raw = (proc.stdout or "").strip()
        if not raw:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        parsed = CodexGrader._extract_json(raw)
        if parsed is None:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        verdict_str = str(parsed.get("verdict", "error"))
        if verdict_str not in _VALID_VERDICTS:
            verdict_str = "error"

        raw_conf = parsed.get("confidence")
        try:
            confidence = float(raw_conf) if raw_conf is not None else None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = None

        rationale = str(parsed.get("rationale", ""))[:200]

        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict=verdict_str,
            confidence=confidence,
            rationale=rationale,
            grader=grader_label,
        )

    @staticmethod
    def _resolve_claude_bin():
        """Resolve the claude executable robustly across platforms.

        On Windows the npm-installed `claude` shim is an extensionless shell
        script that CreateProcess cannot launch, so a bare "claude" fails
        with FileNotFoundError. Prefer an extension Windows can execute, then
        fall back to the bare name so behaviour is unchanged on POSIX.
        """
        import shutil
        for name in ("claude.cmd", "claude.exe", "claude"):
            found = shutil.which(name)
            if found:
                return found
        return "claude"

    @staticmethod
    def is_available():
        """Return True if a launchable `claude` binary is on PATH.

        Honours PROVENANCE_CLAUDE_BIN: when set to an explicit path that
        shutil.which resolves, that wins; otherwise the standard shims are
        probed. Used by get_grader() for auto-selection.
        """
        import shutil
        override = os.environ.get("PROVENANCE_CLAUDE_BIN")
        if override:
            return shutil.which(override) is not None
        for name in ("claude.cmd", "claude.exe", "claude"):
            if shutil.which(name):
                return True
        return False


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def _probe_ollama_local():
    """Check if Ollama is running on localhost:11434 and available.

    Returns True if a cheap GET /api/tags returns 200, False otherwise.
    Never raises. Used by get_grader() for opt-in auto-detection.

    Skips probing if:
    - PROVENANCE_LOCAL_GRADER_URL is already set (explicit config wins)
    - We're in a CI environment (detect via CI env vars)
    - We're in a test runner environment (running tests, not production)
    """
    if os.environ.get("PROVENANCE_LOCAL_GRADER_URL"):
        return False

    # Skip in CI environments: GitHub Actions, GitLab, etc.
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") or os.environ.get("GITLAB_CI"):
        return False

    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            method="GET"
        )
        req.add_header("User-Agent", "warrantos/ollama-probe")
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            return resp.status == 200
    except Exception:
        # Catch all: URLError, HTTPError, OSError, TimeoutError, socket errors, etc.
        # Never raise. Return False if anything goes wrong.
        return False


_GRADER_OVERRIDE_REGISTRY = {
    "heuristic": lambda: HeuristicGrader(),
    "local": lambda: LocalLLMGrader(),
    "local-llm": lambda: LocalLLMGrader(),
    "llm": lambda: LLMGrader(),
    "anthropic": lambda: LLMGrader(),
    "claude": lambda: ClaudeCliGrader(),
    "claude-cli": lambda: ClaudeCliGrader(),
    "codex": lambda: CodexGrader(),
}


def get_grader():
    """Return the most capable grader available in the current environment.

    An explicit ``PROVENANCE_GRADER`` override wins over auto-selection.
    Recognised values (case-insensitive): ``heuristic``, ``local`` /
    ``local-llm``, ``llm`` / ``anthropic``, ``claude`` / ``claude-cli``,
    ``codex``. An unrecognised value is ignored and auto-selection runs.

    Auto-selection order (first match wins):

    1. ``LocalLLMGrader`` if ``PROVENANCE_LOCAL_GRADER_URL`` is set. No
       data egress, no Anthropic API key required. See LocalLLMGrader
       docstring for env vars.
    2. ``LocalLLMGrader`` if Ollama is detected on localhost:11434
       (opt-in auto-detection via cheap /api/tags probe). Sets
       ``PROVENANCE_LOCAL_GRADER_URL`` automatically.
    3. ``LLMGrader`` if ``ANTHROPIC_API_KEY`` is set. Calls the
       Anthropic Messages API.
    4. ``ClaudeCliGrader`` if the ``claude`` CLI is on PATH (and neither
       of the above applies). This is the subscription-over-API path: it
       shells out to ``claude --print`` so a user on a Claude plan verifies
       through their subscription rather than spending API credits.
    5. ``HeuristicGrader`` otherwise. Local, free, deterministic. It can
       emit ``contradicted`` only for a narrow, anchored same-kind numeric
       mismatch, or a closed-vocabulary directional antonym anchored to a
       matching number (see ``HeuristicGrader``,
       ``_find_numeric_contradiction`` and ``_find_direction_contradiction``);
       contradictions outside that scope remain out of its reach.

    ``CodexGrader`` is never auto-selected: it is an evaluation-only
    backend that must be requested explicitly (via ``PROVENANCE_GRADER``
    or the eval harness).

    Order rationale: an explicit API key or local-LLM URL signals a
    deliberate choice and is honoured first. Ollama auto-detection is
    next (cheap probe, no cost if absent). The ``claude`` CLI is the
    subscription-over-API fallback (no credits spent) when no key is set.
    The heuristic is the final fallback.
    """
    override = (os.environ.get("PROVENANCE_GRADER") or "").strip().lower()
    if override in _GRADER_OVERRIDE_REGISTRY:
        return _GRADER_OVERRIDE_REGISTRY[override]()

    if os.environ.get("PROVENANCE_LOCAL_GRADER_URL"):
        return LocalLLMGrader()

    # Opt-in Ollama auto-detection: probe localhost:11434
    if _probe_ollama_local():
        os.environ["PROVENANCE_LOCAL_GRADER_URL"] = "http://localhost:11434/v1/chat/completions"
        return LocalLLMGrader()

    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLMGrader()
    if ClaudeCliGrader.is_available():
        return ClaudeCliGrader()
    return HeuristicGrader()
