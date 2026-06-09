"""Context admissibility controls for claude-provenance.

The provenance loop catches unsupported factual claims. This module handles a
different leakage class: fuzzy process context appearing in final prose instead
of being transformed into an admissible requirement, style rule, claim, or
audit record.

Stdlib only. Python 3.8 compatible.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from provenance.cbom import ClassificationOverrideRecord
from provenance.review_roles import is_review_role_output


@dataclass(frozen=True)
class ContextItem:
    """A classified piece of context and its admissible use."""

    context_id: str
    raw_text: str
    context_type: str
    ledger_bucket: str
    can_influence_output: bool
    can_appear_in_final_prose: bool
    allowed_transformation: str
    audit_status: str
    can_be_seen_by: tuple = ()
    cannot_be_seen_by: tuple = ()
    prohibited_use: tuple = ()


@dataclass(frozen=True)
class DerivedRequirement:
    """An admissible transformation derived from process context."""

    context_id: str
    kind: str
    text: str


@dataclass(frozen=True)
class BoundaryViolation:
    """A process-to-prose leakage finding."""

    matched_text: str
    rule_id: str
    severity: str
    line_number: int = 0
    artefact_role: str = "final"


@dataclass(frozen=True)
class BoundaryResult:
    """Result of scanning final prose for process leakage."""

    verdict: str
    violations: List[BoundaryViolation]


_SOURCE_RE = re.compile(
    r"\b(source|citation|cited|evidence|official|report|study|data|url|https?://)\b",
    re.I,
)
_FEEDBACK_RE = re.compile(
    r"\b(feedback|comment|review note|not commercial|commercial enough|previous version|prior version|workshop feedback)\b",
    re.I,
)
_STYLE_RE = re.compile(r"\b(style|tone|voice|australian english|spelling|shorter|clearer)\b", re.I)
_TRACE_RE = re.compile(r"\b(tool trace|run log|build|pipeline|fetched|http|operator notes|manifest|date check)\b", re.I)
_REASONING_RE = re.compile(r"\b(private reasoning|chain of thought|thinking context|reasoning chain)\b", re.I)
_PRIOR_DRAFT_RE = re.compile(r"\b(prior draft|previous draft|old draft|earlier draft)\b", re.I)
_REVIEW_RE = re.compile(r"\b(model critique|fresh-critic|evidence-auditor|policy-red-team|review finding|reviewer)\b", re.I)
_CONVERSATION_RE = re.compile(r"\b(conversation history|as discussed|you said|we discussed)\b", re.I)
_BANNED_RE = re.compile(r"\b(banned phrase|blocked phrase|validation rule|must not say)\b", re.I)
_INSTRUCTION_RE = re.compile(
    r"(?:^|\n)\s*(?:Goal|Objective|Task|Requirement|Brief|Scope)\s*[:.\-]|"
    r"\b(?:your goal is|the task is|the objective is|the requirement is|scope of work)\b",
    re.I,
)


_DEFAULT_VIEWERS = ("context_classifier", "semantic_reviewer", "ledger_writer")


def classify_context(
    context_id: str,
    raw_text: str,
    source_agent: Optional[str] = None,
) -> ContextItem:
    """Classify context and assign admissible-use controls.

    The classifier is deliberately conservative and transparent. It is a rule
    layer, not a semantic oracle.

    SPEC-L1-S005 (new in v0.2): when *source_agent* identifies a documented
    review-role agent (per ``provenance.review_roles.REVIEW_ROLE_REGISTRY``),
    or when the text alone strongly signals a review-role output, the
    classification is forced to ``review_finding`` regardless of other text
    content. This closes the A1 classification-laundering attack identified
    by the Wave A policy-red-team review on 2026-05-26: a review_finding
    cannot be silently reclassified to ``private_reasoning`` (or any other
    less-visible class) merely because its text contains a "chain of thought"
    keyword. To override this classification, use ``classify_with_override``
    with an override id from the human_override ledger.
    """
    text = raw_text or ""
    if is_review_role_output(text, source_agent=source_agent):
        return _review_finding_item(context_id, text)
    if _REASONING_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="private_reasoning",
            ledger_bucket="excluded",
            can_influence_output=False,
            can_appear_in_final_prose=False,
            allowed_transformation="none",
            audit_status="excluded",
            can_be_seen_by=("context_classifier", "ledger_writer"),
            cannot_be_seen_by=("clean_room_writer", "final_writer"),
            prohibited_use=("influence_output", "final_prose"),
        )
    if _SOURCE_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="empirical_evidence",
            ledger_bucket="empirical",
            can_influence_output=True,
            can_appear_in_final_prose=True,
            allowed_transformation="claim_or_citation",
            audit_status="recorded",
            can_be_seen_by=_DEFAULT_VIEWERS + ("clean_room_writer", "final_writer"),
            prohibited_use=(),
        )
    if _TRACE_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="operational_trace",
            ledger_bucket="process",
            can_influence_output=False,
            can_appear_in_final_prose=False,
            allowed_transformation="audit_record",
            audit_status="audit_only",
            can_be_seen_by=("context_classifier", "ledger_writer", "auditor"),
            cannot_be_seen_by=("clean_room_writer", "final_writer"),
            prohibited_use=("final_prose",),
        )
    if _BANNED_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="validation_rule",
            ledger_bucket="process",
            can_influence_output=True,
            can_appear_in_final_prose=False,
            allowed_transformation="boundary_rule",
            audit_status="recorded",
            can_be_seen_by=_DEFAULT_VIEWERS + ("boundary_gate",),
            cannot_be_seen_by=("final_writer",),
            prohibited_use=("final_prose",),
        )
    if _STYLE_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="style_signal",
            ledger_bucket="synthesised",
            can_influence_output=True,
            can_appear_in_final_prose=False,
            allowed_transformation="style_rule",
            audit_status="recorded",
            can_be_seen_by=_DEFAULT_VIEWERS + ("clean_room_writer", "final_writer"),
            prohibited_use=("verbatim_final_prose",),
        )
    if _PRIOR_DRAFT_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="prior_artefact",
            ledger_bucket="process",
            can_influence_output=True,
            can_appear_in_final_prose=False,
            allowed_transformation="derived_requirement",
            audit_status="recorded",
            can_be_seen_by=_DEFAULT_VIEWERS,
            cannot_be_seen_by=("clean_room_writer",),
            prohibited_use=("final_prose",),
        )
    if _REVIEW_RE.search(text):
        return _review_finding_item(context_id, text)
    if _CONVERSATION_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="process_history",
            ledger_bucket="process",
            can_influence_output=True,
            can_appear_in_final_prose=False,
            allowed_transformation="derived_requirement",
            audit_status="recorded",
            can_be_seen_by=_DEFAULT_VIEWERS,
            cannot_be_seen_by=("clean_room_writer",),
            prohibited_use=("final_prose",),
        )
    if _INSTRUCTION_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="instruction",
            ledger_bucket="process",
            can_influence_output=True,
            can_appear_in_final_prose=False,
            allowed_transformation="derived_requirement",
            audit_status="recorded",
            can_be_seen_by=_DEFAULT_VIEWERS + ("clean_room_writer", "final_writer"),
            prohibited_use=("verbatim_final_prose",),
        )
    if _FEEDBACK_RE.search(text):
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="user_feedback",
            ledger_bucket="synthesised",
            can_influence_output=True,
            can_appear_in_final_prose=False,
            allowed_transformation="derived_requirement",
            audit_status="recorded",
            can_be_seen_by=_DEFAULT_VIEWERS + ("revision_planner",),
            cannot_be_seen_by=("clean_room_writer",),
            prohibited_use=("final_prose",),
        )
    return ContextItem(
        context_id=context_id,
        raw_text=text,
        context_type="synthesised_judgement",
        ledger_bucket="synthesised",
        can_influence_output=True,
        can_appear_in_final_prose=False,
        allowed_transformation="derived_requirement",
        audit_status="recorded",
        can_be_seen_by=_DEFAULT_VIEWERS,
        cannot_be_seen_by=("clean_room_writer",),
        prohibited_use=("final_prose",),
    )


def _review_finding_item(context_id: str, text: str) -> ContextItem:
    """Construct the canonical ``review_finding`` ContextItem.

    Shared between the source_agent-driven SPEC-L1-S005 gate and the
    text-pattern fallback below, so both code paths emit byte-identical
    items.
    """
    return ContextItem(
        context_id=context_id,
        raw_text=text,
        context_type="review_finding",
        ledger_bucket="synthesised",
        can_influence_output=True,
        can_appear_in_final_prose=False,
        allowed_transformation="applied_recommendation",
        audit_status="recorded",
        can_be_seen_by=_DEFAULT_VIEWERS + ("revision_planner",),
        cannot_be_seen_by=("clean_room_writer",),
        prohibited_use=("final_prose",),
    )


def classify_with_override(
    context_id: str,
    raw_text: str,
    *,
    source_agent: Optional[str],
    override_id: str,
    target_class: str,
    override_rationale_summary: str = "",
) -> Tuple[ContextItem, ClassificationOverrideRecord]:
    """Reclassify a review-role-shaped input under a recorded override.

    SPEC-L1-S005 path. The caller has already recorded a human_override
    ledger row via ``provenance.overrides.record_override()`` and now
    holds the override id. This function:

    1. Verifies the input is review-role-shaped (source_agent in the
       registry, or text heuristics fire). If not, raises ValueError;
       this function exists only to handle the laundering-attack
       boundary, not as a general-purpose reclassification path.
    2. Verifies ``override_id`` is non-empty. SPEC-L1-S005 requires the
       override exists; this function takes the id on trust because the
       override ledger lives in a separate database.
    3. Constructs the ContextItem with the requested ``target_class``
       using that class's standard admissibility flags.
    4. Returns a ``ClassificationOverrideRecord`` for inclusion in the
       CBOM's ``classification_overrides`` field (SPEC §10.3).

    Parameters
    ----------
    context_id
        Stable identifier for this context input.
    raw_text
        The input text.
    source_agent
        Authoritative source-agent identifier, or None if unknown.
    override_id
        Non-empty pointer to a human_override ledger row recorded under
        SPEC-L8-S004.
    target_class
        The class the input is being reclassified to. Common case is
        ``private_reasoning``; other classes are permitted but the CBOM
        will record the reclassification regardless.
    override_rationale_summary
        Optional short summary of the override rationale for CBOM
        readability. The authoritative rationale lives on the
        human_override row.

    Returns
    -------
    (ContextItem, ClassificationOverrideRecord)

    Raises
    ------
    ValueError
        If override_id is empty, or the input is not review-role-shaped
        (this function is not a general reclassifier).
    """
    if not override_id or not override_id.strip():
        raise ValueError("SPEC-L1-S005: override_id SHALL be a non-empty string")

    text = raw_text or ""
    if not is_review_role_output(text, source_agent=source_agent):
        raise ValueError(
            "classify_with_override applies only to review-role-shaped input. "
            "Pass source_agent or include a recognisable review-output signature."
        )

    item = _build_item_for_class(context_id, text, target_class)
    override_record = ClassificationOverrideRecord(
        context_id=context_id,
        classified_as=target_class,
        default_would_be="review_finding",
        override_id=override_id.strip(),
        override_rationale_summary=override_rationale_summary.strip(),
    )
    return item, override_record


def _build_item_for_class(context_id: str, text: str, target_class: str) -> ContextItem:
    """Build a ContextItem with the canonical flags for *target_class*.

    Maps to the same per-class admissibility profile the rule-based
    classifier would emit if it had reached that branch directly.
    """
    if target_class == "private_reasoning":
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="private_reasoning",
            ledger_bucket="excluded",
            can_influence_output=False,
            can_appear_in_final_prose=False,
            allowed_transformation="none",
            audit_status="excluded",
            can_be_seen_by=("context_classifier", "ledger_writer"),
            cannot_be_seen_by=("clean_room_writer", "final_writer"),
            prohibited_use=("influence_output", "final_prose"),
        )
    if target_class == "synthesised_judgement":
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="synthesised_judgement",
            ledger_bucket="synthesised",
            can_influence_output=True,
            can_appear_in_final_prose=False,
            allowed_transformation="derived_requirement",
            audit_status="recorded",
            can_be_seen_by=_DEFAULT_VIEWERS,
            cannot_be_seen_by=("clean_room_writer",),
            prohibited_use=("final_prose",),
        )
    if target_class == "review_finding":
        return _review_finding_item(context_id, text)
    if target_class == "operational_trace":
        return ContextItem(
            context_id=context_id,
            raw_text=text,
            context_type="operational_trace",
            ledger_bucket="process",
            can_influence_output=False,
            can_appear_in_final_prose=False,
            allowed_transformation="audit_record",
            audit_status="audit_only",
            can_be_seen_by=("context_classifier", "ledger_writer", "auditor"),
            cannot_be_seen_by=("clean_room_writer", "final_writer"),
            prohibited_use=("final_prose",),
        )
    raise ValueError(
        "target_class %r is not a recognised SPEC §2.2 class for override path"
        % target_class
    )


def derive_requirement(item: ContextItem) -> DerivedRequirement:
    """Transform admissible context into an applied instruction."""
    if item.allowed_transformation == "claim_or_citation":
        text = "Use as source-supported material only when the final claim is cited."
    elif item.allowed_transformation == "style_rule":
        text = "Apply the style signal through wording, structure, and tone."
    elif item.allowed_transformation == "audit_record":
        text = "Retain as audit metadata; do not use in final prose."
    elif item.allowed_transformation == "boundary_rule":
        text = "Apply as a validation rule; do not repeat the rule text in final prose."
    elif item.allowed_transformation == "applied_recommendation":
        text = "Apply the review finding as a concrete revision without narrating the review process."
    elif not item.can_influence_output:
        text = "Exclude from output generation and retain only if audit policy allows."
    else:
        text = _derive_feedback_requirement(item.raw_text)
    return DerivedRequirement(
        context_id=item.context_id,
        kind=item.allowed_transformation,
        text=text,
    )


def _derive_feedback_requirement(raw_text: str) -> str:
    lower = raw_text.lower()
    parts = []
    if "commercial" in lower:
        parts.append("Strengthen commercial positioning")
    if "previous version" in lower or "prior version" in lower or "previous draft" in lower:
        parts.append("ensure the final document reads as standalone")
    if not parts:
        parts.append("Apply the underlying insight without narrating the drafting process")
    return "; ".join(parts) + "."


_BASE_LEAKAGE_RULES = [
    ("process_feedback", re.compile(r"\bbased on (your )?feedback\b", re.I), "high"),
    ("process_discussion", re.compile(r"\bas discussed\b|\bas we discussed\b", re.I), "medium"),
    ("version_narration", re.compile(r"\bthis version\b|\bprevious version\b|\bprior version\b", re.I), "high"),
    ("draft_narration", re.compile(r"\bprevious draft\b|\bprior draft\b|\bearlier draft\b", re.I), "high"),
    ("comparative_revision", re.compile(r"\bmore commercial\b|\bclearer now\b|\bstronger now\b", re.I), "medium"),
    ("implementation_narration", re.compile(r"\bI (have )?(incorporated|updated|rewritten|changed)\b", re.I), "medium"),
    ("internal_context", re.compile(r"\bthinking context\b|\boperator notes\b|\bbuild [0-9a-f]{6,}\b", re.I), "high"),
]

_BRIEF_LIGHT_RULES = [
    ("archive_only", re.compile(r"\[archive only\]", re.I), "high"),
    ("run_context", re.compile(r"\brun-context\b|\bmanifest\b|\bkernel\b", re.I), "high"),
    ("tool_trace", re.compile(r"\bwebfetch\b|\binputs?\b|\bdate check\b|\bagree=\b", re.I), "medium"),
    ("build_label", re.compile(r"\bbuild\b[: ]+[A-Za-z0-9_.-]{6,}", re.I), "medium"),
]

# The core value proposition: AI assistant scaffold and conversational residue
# that bleeds from the chat into the final artefact. These are the unambiguous
# "AI tells" that should never survive into a shipped document. SPEC-L7-G1.
_AI_RESIDUE_RULES = [
    ("ai_self_reference", re.compile(
        r"\bas an? (ai|artificial intelligence|language model|large language model|ai (language )?(model|assistant))\b"
        r"|\bI(?:'m| am) an? (ai|language model|assistant)\b", re.I), "high"),
    ("ai_capability_disclaimer", re.compile(
        r"\bI (?:cannot|can(?:'|no)t|am unable to|'m unable to) (?:verify|access|browse|provide|confirm|guarantee)\b"
        r"|\bI (?:do not|don'?t) have (?:access|the ability|real[- ]time)\b", re.I), "high"),
    ("assistant_opener", re.compile(
        r"(?im)^\s*(certainly|sure|of course|absolutely|great question|no problem|happy to help|understood)[!,.:]",
    ), "high"),
    ("assistant_closer", re.compile(
        r"\bI hope (?:this|that) helps\b|\blet me know if\b|\bfeel free to (?:ask|reach out|let me)\b"
        r"|\bis there anything else\b|\bwould you like me to\b|\bplease let me know if\b"
        r"|\bhappy to (?:revise|expand|adjust|help|assist|clarify)\b|\bI'?d be happy to\b", re.I), "high"),
    ("delivery_framing", re.compile(
        r"\bhere(?:'s| is) (?:the|a|an|your) (?:revised|updated|final|new|requested|reworked|polished)\b"
        r"|\bbelow is (?:the|a|your) (?:revised|updated|final|requested)\b", re.I), "medium"),
    ("request_acknowledgement", re.compile(
        r"\bas (?:requested|per your (?:request|instructions?))\b|\bper your request\b", re.I), "medium"),
    ("hedge_provenance", re.compile(
        r"\bbased on the (?:information|context|data|details) (?:provided|available|you (?:provided|gave))\b"
        r"|\bbased on the available (?:information|data|context)\b", re.I), "medium"),
    ("future_promise", re.compile(
        r"\bI(?:'ll| will)(?: now| then)? (?:revise|update|adjust|expand|add|change|incorporate|rework)\b", re.I), "medium"),
    ("apology", re.compile(r"\bI apologi[sz]e\b|\bmy apologies\b|\bsorry for the\b", re.I), "medium"),
    ("scaffold_placeholder", re.compile(
        r"\[(?:TODO|INSERT|PLACEHOLDER|ADD|FIXME|XXX|YOUR [A-Z ]+|\.\.\.)\b[^\]]*\]"
        r"|\bTKTK\b|\blorem ipsum\b|\[\.\.\.\]", re.I), "high"),
]

_PROFILE_RULES = {
    "final-prose": _BASE_LEAKAGE_RULES + _BRIEF_LIGHT_RULES + _AI_RESIDUE_RULES,
    "final": _BASE_LEAKAGE_RULES + _BRIEF_LIGHT_RULES + _AI_RESIDUE_RULES,
    "brief-light": _BASE_LEAKAGE_RULES + _BRIEF_LIGHT_RULES + _AI_RESIDUE_RULES,
    "paper-full": _BASE_LEAKAGE_RULES + _AI_RESIDUE_RULES,
    # SPEC-v0.2 calibration profile added in v0.9 after empirical testing on
    # 10/10 brief-template files BLOCKED at G1 (2026-05-27). Brief-prompt
    # templates legitimately contain meta-content language that describes
    # process-narration phrases the gate is meant to block in final prose.
    # The prompt-template profile drops the lexical-residue rules entirely
    # because the input IS the rule-list discussion, not the final artefact.
    # Structural narration rules (the SPEC-L7-S004 SHOULD path) are NOT
    # implemented in v0.9; when they are, this profile retains them.
    "prompt-template": [],
    "audit": [],
    "methodology": [],
    "consultation_report": [],
    "changelog": [],
}


def scan_prose_boundary(text: str, artefact_role: str = "final") -> BoundaryResult:
    """Scan reader-facing prose for process-to-prose leakage."""
    profile = artefact_role or "final"
    if profile in {"audit", "methodology", "consultation_report", "changelog"}:
        return BoundaryResult(verdict="pass", violations=[])

    violations: List[BoundaryViolation] = []
    rules = _PROFILE_RULES.get(profile, _PROFILE_RULES["final"])
    for line_number, line in enumerate((text or "").splitlines() or [text or ""], 1):
        for rule_id, pattern, severity in rules:
            for match in pattern.finditer(line):
                violations.append(
                    BoundaryViolation(
                        matched_text=match.group(0),
                        rule_id=rule_id,
                        severity=severity,
                        line_number=line_number,
                        artefact_role=profile,
                    )
                )
    # Keep historical behaviour for one-line text that has no split lines.
    if not (text or "").splitlines():
        for rule_id, pattern, severity in rules:
            for match in pattern.finditer(text or ""):
                violations.append(
                    BoundaryViolation(
                        matched_text=match.group(0),
                        rule_id=rule_id,
                        severity=severity,
                        line_number=1,
                        artefact_role=profile,
                    )
                )

    return BoundaryResult(
        verdict="blocked" if violations else "pass",
        violations=violations,
    )


def admissibility_summary(item: ContextItem) -> Dict[str, object]:
    """Return the stable public summary for a context item."""
    return {
        "context_id": item.context_id,
        "context_type": item.context_type,
        "ledger_bucket": item.ledger_bucket,
        "can_influence_output": item.can_influence_output,
        "can_appear_in_final_prose": item.can_appear_in_final_prose,
        "allowed_transformation": item.allowed_transformation,
        "audit_status": item.audit_status,
        "can_be_seen_by": list(item.can_be_seen_by),
        "cannot_be_seen_by": list(item.cannot_be_seen_by),
        "prohibited_use": list(item.prohibited_use),
    }


def _stable_cbom_id(items: List[ContextItem], final_text: str) -> str:
    h = hashlib.sha256()
    for item in items:
        h.update(item.context_id.encode("utf-8", "replace"))
        h.update(b"\0")
        h.update(item.raw_text.encode("utf-8", "replace"))
        h.update(b"\0")
    h.update((final_text or "").encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def compile_cbom(
    items: Iterable[ContextItem],
    final_text: str,
    artefact_role: str = "final",
    run_id: Optional[str] = None,
) -> Dict[str, object]:
    """Build a Context Bill of Materials for a final artefact."""
    item_list = list(items)
    boundary = scan_prose_boundary(final_text, artefact_role=artefact_role)
    transformed = [derive_requirement(item) for item in item_list if item.can_influence_output]
    return {
        "schema": "context-bill-of-materials/v1",
        "cbom_id": run_id or _stable_cbom_id(item_list, final_text),
        "created_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "artefact_role": artefact_role,
        "summary": {
            "total_context_items": len(item_list),
            "can_influence_output": sum(1 for item in item_list if item.can_influence_output),
            "can_appear_in_final_prose": sum(
                1 for item in item_list if item.can_appear_in_final_prose
            ),
            "audit_only": sum(1 for item in item_list if item.audit_status == "audit_only"),
            "excluded": sum(1 for item in item_list if item.audit_status == "excluded"),
        },
        "context_items": [admissibility_summary(item) for item in item_list],
        "transforms": [
            {"context_id": req.context_id, "kind": req.kind, "text": req.text}
            for req in transformed
        ],
        "prose_boundary": {
            "verdict": boundary.verdict,
            "violations": [
                {
                    "matched_text": v.matched_text,
                    "rule_id": v.rule_id,
                    "severity": v.severity,
                    "line_number": v.line_number,
                    "artefact_role": v.artefact_role,
                }
                for v in boundary.violations
            ],
        },
    }
