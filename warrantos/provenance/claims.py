"""Claim status semantics and constants for WarrantOS.

This module defines the claim status state machine that distinguishes between
citation presence (cited/uncited) and verification result (supported/contradicted).

The critical distinction: a cited claim may still be contradicted by the verifier.
Citation presence alone does not imply verification success.

Semantics (Phase 1 fix M1):

    UNCITED
        No citation token present in the text. The claim lacks supporting material.
        → Status: unverified (no input to verifier)
        → Verdict trigger: unsupported load-bearing claims HOLD

    CITED_UNVERIFIED
        Citation token present but verification has not run. The claim has a citation
        anchor but we don't yet know if the cited material supports the claim.
        → Status: awaiting verification
        → Verdict trigger: none (no load-bearing HOLD; verifier runs next)

    SUPPORTED
        Verifier confirmed that the cited material supports the claim.
        → Status: verified, claim approved
        → Verdict trigger: none (supports PASS)

    CONTRADICTED
        Verifier found contradiction between claim and cited material.
        → Status: verified, claim rejected
        → Verdict trigger: BLOCK (fatal)

    UNVERIFIABLE
        Citation present but cannot verify (network offline, URL missing, etc).
        → Status: verification failed
        → Verdict trigger: HOLD if load-bearing

The state machine:
    - Initial state: UNCITED (no citation) or CITED_UNVERIFIED (has citation)
    - Verifier overwrites CITED_UNVERIFIED → SUPPORTED | CONTRADICTED | UNVERIFIABLE
    - UNCITED never transitions (remains uncited unless citation is added)

Report keys (per-profile):
    - `claims_cited`: count of claims with citations (CITED_UNVERIFIED + SUPPORTED + CONTRADICTED + UNVERIFIABLE)
    - `claims_uncited`: count of claims without citations (UNCITED)
"""

from enum import Enum


class ClaimStatus(Enum):
    """Enumeration of claim verification states (Phase 1 fix M1)."""

    UNCITED = "uncited"
    """No citation present. Claim lacks supporting material anchor."""

    CITED_UNVERIFIED = "cited_unverified"
    """Citation present, verification not yet run. Claim has an anchor but we don't know
    if the cited material supports it."""

    SUPPORTED = "supported"
    """Verifier confirmed the cited material supports the claim."""

    CONTRADICTED = "contradicted"
    """Verifier found contradiction. The claim contradicts the cited material."""

    UNVERIFIABLE = "unverifiable"
    """Citation present but cannot verify (network error, missing resource, etc).
    Treated as HOLD for load-bearing claims but otherwise allows review override."""

    def __str__(self) -> str:
        return self.value


# Report key mapping: group claims by their cited/uncited status
# (independent of verifier verdict)
def get_report_status_key(status: str) -> str:
    """Map a claim status to its report category.

    Returns:
        "cited" if the claim has a citation (regardless of verification result)
        "uncited" if the claim has no citation
    """
    cited_statuses = {
        ClaimStatus.CITED_UNVERIFIED.value,
        ClaimStatus.SUPPORTED.value,
        ClaimStatus.CONTRADICTED.value,
        ClaimStatus.UNVERIFIABLE.value,
    }
    if status in cited_statuses:
        return "cited"
    return "uncited"
