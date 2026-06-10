"""Canonical context-admissibility API.

This module provides stable names for the Context Integrity Layer while
preserving the original ``context_admissibility`` import path.
"""

from warrantos.provenance.context_admissibility import (
    BoundaryResult,
    BoundaryViolation,
    ContextItem,
    DerivedRequirement,
    admissibility_summary,
    classify_context,
    compile_cbom,
    derive_requirement,
    scan_prose_boundary,
)

__all__ = [
    "BoundaryResult",
    "BoundaryViolation",
    "ContextItem",
    "DerivedRequirement",
    "admissibility_summary",
    "classify_context",
    "compile_cbom",
    "derive_requirement",
    "scan_prose_boundary",
]

