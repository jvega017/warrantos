"""Context Bill of Materials helpers for WarrantOS review packs.

The CBOM records what context entered an artefact, how it was transformed,
which material was admitted or blocked, which claims rely on it, and which
review findings remain attached to the artefact.

Stdlib only. Python 3.8 compatible.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class ContextInput:
    """A context item considered for use in an artefact."""

    context_id: str
    text: str
    source: str = ""
    material_type: str = "context"
    admitted: bool = True
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "context_id": self.context_id,
            "text": self.text,
            "source": self.source,
            "material_type": self.material_type,
            "admitted": self.admitted,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TransformationRecord:
    """A transformation from one or more context inputs to an output."""

    transform_id: str
    input_ids: List[str]
    output_id: str
    kind: str
    description: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "transform_id": self.transform_id,
            "input_ids": list(self.input_ids),
            "output_id": self.output_id,
            "kind": self.kind,
            "description": self.description,
        }


@dataclass(frozen=True)
class ClaimRecord:
    """A claim carried by the artefact and its supporting material."""

    claim_id: str
    text: str
    support_ids: List[str] = field(default_factory=list)
    status: str = "unreviewed"

    def to_dict(self) -> Dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "support_ids": list(self.support_ids),
            "status": self.status,
        }


@dataclass(frozen=True)
class ReviewFindingRecord:
    """A review finding attached to the CBOM."""

    finding_id: str
    severity: str
    title: str
    disposition: str = "distinct"

    def to_dict(self) -> Dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "title": self.title,
            "disposition": self.disposition,
        }


@dataclass(frozen=True)
class ClassificationOverrideRecord:
    """A Layer 1 classification override per SPEC-L1-S005.

    Recorded when a review-role agent output is classified as something
    other than `review_finding`, or when any classification deviates from
    the default classifier verdict. The override row points back to a
    human_override ledger row via `override_id`.
    """

    context_id: str
    classified_as: str
    default_would_be: str
    override_id: str
    override_rationale_summary: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "context_id": self.context_id,
            "classified_as": self.classified_as,
            "default_would_be": self.default_would_be,
            "override_id": self.override_id,
            "override_rationale_summary": self.override_rationale_summary,
        }


@dataclass(frozen=True)
class CBOM:
    """A serialisable WarrantOS Context Bill of Materials.

    SPEC-v0.2 additions (additive per INV-007 schema stability):

    - `actor_identity` (SPEC-F-S002): map from role name to actor identity
      string. Required for `context_classifier`, `insight_compiler`,
      `source_curator`, `clean_room_writer`, `reviewer_qa`, `auditor`.
      Identity may be user name, API key id, model identifier, or tuple.
    - `classification_overrides` (SPEC-L1-S005): list of every Layer 1
      classification override recorded for this run.
    - `override_ledger_refs` (SPEC O-S004 supporting field): pointers by id
      to every override ledger row associated with the run.

    All three fields default to empty for backwards compatibility with
    callers from before SPEC-v0.2. The canonical schema name remains
    `warrantos-cbom/v1` per INV-007 (additive change only).
    """

    artefact_id: str
    context_inputs: List[ContextInput]
    transformations: List[TransformationRecord]
    claims: List[ClaimRecord]
    review_findings: List[ReviewFindingRecord]
    schema: str = "warrantos-cbom/v1"
    actor_identity: Dict[str, str] = field(default_factory=dict)
    classification_overrides: List[ClassificationOverrideRecord] = field(default_factory=list)
    override_ledger_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        admitted = [item for item in self.context_inputs if item.admitted]
        blocked = [item for item in self.context_inputs if not item.admitted]
        return {
            "schema": self.schema,
            "artefact_id": self.artefact_id,
            "summary": {
                "context_inputs": len(self.context_inputs),
                "admitted_material": len(admitted),
                "blocked_material": len(blocked),
                "transformations": len(self.transformations),
                "claims": len(self.claims),
                "review_findings": len(self.review_findings),
                "classification_overrides": len(self.classification_overrides),
                "override_ledger_refs": len(self.override_ledger_refs),
            },
            "context_inputs": [item.to_dict() for item in self.context_inputs],
            "admitted_material": [item.to_dict() for item in admitted],
            "blocked_material": [item.to_dict() for item in blocked],
            "transformations": [item.to_dict() for item in self.transformations],
            "claims": [item.to_dict() for item in self.claims],
            "review_findings": [item.to_dict() for item in self.review_findings],
            "actor_identity": dict(self.actor_identity),
            "classification_overrides": [item.to_dict() for item in self.classification_overrides],
            "override_ledger_refs": list(self.override_ledger_refs),
        }


def build_cbom(
    context_inputs: Optional[Iterable[ContextInput]] = None,
    transformations: Optional[Iterable[TransformationRecord]] = None,
    claims: Optional[Iterable[ClaimRecord]] = None,
    review_findings: Optional[Iterable[ReviewFindingRecord]] = None,
    artefact_id: str = "",
    actor_identity: Optional[Dict[str, str]] = None,
    classification_overrides: Optional[Iterable[ClassificationOverrideRecord]] = None,
    override_ledger_refs: Optional[Iterable[str]] = None,
) -> CBOM:
    """Build and validate a CBOM.

    SPEC-v0.2 additions (`actor_identity`, `classification_overrides`,
    `override_ledger_refs`) are accepted as optional kwargs with empty
    defaults. Existing v0.1 callers continue to work unchanged.
    """
    input_list = list(context_inputs or [])
    transform_list = list(transformations or [])
    claim_list = list(claims or [])
    finding_list = list(review_findings or [])
    actor_map = dict(actor_identity or {})
    override_list = list(classification_overrides or [])
    override_refs = list(override_ledger_refs or [])

    _validate_references(input_list, transform_list, claim_list)
    _validate_classification_overrides(override_list, input_list)
    return CBOM(
        artefact_id=artefact_id,
        context_inputs=input_list,
        transformations=transform_list,
        claims=claim_list,
        review_findings=finding_list,
        actor_identity=actor_map,
        classification_overrides=override_list,
        override_ledger_refs=override_refs,
    )


def _validate_classification_overrides(
    overrides: List[ClassificationOverrideRecord],
    context_inputs: List[ContextInput],
) -> None:
    """Validate that every classification override refers to a known context_id.

    The override_id is a free-form pointer to a human_override ledger row
    that lives outside the CBOM; we cannot validate that reference here.
    SPEC-L1-S005 enforcement that the override exists with non-empty
    risk_accepted / compensating_control happens at the override-ledger
    layer, not in CBOM assembly.
    """
    if not overrides:
        return
    known_ids = {item.context_id for item in context_inputs}
    for override in overrides:
        if override.context_id not in known_ids:
            raise ValueError(
                "classification override %s references unknown context_id: %s"
                % (override.override_id, override.context_id)
            )
        if not override.override_id:
            raise ValueError(
                "classification override for context_id %s has empty override_id"
                % override.context_id
            )


def _validate_references(
    context_inputs: List[ContextInput],
    transformations: List[TransformationRecord],
    claims: List[ClaimRecord],
) -> None:
    known_ids = {item.context_id for item in context_inputs}
    admitted_ids = {item.context_id for item in context_inputs if item.admitted}

    for transform in transformations:
        missing = [input_id for input_id in transform.input_ids if input_id not in known_ids]
        if missing:
            raise ValueError(
                "transformation %s references unknown context input(s): %s"
                % (transform.transform_id, ", ".join(missing))
            )

    for claim in claims:
        missing = [support_id for support_id in claim.support_ids if support_id not in known_ids]
        if missing:
            raise ValueError(
                "claim %s references unknown support input(s): %s"
                % (claim.claim_id, ", ".join(missing))
            )
        blocked = [support_id for support_id in claim.support_ids if support_id not in admitted_ids]
        if blocked:
            raise ValueError(
                "claim %s references blocked support input(s): %s"
                % (claim.claim_id, ", ".join(blocked))
            )
