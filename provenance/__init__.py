"""provenance: out-of-band claim verification for claude-provenance.

This package provides the v1 verification pipeline: URL fetching, heuristic
and LLM grading, and batch text analysis. It is called by the CLI, never
by the hook. The hook (hooks/provenance_check.py) remains stdlib-only and
does no network I/O.

Public API:

    from provenance.grade import Verdict, HeuristicGrader, LLMGrader, get_grader
    from provenance.verify import fetch_text, extract_citation, verify_claim, verify_text
    from provenance.extract import CLAIM_TRIGGERS, CITATION_MARKERS, CITE_NEEDED, sentences
"""

from provenance.grade import (
    HeuristicGrader,
    LLMGrader,
    Verdict,
    get_grader,
)
from provenance.verify import (
    extract_citation,
    fetch_text,
    verify_claim,
    verify_text,
)

__all__ = [
    "Verdict",
    "HeuristicGrader",
    "LLMGrader",
    "get_grader",
    "fetch_text",
    "extract_citation",
    "verify_claim",
    "verify_text",
]
