"""provenance.classification: Foundation row F-classification.

Data-classification sensitivity tiers for the WarrantOS foundation row.
This module gives an adopter a runtime sensitivity gate so that material
that must not leave a local boundary, or that must never be processed by
a remote model, can be detected and blocked before it enters the
pipeline.

The default registry mirrors the four-tier data gate that the reference
adopter (a public-sector policy practitioner) operates:

- **Public**: published reports, legislation, open statistics, media.
  Proceed freely.
- **Official**: working policy drafts, non-sensitive analysis, internal
  templates. Proceed (working draft only).
- **Sensitive**: Cabinet material, ministerial decisions, HR, legal
  advice, pre-release budget. STOP: do not process here.
- **Credentials**: API keys, passwords, tokens. STOP: never paste; store
  in a secrets manager.

The keyword heuristics are DELIBERATELY a starter set drawn from the
reference adopter's own classification gate. They are not a complete
classifier. A production deployment SHALL extend the registry and the
keyword lists with its own domain taxonomy. The module is honest about
this: every block carries the tier definition that fired and a note that
the heuristic is a starter.

Sensitivity classification is orthogonal to Layer 1 context
classification (`context_admissibility.classify_context`). Layer 1 asks
"what kind of context material is this and may it appear in final
prose?"; F-classification asks "is this material too sensitive to
process in this environment at all?".

Stdlib only. Python 3.8 compatible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Pattern, Tuple


# ---------------------------------------------------------------------------
# Sensitivity tier model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SensitivityTier:
    """One sensitivity classification tier.

    Attributes
    ----------
    tier_id
        Stable machine identifier (e.g. ``public``, ``sensitive``).
    name
        Human-readable tier name.
    rank
        Ordinal sensitivity. Higher means more sensitive. Used to decide
        whether a tier is at or above a block threshold.
    action
        The disposition for material at this tier (e.g. "Proceed
        freely", "STOP: do not process here").
    blocks_processing
        True when material at this tier SHALL be blocked from processing
        by the gate's default policy.
    examples
        Illustrative example material descriptions for this tier.
    """

    tier_id: str
    name: str
    rank: int
    action: str
    blocks_processing: bool = False
    examples: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "tier_id": self.tier_id,
            "name": self.name,
            "rank": self.rank,
            "action": self.action,
            "blocks_processing": self.blocks_processing,
            "examples": list(self.examples),
        }


# ---------------------------------------------------------------------------
# Default four-tier registry (reference adopter data gate)
# ---------------------------------------------------------------------------

TIER_PUBLIC = SensitivityTier(
    tier_id="public",
    name="Public",
    rank=0,
    action="Proceed freely.",
    blocks_processing=False,
    examples=[
        "Published reports",
        "Legislation",
        "Open statistics (OECD / ABS)",
        "Media",
    ],
)

TIER_OFFICIAL = SensitivityTier(
    tier_id="official",
    name="Official",
    rank=1,
    action="Proceed (working draft only).",
    blocks_processing=False,
    examples=[
        "Working policy drafts",
        "Non-sensitive analysis",
        "Internal templates",
    ],
)

TIER_SENSITIVE = SensitivityTier(
    tier_id="sensitive",
    name="Sensitive / Protected",
    rank=2,
    action="STOP: do not process here.",
    blocks_processing=True,
    examples=[
        "Cabinet material",
        "Ministerial decisions",
        "HR / personnel matters",
        "Legal advice",
        "Pre-release budget figures",
    ],
)

TIER_CREDENTIALS = SensitivityTier(
    tier_id="credentials",
    name="Credentials",
    rank=3,
    action="STOP: never paste; store in a secrets manager only.",
    blocks_processing=True,
    examples=[
        "API keys",
        "Passwords",
        "Tokens",
    ],
)

# The default registry, ordered from least to most sensitive.
DEFAULT_TIERS: Tuple[SensitivityTier, ...] = (
    TIER_PUBLIC,
    TIER_OFFICIAL,
    TIER_SENSITIVE,
    TIER_CREDENTIALS,
)


# ---------------------------------------------------------------------------
# Keyword heuristics (starter set)
# ---------------------------------------------------------------------------
#
# DELIBERATELY a starter set. A production deployment SHALL extend these
# patterns with its own domain taxonomy. Each pattern maps a rule id to a
# (tier_id, compiled-pattern) pair. The classifier returns the highest-rank
# tier whose pattern fires.

# Sensitive-tier markers (public-sector reference gate).
_SENSITIVE_PATTERNS: Tuple[Tuple[str, Pattern], ...] = (
    ("cabinet", re.compile(r"\bcabinet(?:[- ]in[- ]confidence)?\b", re.I)),
    ("ministerial", re.compile(r"\bminister(?:ial)?\b", re.I)),
    ("legal_advice", re.compile(r"\blegal\s+advice\b", re.I)),
    ("crown_solicitor", re.compile(r"\bcrown\s+solicitor\b", re.I)),
    ("without_prejudice", re.compile(r"\bwithout\s+prejudice\b", re.I)),
    # HR / personnel markers.
    ("hr_pip", re.compile(r"\b(?:PIP|performance\s+improvement\s+plan)\b", re.I)),
    ("hr_termination", re.compile(r"\btermination\b", re.I)),
    ("hr_investigation", re.compile(r"\b(?:HR\s+)?investigation\b", re.I)),
    # Unpublished budget figures: $NNN[.N]M or $NNN[.N]B markers. The
    # heuristic treats any $-prefixed million/billion figure as a
    # potential pre-release budget marker; a production deployment can
    # narrow this to "unpublished" contexts.
    ("budget_figure", re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:M|B|million|billion)\b", re.I)),
)

# Credentials-tier markers.
_CREDENTIAL_PATTERNS: Tuple[Tuple[str, Pattern], ...] = (
    ("api_key_assignment", re.compile(
        r"\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd|bearer)\b\s*[:=]",
        re.I,
    )),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I)),
)


@dataclass(frozen=True)
class ClassificationMatch:
    """A single sensitivity-pattern hit."""

    rule_id: str
    tier_id: str
    matched_text: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "tier_id": self.tier_id,
            "matched_text": self.matched_text,
        }


@dataclass(frozen=True)
class ClassificationResult:
    """Result of a sensitivity classification over a text.

    Attributes
    ----------
    tier
        The highest-rank tier that fired. When nothing matched, the
        default floor tier (Official) is returned: in a working
        environment text whose sensitivity could not be lowered to
        Public is treated as Official, not silently Public.
    matches
        All pattern hits, across every tier.
    corpus_completeness
        Always ``starter``: the keyword heuristics are a starter set.
    """

    tier: SensitivityTier
    matches: List[ClassificationMatch]
    corpus_completeness: str = "starter"

    @property
    def blocks_processing(self) -> bool:
        return self.tier.blocks_processing

    def to_dict(self) -> Dict[str, object]:
        return {
            "tier": self.tier.to_dict(),
            "matches": [m.to_dict() for m in self.matches],
            "corpus_completeness": self.corpus_completeness,
            "blocks_processing": self.blocks_processing,
            "note": (
                "Sensitivity keyword heuristics are a starter set drawn "
                "from the reference adopter's data gate. Production "
                "deployments SHALL extend the registry and patterns with "
                "their own domain taxonomy. A 'public' verdict is only "
                "returned when the floor tier is explicitly Public; "
                "unmatched text defaults to Official, never silently Public."
            ),
        }


def classify_sensitivity(
    text: str,
    *,
    tiers: Optional[Tuple[SensitivityTier, ...]] = None,
    floor: Optional[SensitivityTier] = None,
) -> ClassificationResult:
    """Classify text into a sensitivity tier using the keyword heuristics.

    Returns the highest-rank tier whose pattern fires. When no pattern
    fires, returns the ``floor`` tier (default: Official), because in a
    working environment unmatched text is treated as Official, never
    silently Public.

    Parameters
    ----------
    text
        The material to classify.
    tiers
        Optional tier registry. Defaults to ``DEFAULT_TIERS``.
    floor
        Optional default tier when nothing matches. Defaults to the
        Official tier from ``DEFAULT_TIERS``.
    """
    registry = tiers if tiers is not None else DEFAULT_TIERS
    by_id = {t.tier_id: t for t in registry}
    floor_tier = floor if floor is not None else by_id.get("official", registry[0])

    matches: List[ClassificationMatch] = []
    if text:
        for rule_id, pattern in _CREDENTIAL_PATTERNS:
            hit = pattern.search(text)
            if hit:
                matches.append(ClassificationMatch(
                    rule_id=rule_id, tier_id="credentials",
                    matched_text=hit.group(0)[:80],
                ))
        for rule_id, pattern in _SENSITIVE_PATTERNS:
            hit = pattern.search(text)
            if hit:
                matches.append(ClassificationMatch(
                    rule_id=rule_id, tier_id="sensitive",
                    matched_text=hit.group(0)[:80],
                ))

    # Pick the highest-rank tier among the fired matches.
    chosen = floor_tier
    for m in matches:
        tier = by_id.get(m.tier_id)
        if tier is not None and tier.rank > chosen.rank:
            chosen = tier

    return ClassificationResult(tier=chosen, matches=matches)


# ---------------------------------------------------------------------------
# Sensitivity gate
# ---------------------------------------------------------------------------

class SensitivityBlock(Exception):
    """Raised when material at or above the block threshold is detected.

    Fail-closed: the gate raises rather than returning a soft verdict so
    that a caller cannot accidentally process blocked material by
    ignoring a return value.
    """

    def __init__(self, result: ClassificationResult):
        self.result = result
        rule_ids = ", ".join(sorted({m.rule_id for m in result.matches})) or "(none)"
        super().__init__(
            "Sensitivity gate BLOCKED processing: material classified as "
            "'%s' (rank %d). Triggering rules: %s. Action: %s"
            % (
                result.tier.name,
                result.tier.rank,
                rule_ids,
                result.tier.action,
            )
        )


def gate_sensitivity(
    text: str,
    *,
    tiers: Optional[Tuple[SensitivityTier, ...]] = None,
    floor: Optional[SensitivityTier] = None,
) -> ClassificationResult:
    """Classify text and raise SensitivityBlock if it must not be processed.

    Returns the ClassificationResult when the material is admissible
    (its tier does not block processing). Raises ``SensitivityBlock``
    when the classified tier has ``blocks_processing=True``.

    This is the fail-closed gate the CLI ``--sensitivity-check`` flag
    uses.
    """
    result = classify_sensitivity(text, tiers=tiers, floor=floor)
    if result.tier.blocks_processing:
        raise SensitivityBlock(result)
    return result
