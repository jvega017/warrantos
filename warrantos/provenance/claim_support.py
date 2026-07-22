"""Content-addressed claim-to-passage evidence without pretending truth.

Standalone WarrantOS can reproduce exact artefact/source bytes, locators and
passage digests.  That result is ``passage_reproduced``: it is evidence that
the addressed material is stable, not evidence that the source semantically
supports the claim.

Legacy callers may still pass ``reviewer`` and ``semantic_verdict`` to
``verify_binding``.  Those unauthenticated strings are deliberately ignored
and can never mint ``support_verified``.  A host that confers a semantic state
must do so through its own authenticated, hash-bound proof protocol; WarrantOS
does not currently implement or validate such a proof.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Mapping, Optional

class ClaimSupportState(str, Enum):
    CITATION_PRESENT = "citation_present"
    SOURCE_RESOLVED = "source_resolved"
    PASSAGE_LOCATED = "passage_located"
    SUPPORT_ASSERTED = "support_asserted"
    PASSAGE_REPRODUCED = "passage_reproduced"
    SUPPORT_VERIFIED = "support_verified"
    SUPPORT_CONTESTED = "support_contested"
    CONTRADICTED = "contradicted"

SUPPORT_STATES = tuple(state.value for state in ClaimSupportState)

def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

def sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()

def state_for_legacy_claim(status: str, citation: Optional[str] = None) -> Optional[str]:
    """Map legacy ``supported`` to its honest citation-only ceiling."""
    if citation or status == "supported":
        return ClaimSupportState.CITATION_PRESENT.value
    return None

@dataclass(frozen=True)
class SourceSnapshot:
    source_snapshot_id: str
    canonical_uri: str
    retrieved_at: str
    content_sha256: str
    media_type: str = "application/octet-stream"
    published_at: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    extraction_sha256: Optional[str] = None
    publisher: str = ""
    authority_class: str = "unclassified"
    classification: str = "Official"
    schema: str = "warrantos-source-manifest/v1"
    def __post_init__(self) -> None:
        _require_id(self.source_snapshot_id, "source_snapshot_id")
        _require_id(self.canonical_uri, "canonical_uri")
        _require_id(self.retrieved_at, "retrieved_at")
        _require_digest(self.content_sha256, "content_sha256")
        if self.extraction_sha256 is not None:
            _require_digest(self.extraction_sha256, "extraction_sha256")
    def to_dict(self) -> Dict[str, object]:
        return dict(self.__dict__)

@dataclass(frozen=True)
class SupportLink:
    source_snapshot_id: str
    relation: str
    locator: Dict[str, object] = field(default_factory=dict)
    quoted_span_sha256: Optional[str] = None
    verdict: Optional[str] = None
    confidence: Optional[float] = None
    def __post_init__(self) -> None:
        _require_id(self.source_snapshot_id, "source_snapshot_id")
        if self.quoted_span_sha256 is not None:
            _require_digest(self.quoted_span_sha256, "quoted_span_sha256")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
    def to_dict(self) -> Dict[str, object]:
        return {"source_snapshot_id": self.source_snapshot_id, "relation": self.relation,
                "locator": dict(self.locator), "quoted_span_sha256": self.quoted_span_sha256,
                "verdict": self.verdict, "confidence": self.confidence}

@dataclass(frozen=True)
class ClaimBinding:
    binding_id: str
    claim_id: str
    artefact_revision: str
    support_state: str
    supports: List[SupportLink] = field(default_factory=list)
    assertion_id: Optional[str] = None
    created_by: str = ""
    reviewed_by: Optional[str] = None
    created_at: str = ""
    claim_text_sha256: Optional[str] = None
    claim_locator: Dict[str, object] = field(default_factory=dict)
    schema: str = "warrantos-claim-binding/v1"
    def __post_init__(self) -> None:
        _require_id(self.binding_id, "binding_id")
        _require_id(self.claim_id, "claim_id")
        _require_digest(self.artefact_revision, "artefact_revision")
        if self.claim_text_sha256 is not None:
            _require_digest(self.claim_text_sha256, "claim_text_sha256")
        if self.support_state not in SUPPORT_STATES:
            raise ValueError("unknown support_state: %s" % self.support_state)
        if self.support_state != ClaimSupportState.CITATION_PRESENT.value and not self.supports:
            raise ValueError("%s requires at least one source link" % self.support_state)
        passage_states = {
            ClaimSupportState.PASSAGE_LOCATED.value,
            ClaimSupportState.SUPPORT_ASSERTED.value,
            ClaimSupportState.PASSAGE_REPRODUCED.value,
            ClaimSupportState.SUPPORT_VERIFIED.value,
            ClaimSupportState.SUPPORT_CONTESTED.value,
            ClaimSupportState.CONTRADICTED.value,
        }
        if self.support_state in passage_states and not any(link.locator for link in self.supports):
            raise ValueError("%s requires a passage locator" % self.support_state)
        assertion_states = {
            ClaimSupportState.SUPPORT_ASSERTED.value,
            ClaimSupportState.SUPPORT_VERIFIED.value,
            ClaimSupportState.SUPPORT_CONTESTED.value,
            ClaimSupportState.CONTRADICTED.value,
        }
        if self.support_state in assertion_states and not self.created_by:
            raise ValueError("%s requires created_by" % self.support_state)
        if self.support_state == ClaimSupportState.SUPPORT_VERIFIED.value:
            if not self.reviewed_by:
                raise ValueError("support_verified requires reviewed_by")
            if not any(link.verdict == "supports" for link in self.supports):
                raise ValueError("support_verified requires a link verdict of supports")
        if self.support_state == ClaimSupportState.SUPPORT_CONTESTED.value:
            if not any(link.verdict == "contested" for link in self.supports):
                raise ValueError("support_contested requires a link verdict of contested")
        if self.support_state == ClaimSupportState.CONTRADICTED.value:
            if not any(link.verdict == "contradicts" for link in self.supports):
                raise ValueError("contradicted requires a link verdict of contradicts")
    def to_dict(self) -> Dict[str, object]:
        record = {"schema": self.schema, "binding_id": self.binding_id, "claim_id": self.claim_id,
                  "assertion_id": self.assertion_id, "artefact_revision": self.artefact_revision,
                  "support_state": self.support_state, "supports": [s.to_dict() for s in self.supports],
                  "created_by": self.created_by, "reviewed_by": self.reviewed_by,
                  "created_at": self.created_at}
        if self.claim_text_sha256 is not None:
            record["claim_text_sha256"] = self.claim_text_sha256
        if self.claim_locator:
            record["claim_locator"] = dict(self.claim_locator)
        return record

@dataclass(frozen=True)
class BindingVerification:
    valid: bool
    checks: Dict[str, bool]
    errors: List[str]
    binding: ClaimBinding

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema": "warrantos-binding-verification/v1",
            "valid": self.valid,
            "checks": dict(self.checks),
            "errors": list(self.errors),
            "binding": self.binding.to_dict(),
        }

def locate_unique(text: str, passage: str) -> Dict[str, object]:
    """Return a deterministic Unicode-codepoint range for an exact passage."""
    if not passage:
        raise ValueError("passage must be non-empty")
    start = text.find(passage)
    if start < 0:
        raise ValueError("passage is not present in text")
    if text.find(passage, start + 1) >= 0:
        raise ValueError("passage is not unique; supply an unambiguous passage")
    return {"type": "text_char_range", "start": start, "end": start + len(passage)}

def passage_at(text: str, locator: Mapping[str, object]) -> str:
    """Resolve the closed-open v1 locator, rejecting coercions and bad ranges."""
    if locator.get("type") != "text_char_range":
        raise ValueError("unsupported locator type; expected text_char_range")
    start, end = locator.get("start"), locator.get("end")
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
        raise ValueError("locator start/end must be integers")
    if start < 0 or end <= start or end > len(text):
        raise ValueError("locator range is outside the supplied text")
    return text[start:end]

def snapshot_text(*, source_snapshot_id: str, canonical_uri: str, retrieved_at: str,
                  content: bytes, media_type: str = "text/plain",
                  encoding: str = "utf-8") -> SourceSnapshot:
    """Create a snapshot from the exact bytes and deterministic text extraction."""
    text = content.decode(encoding)
    return SourceSnapshot(
        source_snapshot_id=source_snapshot_id,
        canonical_uri=canonical_uri,
        retrieved_at=retrieved_at,
        content_sha256=sha256_bytes(content),
        extraction_sha256=sha256_text(text),
        media_type=media_type,
    )

def assert_binding(*, binding_id: str, claim_id: str, claim_text: str,
                   artefact_text: str, snapshot: SourceSnapshot, source_text: str,
                   passage: str, created_by: str, created_at: str = "",
                   assertion_id: Optional[str] = None,
                   relation: str = "direct_support") -> ClaimBinding:
    """Create a reproducible support assertion from exact artefact/source text."""
    claim_locator = locate_unique(artefact_text, claim_text)
    source_locator = locate_unique(source_text, passage)
    link = SupportLink(
        source_snapshot_id=snapshot.source_snapshot_id,
        relation=relation,
        locator=source_locator,
        quoted_span_sha256=sha256_text(passage),
        verdict=None,
    )
    return ClaimBinding(
        binding_id=binding_id,
        claim_id=claim_id,
        assertion_id=assertion_id,
        artefact_revision=sha256_text(artefact_text),
        support_state=ClaimSupportState.SUPPORT_ASSERTED.value,
        supports=[link],
        created_by=created_by,
        created_at=created_at,
        claim_text_sha256=sha256_text(claim_text),
        claim_locator=claim_locator,
    )

def verify_binding(binding: ClaimBinding, *, artefact_text: str,
                   snapshots: List[SourceSnapshot], source_bytes: Mapping[str, bytes],
                   reviewer: str, semantic_verdict: str,
                   source_encoding: str = "utf-8") -> BindingVerification:
    """Reproduce byte/range evidence without accepting semantic authority.

    ``reviewer`` and ``semantic_verdict`` remain in the signature for source
    compatibility with the pre-hardening API.  They are untrusted caller data,
    are not copied into the returned binding, and cannot confer any semantic
    support state.  A successful result is always ``passage_reproduced``.
    """
    checks: Dict[str, bool] = {}
    errors: List[str] = []
    snap_by_id = {s.source_snapshot_id: s for s in snapshots}
    checks["artefact_revision"] = binding.artefact_revision == sha256_text(artefact_text)
    if not checks["artefact_revision"]:
        errors.append("artefact revision digest mismatch")
    try:
        claim_text = passage_at(artefact_text, binding.claim_locator)
        checks["claim_passage"] = binding.claim_text_sha256 == sha256_text(claim_text)
    except (ValueError, TypeError) as exc:
        checks["claim_passage"] = False
        errors.append("claim locator: %s" % exc)
    if not checks["claim_passage"] and not any(e.startswith("claim locator:") for e in errors):
        errors.append("claim passage digest mismatch")
    # Compatibility inputs are intentionally non-authoritative.  Recording a
    # different label is not authentication and must not inflate evidence
    # reproduction into semantic support.
    _ = reviewer, semantic_verdict
    checks["legacy_semantic_inputs_ignored"] = True
    links: List[SupportLink] = []
    for index, link in enumerate(binding.supports):
        prefix = "support_%d" % index
        snapshot = snap_by_id.get(link.source_snapshot_id)
        checks[prefix + "_snapshot_known"] = snapshot is not None
        raw = source_bytes.get(link.source_snapshot_id)
        checks[prefix + "_bytes_supplied"] = raw is not None
        if snapshot is None or raw is None:
            errors.append("%s source snapshot or bytes missing" % prefix)
            continue
        checks[prefix + "_content_digest"] = sha256_bytes(raw) == snapshot.content_sha256
        try:
            source_text = raw.decode(source_encoding)
            checks[prefix + "_extraction_digest"] = (
                snapshot.extraction_sha256 is not None
                and sha256_text(source_text) == snapshot.extraction_sha256
            )
            quoted = passage_at(source_text, link.locator)
            checks[prefix + "_passage_digest"] = (
                link.quoted_span_sha256 is not None
                and sha256_text(quoted) == link.quoted_span_sha256
            )
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            checks[prefix + "_extraction_digest"] = False
            checks[prefix + "_passage_digest"] = False
            errors.append("%s passage: %s" % (prefix, exc))
        for suffix in ("content_digest", "extraction_digest", "passage_digest"):
            if not checks.get(prefix + "_" + suffix, False):
                errors.append("%s %s mismatch" % (prefix, suffix.replace("_", " ")))
        links.append(SupportLink(
            source_snapshot_id=link.source_snapshot_id,
            relation=link.relation,
            locator=dict(link.locator),
            quoted_span_sha256=link.quoted_span_sha256,
            verdict=None,
            confidence=link.confidence,
        ))
    valid = bool(checks) and all(checks.values()) and len(links) == len(binding.supports)
    state = ClaimSupportState.PASSAGE_REPRODUCED.value if valid else binding.support_state
    verified = ClaimBinding(
        binding_id=binding.binding_id, claim_id=binding.claim_id,
        assertion_id=binding.assertion_id, artefact_revision=binding.artefact_revision,
        support_state=state, supports=links if valid else binding.supports,
        created_by=binding.created_by, reviewed_by=None,
        created_at=binding.created_at, claim_text_sha256=binding.claim_text_sha256,
        claim_locator=dict(binding.claim_locator),
    )
    return BindingVerification(valid=valid, checks=checks, errors=errors, binding=verified)

def validate_binding_sources(binding: ClaimBinding, snapshots: List[SourceSnapshot]) -> None:
    known = {snapshot.source_snapshot_id for snapshot in snapshots}
    missing = [link.source_snapshot_id for link in binding.supports if link.source_snapshot_id not in known]
    if missing:
        raise ValueError("binding references unknown source snapshot(s): %s" % ", ".join(missing))

def source_snapshot_from_dict(data: Mapping[str, object]) -> SourceSnapshot:
    if data.get("schema") != "warrantos-source-manifest/v1":
        raise ValueError("unsupported source snapshot schema")
    return SourceSnapshot(
        source_snapshot_id=str(data.get("source_snapshot_id", "")),
        canonical_uri=str(data.get("canonical_uri", "")),
        retrieved_at=str(data.get("retrieved_at", "")),
        content_sha256=str(data.get("content_sha256", "")),
        media_type=str(data.get("media_type", "application/octet-stream")),
        published_at=data.get("published_at") if isinstance(data.get("published_at"), str) else None,
        effective_from=data.get("effective_from") if isinstance(data.get("effective_from"), str) else None,
        effective_to=data.get("effective_to") if isinstance(data.get("effective_to"), str) else None,
        extraction_sha256=data.get("extraction_sha256") if isinstance(data.get("extraction_sha256"), str) else None,
        publisher=str(data.get("publisher", "")),
        authority_class=str(data.get("authority_class", "unclassified")),
        classification=str(data.get("classification", "Official")),
    )

def claim_binding_from_dict(data: Mapping[str, object]) -> ClaimBinding:
    if data.get("schema") != "warrantos-claim-binding/v1":
        raise ValueError("unsupported claim binding schema")
    raw_supports = data.get("supports")
    if not isinstance(raw_supports, list):
        raise ValueError("binding supports must be an array")
    supports: List[SupportLink] = []
    for raw in raw_supports:
        if not isinstance(raw, Mapping):
            raise ValueError("binding support must be an object")
        supports.append(SupportLink(
            source_snapshot_id=str(raw.get("source_snapshot_id", "")),
            relation=str(raw.get("relation", "")),
            locator=dict(raw.get("locator") or {}),
            quoted_span_sha256=raw.get("quoted_span_sha256") if isinstance(raw.get("quoted_span_sha256"), str) else None,
            verdict=raw.get("verdict") if isinstance(raw.get("verdict"), str) else None,
            confidence=float(raw["confidence"]) if isinstance(raw.get("confidence"), (int, float)) else None,
        ))
    return ClaimBinding(
        binding_id=str(data.get("binding_id", "")), claim_id=str(data.get("claim_id", "")),
        assertion_id=data.get("assertion_id") if isinstance(data.get("assertion_id"), str) else None,
        artefact_revision=str(data.get("artefact_revision", "")),
        support_state=str(data.get("support_state", "")), supports=supports,
        created_by=str(data.get("created_by", "")),
        reviewed_by=data.get("reviewed_by") if isinstance(data.get("reviewed_by"), str) else None,
        created_at=str(data.get("created_at", "")),
        claim_text_sha256=data.get("claim_text_sha256") if isinstance(data.get("claim_text_sha256"), str) else None,
        claim_locator=dict(data.get("claim_locator") or {}),
    )

def verify_recorded_binding(binding: ClaimBinding, *, artefact_text: str,
                            snapshots: List[SourceSnapshot],
                            source_bytes: Mapping[str, bytes]) -> BindingVerification:
    """Reproduce a recorded binding, downgrading legacy semantic assertions.

    A recorded reviewer label/verdict is not authenticated semantic proof.
    Re-verification therefore strips those fields and returns only the
    evidence-only ``passage_reproduced`` state when all bytes and ranges match.
    """
    asserted = ClaimBinding(
        binding_id=binding.binding_id, claim_id=binding.claim_id,
        assertion_id=binding.assertion_id, artefact_revision=binding.artefact_revision,
        support_state=ClaimSupportState.SUPPORT_ASSERTED.value,
        supports=[SupportLink(
            source_snapshot_id=link.source_snapshot_id, relation=link.relation,
            locator=dict(link.locator), quoted_span_sha256=link.quoted_span_sha256,
            confidence=link.confidence,
        ) for link in binding.supports],
        created_by=binding.created_by, created_at=binding.created_at,
        claim_text_sha256=binding.claim_text_sha256,
        claim_locator=dict(binding.claim_locator),
    )
    return verify_binding(
        asserted, artefact_text=artefact_text, snapshots=snapshots,
        source_bytes=source_bytes, reviewer="",
        semantic_verdict="",
    )

def _require_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be non-empty" % name)

def _require_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ValueError("%s must be a sha256:<64 hex> digest" % name)
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ValueError("%s must contain hexadecimal digest text" % name) from exc
