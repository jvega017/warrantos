"""provenance: out-of-band claim verification for claude-provenance.

This package provides the v1 verification pipeline: URL fetching, heuristic
and LLM grading, and batch text analysis. It is called by the CLI, never
by the hook. The hook (hooks/provenance_check.py) remains stdlib-only and
does no network I/O.

Public API:

    from warrantos.provenance.grade import Verdict, HeuristicGrader, LLMGrader, get_grader
    from warrantos.provenance.verify import fetch_text, extract_citation, verify_claim, verify_text
    from warrantos.provenance.extract import CLAIM_TRIGGERS, CITATION_MARKERS, CITE_NEEDED, sentences
    from warrantos.provenance.context_admissibility import classify_context, scan_prose_boundary, compile_cbom
    from warrantos.provenance.boundary import check_boundary
"""

from warrantos.provenance.grade import (
    HeuristicGrader,
    LLMGrader,
    Verdict,
    get_grader,
)
from warrantos.provenance.verify import (
    extract_citation,
    fetch_text,
    verify_claim,
    verify_text,
)
from warrantos.provenance.context_admissibility import (
    BoundaryResult,
    BoundaryViolation,
    ContextItem,
    DerivedRequirement,
    classify_context,
    compile_cbom,
    derive_requirement,
    scan_prose_boundary,
)
from warrantos.provenance.boundary import check_boundary

__all__ = [
    "Verdict",
    "HeuristicGrader",
    "LLMGrader",
    "get_grader",
    "fetch_text",
    "extract_citation",
    "verify_claim",
    "verify_text",
    "ContextItem",
    "DerivedRequirement",
    "BoundaryViolation",
    "BoundaryResult",
    "classify_context",
    "derive_requirement",
    "scan_prose_boundary",
    "check_boundary",
    "compile_cbom",
]
