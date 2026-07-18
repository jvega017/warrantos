"""provenance.extract: shared citation-trigger detection patterns and sentence splitting.

This module detects patterns that signal checkable claims (years, percentages, magnitudes,
statutes, attribution, causal language, superlatives, comparisons, etc.). Note that these
patterns are heuristic triggers, not guarantees of factuality: a sentence matching a pattern
is not necessarily true, and many factual sentences (copular claims like "Canberra is the
capital of Australia", common knowledge) do not match any pattern.

These patterns are copied from hooks/provenance_check.py, which remains the canonical
in-session tripwire. This module provides out-of-band reuse for the CLI verification
pipeline (provenance.verify, provenance.grade). If you change detection logic, update
the hook first and mirror the change here.

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
    # Statute pattern, refined in phase-1b: common words (part, act, law,
    # court, requirement, provision, article, division, schedule, clause,
    # authority) removed after precision collapse; replaced with
    # high-precision signals (pursuant to, in accordance with, gazetted,
    # enacted, repealed, amended by, prescribed). Numbered forms (s. 5,
    # section 42, Act 1988) are now case-insensitive so "Section 42" matches.
    # "under the" is restricted to a capitalised following word ("under the
    # Privacy Act") so everyday phrases ("under the couch") do not fire.
    ("statute",     re.compile(
        r"(?i:\b(?:s\.?\s?\d+|section\s\d+|Act\s(?:18|19|20)\d{2})\b)"
        r"|(?i:\b(?:regulation|legislation|statutory|code\s+section|subsection|"
        r"legislative|ordinance|statute|bill|congress|parliament|legal|judicial|"
        r"mandate|pursuant\s+to|in\s+accordance\s+with|prescribed|"
        r"gazetted|enacted|repealed|amended\s+by)s?\b)"
        r"|\b[Uu]nder\s+the\s+[A-Z]")),
    # Attribution pattern, refined in phase-1b: bare verbs (found, shown,
    # established, reported, noted, identified) removed; object-clause shapes
    # ("found that", "reported that") retained.
    ("attribution", re.compile(
        r"\b(?:according to|found that|reported that|estimated|shows that|study\b|survey\b|"
        r"data show|statistics show|stated|confirmed|revealed|disclosed|indicated|"
        r"demonstrated|concluded|cites?|determines?|assessed|evaluated|judged|"
        r"documented|verified)\b", re.I)),
    # Decision/obligation language. Closes the alignment bug where salience
    # _DECISION scores must/shall/require sentences load-bearing (0.55) but
    # extract never detected them, so they silently PASSed.
    ("decision",    re.compile(r"\b(?:must|shall|required\s+to|must\s+comply|requires?\b|recommend(?:s|ed)?)\b", re.I)),
    # Superlative claims ("the largest", "fastest", "first ever").
    ("superlative", re.compile(r"\b(?:largest|smallest|highest|lowest|fastest|slowest|best|worst|first|only|unprecedented|most|least)\b", re.I)),
    # Causal claims ("X caused Y", "led to", "as a result of").
    ("causal",      re.compile(r"\b(?:caused|causes|causing|led\s+to|leads?\s+to|results?\s+in|resulted\s+in|due\s+to|as\s+a\s+result\s+of|because\s+of|driven\s+by|attributable\s+to)\b", re.I)),
    # Numeric approximations ("around 40", "roughly 1,000", "about 12%").
    ("numeric_approx", re.compile(r"\b(?:approximately|roughly|around|about|nearly|almost|up\s+to|over|more\s+than|fewer\s+than|less\s+than)\s+\d", re.I)),
    # Named-body attribution (OECD, ABS, Treasury, ANAO and similar).
    ("named_body",  re.compile(r"\b(?:OECD|ABS|Treasury|ANAO|APSC|DTA|Productivity\s+Commission|World\s+Bank|IMF|United\s+Nations|UN|Reserve\s+Bank|RBA|Bureau\s+of\s+Statistics)\b")),
    # Empirical comparison ("more than", "compared to", "twice as", "increase of").
    ("comparison",  re.compile(r"\b(?:compared\s+(?:to|with)|relative\s+to|twice\s+as|half\s+as|\d+\s+times\s+(?:more|less|higher|lower)|increase\s+of|decrease\s+of|outperform(?:s|ed)?|higher\s+than|lower\s+than)\b", re.I)),
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
