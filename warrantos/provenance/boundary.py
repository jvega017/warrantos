"""Reusable prose-boundary gate for final artefacts.

The boundary gate is the BriefLock reference control inside WarrantOS. It
does not decide whether a claim is true. It decides whether process material
has leaked into reader-facing prose instead of being transformed into an
admissible requirement, claim, style rule, or audit record.
"""

from warrantos.provenance.context_admissibility import (
    BoundaryResult,
    BoundaryViolation,
    scan_prose_boundary,
)


def check_boundary(text, profile="final-prose"):
    """Return a BoundaryResult for the requested output profile."""
    return scan_prose_boundary(text, artefact_role=profile)


__all__ = ["BoundaryResult", "BoundaryViolation", "check_boundary"]

