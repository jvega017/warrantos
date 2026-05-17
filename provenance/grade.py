"""provenance.grade: heuristic and LLM-based claim graders.

Provides two grader classes and a Verdict dataclass. The graders implement
Axis 2 verdict classification (verified, contradicted, not_addressed,
unverifiable, skipped, error). Axis 1 (supported/tagged/unsupported) remains
in the hook and is not modified here.

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
    _STOP = {
        "according", "because", "however", "although", "through",
        "within", "between", "before", "during", "against",
        "should", "would", "could", "might", "their", "which",
        "there", "where", "these", "those", "other",
    }
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
# HeuristicGrader
# ---------------------------------------------------------------------------

class HeuristicGrader:
    """Token-overlap heuristic grader. No network I/O. Stdlib only."""

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
            verdict="verified" when salient tokens are present in source_text;
            verdict="not_addressed" when source text is available but tokens
            are absent; verdict="unverifiable" when a citation exists but no
            source text was obtained; verdict="skipped" when neither citation
            nor source text is present.
        """
        if source_text is not None:
            tokens = _salient_tokens(claim_text)
            src_lower = source_text.lower()
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
# Factory function
# ---------------------------------------------------------------------------

def get_grader():
    """Return an LLMGrader if ANTHROPIC_API_KEY is set, else HeuristicGrader."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLMGrader()
    return HeuristicGrader()
