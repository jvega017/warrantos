"""provenance.extract: shared claim-detection patterns and sentence splitting.

These patterns are copied from hooks/provenance_check.py, which remains the
canonical in-session tripwire. This module provides out-of-band reuse for the
CLI verification pipeline (provenance.verify, provenance.grade). If you change
detection logic, update the hook first and mirror the change here.

Australian English throughout.
"""

import re
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Citation markers
# Copied from hooks/provenance_check.py; hook is canonical.
# ---------------------------------------------------------------------------

CITATION_MARKERS = [
    re.compile(r"https?://", re.I),
    re.compile(r"\(?\bsource\s*:", re.I),
    re.compile(r"\[[^\]]+\]\([^)]+\)"),           # markdown link
    re.compile(r"\[\^?\d+\]"),                     # footnote reference
    re.compile(r"\([A-Z][\w.'-]+(?:\s(?:&|et al\.?|and)\s[\w.'-]+)*,\s*\d{4}[a-z]?\)"),  # APA
]

# Explicit "please source this" tag.
# Copied from hooks/provenance_check.py; hook is canonical.
CITE_NEEDED = re.compile(r"\[cite[ _-]?needed\]", re.I)

# ---------------------------------------------------------------------------
# Claim triggers
# Copied from hooks/provenance_check.py; hook is canonical.
# List of (name, compiled_pattern) tuples.
# ---------------------------------------------------------------------------

CLAIM_TRIGGERS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("year",        re.compile(r"\b(?:18|19|20)\d{2}\b")),
    ("percentage",  re.compile(r"\b\d+(?:\.\d+)?\s?%|\bper\s?cent\b|\bpercent\b", re.I)),
    ("magnitude",   re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:million|billion|trillion|bn|tn)\b", re.I)),
    ("statute",     re.compile(r"\b(?:s\.?\s?\d+|section\s\d+|Act\s(?:18|19|20)\d{2})\b")),
    ("attribution", re.compile(r"\b(?:according to|found that|reported that|estimated|shows that|study\b|survey\b|data show|statistics show)\b", re.I)),
]

# ---------------------------------------------------------------------------
# Sentence splitting
# Mirror the approach in hooks/provenance_check.py; hook is canonical.
# ---------------------------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|(?:^|\s)[-*]\s+")


def sentences(text: str) -> List[str]:
    """Split text into candidate sentences.

    Uses the same regex strategy as hooks/provenance_check.py so claim
    detection is consistent between the in-session hook and the out-of-band
    CLI.
    """
    chunks = [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]
    return chunks
