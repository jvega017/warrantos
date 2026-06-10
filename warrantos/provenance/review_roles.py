"""provenance.review_roles: review-role registry and detection for SPEC-L1-S005.

A `review_finding`-shaped input from an agent in the documented review-role
registry SHALL NOT be silently reclassified to `private_reasoning`
(SPEC-L1-S005). This module provides:

- REVIEW_ROLE_REGISTRY: the canonical tuple of agent names whose output
  defaults to `review_finding` at Layer 1.
- is_review_role_output(): the detection heuristic. The authoritative
  signal is the caller's source_agent argument; text patterns are a
  best-effort secondary signal when source_agent is unknown.

The registry is implementation-declared per SPEC-L1-S005. The names below
match the agent type strings used in Juan Vega's workspace and in the
WarrantOS Wave A QA convergence note dated 2026-05-26.

Stdlib only. Python 3.8 compatible.
"""

import re
from typing import Optional, Tuple


REVIEW_ROLE_REGISTRY: Tuple[str, ...] = (
    "fresh-critic",
    "evidence-auditor",
    "policy-red-team",
    "paper-editor",
    "codex-rescue",
    "policy-debate",
    "claim-verify",
    "rejection-handler",
)


# Heuristic patterns that indicate the input is the output of a review-role
# agent. These are intentionally narrow; the authoritative signal is the
# source_agent kwarg, not the text. Text-only detection is "better than
# nothing" for callers who do not know the source.

_FINDING_ID_RE = re.compile(r"\b(?:A|F|P|C|R|E)[0-9]{1,3}\b")
_SEVERITY_LINE_RE = re.compile(r"^\s*[*-]?\s*\*?\*?Severity[* ]*:\s*P[0-9]\b", re.I | re.M)
_REVIEWER_HEADER_RE = re.compile(
    r"^#+\s*(?:Attacker thesis|Critique|Review|Findings?|Convergence|Verdict|Red-?[Tt]eam)\b",
    re.M,
)
_AGENT_NAME_RE = re.compile(
    r"\b(?:fresh-?critic|evidence-?auditor|policy-?red-?team|paper-?editor|codex-?rescue|policy-?debate|claim-?verify|rejection-?handler)\b",
    re.I,
)


def is_review_role_output(text: str, source_agent: Optional[str] = None) -> bool:
    """Return True when the input is the output of a review-role agent.

    Decision order:

    1. If source_agent is provided and is in REVIEW_ROLE_REGISTRY (case
       insensitive, hyphen-normalised), return True. This is the
       authoritative signal.
    2. Otherwise, apply text heuristics: finding-id token, Severity:
       P0/P1/P2 line, review-style section header, or self-naming as a
       registered agent. Two or more heuristic signals must fire.
    3. Otherwise, return False.

    The two-signal rule for text-only detection reduces false positives
    from policy or paper content that happens to contain one severity
    label or one finding id.
    """
    if source_agent and _normalise_agent_name(source_agent) in {
        _normalise_agent_name(name) for name in REVIEW_ROLE_REGISTRY
    }:
        return True

    if not text:
        return False

    signals = 0
    if _FINDING_ID_RE.search(text):
        signals += 1
    if _SEVERITY_LINE_RE.search(text):
        signals += 1
    if _REVIEWER_HEADER_RE.search(text):
        signals += 1
    if _AGENT_NAME_RE.search(text):
        signals += 1

    return signals >= 2


def _normalise_agent_name(name: str) -> str:
    """Lowercase and collapse hyphens for source_agent comparison."""
    if not name:
        return ""
    return re.sub(r"[-_\s]+", "-", name.strip().lower())
