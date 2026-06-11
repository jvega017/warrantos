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
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from warrantos.provenance.extract import (
    CITATION_MARKERS,
    CLAIM_TRIGGERS,
    CITE_NEEDED,
    sentences,
)
from warrantos.provenance.grade import Verdict, get_grader

# ---------------------------------------------------------------------------
# SSRF and scheme guard
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES = {"http", "https"}
_REDIRECT_HOP_CAP = 3


def _is_safe_url(url: str) -> bool:
    """Return True only if *url* is safe to fetch.

    Safety criteria:
    1. Scheme must be http or https; any other scheme (file://, ftp://, etc.)
       is rejected immediately.
    2. A hostname must be present.
    3. The hostname must resolve to at least one address, and EVERY resolved
       address must be a globally routable address (ipaddress.ip_address.is_global
       must be True). This covers loopback, link-local, private RFC 1918,
       CGNAT RFC 6598 (100.64.0.0/10), reserved, multicast, and any future
       IANA-reserved ranges that Python marks as non-global.
    4. Any resolution failure (NXDOMAIN, timeout, OS error) causes rejection.

    Known limitation: DNS rebinding (TOCTOU). This function resolves the
    hostname at validation time; the subsequent TCP connection is a separate
    syscall that may resolve to a different address if the DNS TTL is very
    short and a rebinding attack is in progress. This is an inherent
    limitation of the stdlib approach for this opt-in, CLI-only tool. It is
    NOT a safe replacement for a network-level egress filter.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:
        return False

    if parts.scheme not in _ALLOWED_SCHEMES:
        return False

    hostname = parts.hostname
    if not hostname:
        return False

    try:
        results = socket.getaddrinfo(hostname, None)
    except Exception:
        return False

    if not results:
        return False

    for result in results:
        # result is (family, type, proto, canonname, sockaddr)
        # sockaddr is (address, port) for IPv4, (address, port, flow, scope) for IPv6
        addr_str = result[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            return False

        if not addr.is_global:
            return False

    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that validates each redirect target with _is_safe_url.

    Caps the number of followed hops at _REDIRECT_HOP_CAP using the stdlib
    per-request redirect_dict mechanism (set via max_redirections). Any
    redirect whose target fails the safety check raises urllib.error.URLError
    immediately, preventing SSRF via open redirects.

    No instance-level counter is maintained; the stdlib tracks hop counts
    per Request object, so each fetch_text call gets a clean count via its
    own fresh Request instance.
    """

    def __init__(self):
        # Override the default (10) with our tighter cap.
        # The stdlib http_error_302 enforces this via req.redirect_dict,
        # which is fresh for every new Request object.
        self.max_redirections = _REDIRECT_HOP_CAP

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_safe_url(newurl):
            raise urllib.error.URLError(
                "redirect target failed safety check: %s" % newurl
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Module-level opener that uses the safe redirect handler.
# Built once at import time so tests can monkeypatch it.
# The handler holds no per-request state, so sharing one instance is safe.
_safe_opener = urllib.request.build_opener(_SafeRedirectHandler())

# ---------------------------------------------------------------------------
# fetch_text
# ---------------------------------------------------------------------------

_FETCH_TIMEOUT = 8          # seconds
_FETCH_MAX_BYTES = 1_500_000  # 1.5 MB
_USER_AGENT = "claude-provenance/0.9.0b1 (+https://github.com/jvega017/claude-provenance)"


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

    Validates *url* with _is_safe_url before making any network request.
    Returns None immediately if the URL does not pass the safety check (wrong
    scheme, private/loopback/reserved address, resolution failure).

    Follows up to _REDIRECT_HOP_CAP redirects via _SafeRedirectHandler, which
    re-validates each redirect target. Reads at most 1.5 MB. Strips HTML tags
    if the response looks like HTML. Collapses whitespace. Returns None on ANY
    exception; never raises.

    Parameters
    ----------
    url:
        The HTTP or HTTPS URL to fetch.

    Returns
    -------
    str or None
        Cleaned text, or None if the URL failed the safety check or the
        request failed for any reason.
    """
    if not _is_safe_url(url):
        return None

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
        )
        with _safe_opener.open(req, timeout=_FETCH_TIMEOUT) as resp:
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
