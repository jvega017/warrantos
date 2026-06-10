"""provenance.writer_pack: Layer 5 clean-room writer pack.

The writer pack is the only context Layer 6 (clean-room generation) is
permitted to see. Everything else stays in the ledger. SPEC §6.2 lists
the five required sections:

- **Clean Brief**: goal and derived requirements only; no feedback
  history, no process narration.
- **Approved Sources**: empirical evidence rows admitted to final
  prose.
- **Style Rules**: tone, register, and structural rules derived from
  style signals.
- **Acceptance Tests**: quality gates the artefact must pass before
  release.
- **Banned Residue List**: phrases that must not appear verbatim
  (boundary rules promoted from validation rules).

SPEC §6.2 also lists what the pack explicitly does NOT include:

- Raw feedback (the un-transformed text)
- Conversation history
- Prior failed drafts
- Tool traces
- Process notes

The function `compile_writer_pack()` builds the pack from classified
context items. It enforces SPEC-L4-S001 at the writer entry point:
items whose `can_be_seen_by` does not list `clean_room_writer` SHALL
NOT appear in the pack.

Stdlib only. Python 3.8 compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from warrantos.provenance.context_admissibility import ContextItem, derive_requirement


_DEFAULT_ACCEPTANCE_TESTS = (
    "No prohibited expression appears in the final-prose body (Layer 7 G1).",
    "Every load-bearing claim links to at least one admitted source (Layer 7 G2).",
    "No model self-grounding promotes a claim to verified (Layer 7 G3).",
)


@dataclass(frozen=True)
class WriterPack:
    """The structured Layer 5 writer pack.

    Five required sections per SPEC §6.2; serialisable via to_dict().
    """

    run_id: str
    clean_brief: List[str] = field(default_factory=list)
    approved_sources: List[Dict[str, str]] = field(default_factory=list)
    style_rules: List[str] = field(default_factory=list)
    acceptance_tests: List[str] = field(default_factory=list)
    banned_residue: List[str] = field(default_factory=list)
    excluded_count: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema": "warrantos-writer-pack/v1",
            "run_id": self.run_id,
            "clean_brief": list(self.clean_brief),
            "approved_sources": [dict(s) for s in self.approved_sources],
            "style_rules": list(self.style_rules),
            "acceptance_tests": list(self.acceptance_tests),
            "banned_residue": list(self.banned_residue),
            "excluded_count": self.excluded_count,
        }


_BASE_BANNED_RESIDUE = (
    "based on your feedback",
    "as discussed",
    "this version",
    "previous version",
    "prior version",
    "previous draft",
    "prior draft",
)


def compile_writer_pack(
    context_items: Iterable[ContextItem],
    run_id: str,
    extra_acceptance_tests: Optional[Iterable[str]] = None,
    extra_banned_residue: Optional[Iterable[str]] = None,
) -> WriterPack:
    """Compile the Layer 5 writer pack from classified context.

    Enforces SPEC-L4-S001 at the writer entry point: any item whose
    `can_be_seen_by` excludes `clean_room_writer` (either because the
    classifier set `cannot_be_seen_by=(clean_room_writer, ...)` or
    because the row was assigned to the excluded bucket) is rejected
    from the pack. The excluded count is reported on the pack so the
    auditor can see how much material was withheld from the writer.

    Parameters
    ----------
    context_items
        Iterable of ContextItem produced by Layer 1.
    run_id
        Stable run identifier.
    extra_acceptance_tests
        Optional additional acceptance test strings appended to the
        default Layer 7 gate list.
    extra_banned_residue
        Optional additional banned residue phrases appended to the
        base list.

    Returns
    -------
    WriterPack
    """
    items = list(context_items)
    excluded = 0

    clean_brief: List[str] = []
    approved_sources: List[Dict[str, str]] = []
    style_rules: List[str] = []
    banned_residue: List[str] = list(_BASE_BANNED_RESIDUE)

    for item in items:
        if not _admissible_to_writer(item):
            excluded += 1
            continue

        if item.context_type == "empirical_evidence":
            approved_sources.append({
                "context_id": item.context_id,
                "text": item.raw_text,
            })
            continue

        if item.context_type == "style_signal":
            req = derive_requirement(item)
            style_rules.append(req.text)
            continue

        if item.context_type == "validation_rule":
            # validation rules promote to banned-residue entries; the rule
            # text is parsed only loosely here, deferred to the
            # derive_requirement() output.
            req = derive_requirement(item)
            banned_residue.append(req.text)
            continue

        if item.context_type == "instruction":
            clean_brief.append(item.raw_text.strip())
            continue

        if item.context_type in {
            "user_feedback",
            "review_finding",
            "prior_artefact",
            "process_history",
        }:
            # Transform process material into a derived requirement,
            # never include the raw text in the brief.
            req = derive_requirement(item)
            clean_brief.append(req.text)
            continue

        if item.context_type == "synthesised_judgement":
            # Synthesised judgement is admissible only as a derived
            # requirement, never verbatim, per SPEC-L4-S004.
            req = derive_requirement(item)
            clean_brief.append(req.text)
            continue

        # private_reasoning, operational_trace etc. would have been
        # excluded by _admissible_to_writer above.
        excluded += 1

    acceptance_tests = list(_DEFAULT_ACCEPTANCE_TESTS)
    if extra_acceptance_tests:
        acceptance_tests.extend(extra_acceptance_tests)
    if extra_banned_residue:
        banned_residue.extend(extra_banned_residue)

    return WriterPack(
        run_id=run_id,
        clean_brief=clean_brief,
        approved_sources=approved_sources,
        style_rules=style_rules,
        acceptance_tests=acceptance_tests,
        banned_residue=banned_residue,
        excluded_count=excluded,
    )


def _admissible_to_writer(item: ContextItem) -> bool:
    """SPEC-L4-S001: clean_room_writer is permitted to read this item.

    Decision rule:

    - If `cannot_be_seen_by` explicitly lists `clean_room_writer`,
      reject.
    - If `can_be_seen_by` is non-empty and does not include
      `clean_room_writer`, reject.
    - If the ledger bucket is `excluded`, reject.
    - Otherwise, admit.

    The two-way check (cannot AND can) preserves the classifier's
    intent both when it explicitly denies and when it explicitly lists
    permitted roles.
    """
    if "clean_room_writer" in (item.cannot_be_seen_by or ()):
        return False
    can_set = tuple(item.can_be_seen_by or ())
    if can_set and "clean_room_writer" not in can_set:
        return False
    if item.ledger_bucket == "excluded":
        return False
    return True
