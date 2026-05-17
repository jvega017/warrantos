"""provenance.verify: out-of-band URL fetching and claim verification.

This module is intended for CLI use only. It is never imported or called
from inside hooks/provenance_check.py, which remains stdlib-only and does
no network I/O. Any network access here is explicitly opt-in via the
public API.

Provides:
    fetch_text(url)        -- retrieve and clean text from a URL
    extract_citation(sent) -- pull the first citation token from a sentence
    verify_claim(...)      -- grade a single claim
    verify_text(...)       -- grade all claims in a block of text

Australian English throughout. No third-party dependencies. Python 3.8+.
"""

import html.parser
import re
import urllib.error
import urllib.request
from typing import List, Optional

from provenance.extract import (
    CITATION_MARKERS,
    CLAIM_TRIGGERS,
    CITE_NEEDED,
    sentences,
)
from provenance.grade import Verdict, get_grader

# ---------------------------------------------------------------------------
# fetch_text
# ---------------------------------------------------------------------------

_FETCH_TIMEOUT = 8          # seconds
_FETCH_MAX_BYTES = 1_500_000  # 1.5 MB
_USER_AGENT = "claude-provenance/0.2 (+https://github.com/jvega017/claude-provenance)"


class _HTMLStripper(html.parser.HTMLParser):
    """Minimal HTML-to-text converter using stdlib html.parser.

    Drops script and style element content entirely. Converts all other
    element text to a flat string.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        # Collapse multiple whitespace characters to a single space.
        return re.sub(r"\s+", " ", raw).strip()


def fetch_text(url: str) -> Optional[str]:
    """Retrieve text from *url* and return it as a cleaned plain-text string.

    Follows up to 3 redirects (urllib's default handler behaviour). Reads at
    most 1.5 MB. Strips HTML tags if the response looks like HTML. Collapses
    whitespace. Returns None on ANY exception; never raises.

    Parameters
    ----------
    url:
        The HTTP or HTTPS URL to fetch.

    Returns
    -------
    str or None
        Cleaned text, or None if the request failed for any reason.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            raw_bytes = resp.read(_FETCH_MAX_BYTES)
            content_type = resp.headers.get("Content-Type", "")

        text = raw_bytes.decode("utf-8", errors="replace")

        if "html" in content_type.lower() or text.lstrip().startswith("<"):
            stripper = _HTMLStripper()
            stripper.feed(text)
            text = stripper.get_text()

        # Collapse whitespace.
        text = re.sub(r"\s+", " ", text).strip()
        return text if text else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# extract_citation
# ---------------------------------------------------------------------------

# APA pattern: (Author, YYYY) or (Author et al., YYYY) etc.
# Copied from hooks/provenance_check.py; hook is canonical.
_APA_PATTERN = re.compile(
    r"\([A-Z][\w.'-]+(?:\s(?:&|et al\.?|and)\s[\w.'-]+)*,\s*\d{4}[a-z]?\)",
)

# URL pattern for citation extraction.
_URL_PATTERN = re.compile(r"https?://\S+", re.I)


def extract_citation(sentence: str) -> Optional[str]:
    """Extract the first citation from *sentence*.

    Checks for a URL first; if none, checks for an APA-style
    "(Author, YYYY)" token. Returns the matched string, or None.

    The citation notions here mirror those in hooks/provenance_check.py.
    The hook remains the canonical tripwire; this function provides
    out-of-band reuse.
    """
    url_match = _URL_PATTERN.search(sentence)
    if url_match:
        return url_match.group(0)

    apa_match = _APA_PATTERN.search(sentence)
    if apa_match:
        return apa_match.group(0)

    return None


# ---------------------------------------------------------------------------
# verify_claim
# ---------------------------------------------------------------------------

def verify_claim(
    claim_text: str,
    citation: Optional[str],
    grader=None,
) -> Verdict:
    """Grade a single claim, optionally fetching the cited URL.

    Parameters
    ----------
    claim_text:
        The sentence containing the factual assertion.
    citation:
        A URL or APA reference string, or None.
    grader:
        A grader instance (HeuristicGrader or LLMGrader). If None, the
        grader from get_grader() is used.

    Returns
    -------
    Verdict
    """
    if grader is None:
        grader = get_grader()

    source_text: Optional[str] = None
    if citation and _URL_PATTERN.match(citation):
        source_text = fetch_text(citation)

    return grader.grade(claim_text, source_text, citation)


# ---------------------------------------------------------------------------
# verify_text
# ---------------------------------------------------------------------------

def _looks_like_claim(sentence: str) -> bool:
    """Return True if any CLAIM_TRIGGERS pattern matches *sentence*."""
    return any(rx.search(sentence) for _, rx in CLAIM_TRIGGERS)


def verify_text(
    text: str,
    grader=None,
    fetch: bool = True,
) -> List[Verdict]:
    """Grade all factual claims in *text*.

    Splits *text* into sentences using the same strategy as the hook,
    identifies sentences that contain factual claim triggers, extracts
    citations, and grades each claim.

    Parameters
    ----------
    text:
        The full text block to analyse.
    grader:
        Grader instance to use. If None, get_grader() is called once and
        reused for all claims.
    fetch:
        If False, no network requests are made. The grader receives
        source_text=None for every claim regardless of whether a citation
        URL is present. Useful for offline/deterministic use.

    Returns
    -------
    List[Verdict]
        One Verdict per sentence that contains at least one claim trigger.
    """
    if grader is None:
        grader = get_grader()

    verdicts: List[Verdict] = []
    sents = sentences(text)

    for sent in sents:
        if not _looks_like_claim(sent):
            continue

        citation = extract_citation(sent)

        if fetch and citation and _URL_PATTERN.match(citation):
            source_text: Optional[str] = fetch_text(citation)
        else:
            source_text = None

        verdict = grader.grade(sent, source_text, citation)
        verdicts.append(verdict)

    return verdicts
