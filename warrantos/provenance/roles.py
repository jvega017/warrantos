"""provenance.roles: machine-readable WarrantOS actor-role registry (SPEC-F-S002).

This module is the single runtime source of truth for the six WarrantOS
actor roles that the CBOM `actor_identity` field is keyed on
(SPEC-F-S002). Before this module existed the six roles were documented
only in prose (docs/STACK.md) and embedded in the `cbom.py` docstring; a
caller had no programmatic way to enumerate them, validate an
`actor_identity` map, or render the taxonomy. This module closes that gap
for Foundation row F-policy.

Scope and honesty
-----------------
- The six roles below are the SPEC-F-S002 *actor* taxonomy: the
  accountable functional roles that the CBOM `actor_identity` map is
  required to carry. They are coarse-grained accountability roles, not
  the finer-grained per-item *viewer* identities used inside the Layer 4
  admissibility flags (`can_be_seen_by` / `cannot_be_seen_by`), which
  include additional internal viewer strings such as `ledger_writer`,
  `boundary_gate`, `final_writer`, `semantic_reviewer` and
  `revision_planner`. `VIEWER_IDENTITIES` documents that wider set so the
  relationship is auditable and not silently conflated.
- This registry is a data declaration plus validation helpers. It does
  NOT enforce separation of duties (that is `overrides.enforce_single_actor_rule`,
  SPEC-L8-S003) and it does NOT itself decide admissibility (that is
  `context_admissibility` / `writer_pack`, SPEC-L4-S001). It is the
  enumerable taxonomy those modules reference.

Stdlib only. Python 3.8 compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Tuple


@dataclass(frozen=True)
class ActorRole:
    """One WarrantOS actor role in the SPEC-F-S002 taxonomy.

    Attributes
    ----------
    role_id
        The canonical machine key used in the CBOM `actor_identity` map.
    title
        Human-readable role title.
    layer
        The architecture layer the role is principally accountable for.
    responsibility
        One-line statement of what the role is accountable for.
    spec_refs
        SPEC-IDs whose enforcement this role participates in.
    identity_examples
        Example forms the actor identity string may take (user name,
        API key id, model identifier, or a tuple thereof).
    """

    role_id: str
    title: str
    layer: str
    responsibility: str
    spec_refs: Tuple[str, ...] = field(default_factory=tuple)
    identity_examples: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, object]:
        return {
            "role_id": self.role_id,
            "title": self.title,
            "layer": self.layer,
            "responsibility": self.responsibility,
            "spec_refs": list(self.spec_refs),
            "identity_examples": list(self.identity_examples),
        }


# ---------------------------------------------------------------------------
# The six canonical actor roles (SPEC-F-S002).
#
# Order is significant: it follows the artefact lifecycle from context
# intake (context_classifier) through to post-hoc audit (auditor). The
# role_id strings match the keys required on CBOM.actor_identity exactly
# (see cbom.py CBOM docstring and SPEC-F-S002).
# ---------------------------------------------------------------------------
ACTOR_ROLES: Tuple[ActorRole, ...] = (
    ActorRole(
        role_id="context_classifier",
        title="Context Classifier",
        layer="L1",
        responsibility=(
            "Classifies every incoming context item into one of the "
            "eleven canonical classes and applies review-role gating."
        ),
        spec_refs=("SPEC-L1-S005",),
        identity_examples=("model-identifier", "rule-engine-version"),
    ),
    ActorRole(
        role_id="insight_compiler",
        title="Applied Insight Compiler",
        layer="L3",
        responsibility=(
            "Transforms admitted process material into structured derived "
            "requirements before any writer sees it, and persists the "
            "transform to the ledger."
        ),
        spec_refs=("SPEC-L3-N001", "SPEC-L4-S004"),
        identity_examples=("model-identifier", "rule-engine-version"),
    ),
    ActorRole(
        role_id="source_curator",
        title="Source Curator",
        layer="L4",
        responsibility=(
            "Decides which admitted context items are approved as sources "
            "for the writer pack and which actors may see each item."
        ),
        spec_refs=("SPEC-L4-S001",),
        identity_examples=("user-name", "model-identifier"),
    ),
    ActorRole(
        role_id="clean_room_writer",
        title="Clean-Room Writer",
        layer="L5/L6",
        responsibility=(
            "Generates the artefact seeing only the writer pack; runs in "
            "discipline mode (or subprocess isolation) so no out-of-band "
            "context reaches it."
        ),
        spec_refs=("SPEC-L4-S001", "SPEC-L6-S001", "SPEC-L6-R001"),
        identity_examples=("model-identifier",),
    ),
    ActorRole(
        role_id="reviewer_qa",
        title="Reviewer / QA",
        layer="L7/L8",
        responsibility=(
            "Runs the output integrity gates and records the human review "
            "decision; SHALL be a different actor from the writer when an "
            "override is recorded (separation of duties)."
        ),
        spec_refs=("SPEC-L7-S003", "SPEC-L8-S003", "SPEC-L8-S004"),
        identity_examples=("user-name", "model-identifier"),
    ),
    ActorRole(
        role_id="auditor",
        title="Auditor",
        layer="F-audit",
        responsibility=(
            "Reads the append-only ledger, CBOM, and override footer after "
            "the fact; never writes runtime artefacts."
        ),
        spec_refs=("INV-004", "SPEC-L8-S005"),
        identity_examples=("user-name",),
    ),
)


# The exact set of role_id keys required on CBOM.actor_identity per
# SPEC-F-S002. Kept as a frozenset for O(1) membership checks.
REQUIRED_ACTOR_ROLE_IDS: frozenset = frozenset(r.role_id for r in ACTOR_ROLES)


# Finer-grained per-item VIEWER identities used inside the Layer 4
# admissibility flags. These are NOT the SPEC-F-S002 actor roles; they
# are the internal viewer strings the classifier writes into
# `can_be_seen_by` / `cannot_be_seen_by`. Documented here so the two
# vocabularies are not silently conflated. This list is descriptive of
# the strings the code emits today, not normative.
VIEWER_IDENTITIES: Tuple[str, ...] = (
    "context_classifier",
    "semantic_reviewer",
    "ledger_writer",
    "clean_room_writer",
    "final_writer",
    "auditor",
    "boundary_gate",
    "revision_planner",
)


def role_ids() -> Tuple[str, ...]:
    """Return the six canonical actor-role ids in lifecycle order."""
    return tuple(r.role_id for r in ACTOR_ROLES)


def get_role(role_id: str) -> ActorRole:
    """Return the ActorRole for a role_id.

    Raises
    ------
    KeyError
        If role_id is not one of the six canonical roles.
    """
    for r in ACTOR_ROLES:
        if r.role_id == role_id:
            return r
    raise KeyError("unknown actor role_id: %r" % (role_id,))


def is_actor_role(role_id: str) -> bool:
    """Return True if role_id is one of the six canonical actor roles."""
    return role_id in REQUIRED_ACTOR_ROLE_IDS


def validate_actor_identity(actor_identity: Mapping[str, str]) -> List[str]:
    """Validate a CBOM `actor_identity` map against SPEC-F-S002.

    Returns a list of human-readable problems; an empty list means the
    map names all six required roles with non-empty identities and
    introduces no unknown role keys.

    SPEC-F-S002 requires the six roles be present. This is the runtime
    check that was missing before the role registry existed.
    """
    problems: List[str] = []
    present = set(actor_identity or {})

    missing = REQUIRED_ACTOR_ROLE_IDS - present
    for role_id in sorted(missing):
        problems.append("SPEC-F-S002: missing actor role %r" % (role_id,))

    for role_id in sorted(present):
        if role_id not in REQUIRED_ACTOR_ROLE_IDS:
            problems.append("unknown actor role key %r (not in SPEC-F-S002 taxonomy)" % (role_id,))
            continue
        value = actor_identity.get(role_id)
        if value is None or not str(value).strip():
            problems.append("SPEC-F-S002: actor role %r has empty identity" % (role_id,))

    return problems


def registry_to_dict() -> Dict[str, object]:
    """Return the full registry as a JSON-serialisable dict.

    Schema name is stable (`warrantos-roles/v1`) so a downstream auditor
    or the status report can rely on it.
    """
    return {
        "schema": "warrantos-roles/v1",
        "spec_ref": "SPEC-F-S002",
        "actor_roles": [r.to_dict() for r in ACTOR_ROLES],
        "required_actor_role_ids": sorted(REQUIRED_ACTOR_ROLE_IDS),
        "viewer_identities": list(VIEWER_IDENTITIES),
    }
