#!/usr/bin/env python3
"""warrantos: integration CLI for the WarrantOS provenance and admissibility stack.

Path X3 Day 5. Wires the full upstream-leg pipeline: Layer 1 classification
with SPEC-L1-S005 review-role gating, per-run JSON persistence (Layer 2
discipline), Layer 7 G1 prose-boundary scan, Layer 7 G2 claim detection
and optional verification, CBOM v0.2 assembly with actor_identity and
classification_overrides, reader-facing override footer per SPEC-L8-S005,
and a four-state consolidated verdict (PASS, HOLD, BLOCK, NOT_ASSESSABLE)
that closes Codex C1: NOT_ASSESSABLE fires when a final-prose artefact
lacks the minimum coupling evidence (actor_identity) needed to certify
the override/identity leg of the coupling thesis.

Honest limits carried forward from PATH-X3-EXECUTION-PLAN.md section 4:

- Layer 5 writer pack and Layer 6 clean-room generation are NOT BUILT.
  The harness operates over an already-written draft. Layer 5/6 are Path
  X4 work.
- Layer 7 G3, G4, G5 are NOT BUILT.
- The offline heuristic verifier CANNOT emit `contradicted` by
  construction (documented in MEMORY.md from Probe A 2026-05-22/23 and
  in grade.py module docstring). The harness's BLOCK-on-contradicted
  branch fires only when an LLM grader is configured via
  ANTHROPIC_API_KEY or a callable cross-model backend is supplied.
- The salience-based HOLD line uses `provenance.salience.is_load_bearing`
  with the documented LOAD_BEARING_THRESHOLD = 0.5. The threshold is
  inherited from the existing salience module rather than reinvented
  here.

Usage
-----

    python cli/warrantos_cli.py check DRAFT.md
        [--context CONTEXT.json]
        [--actor-identity ACTOR.json]
        [--profile final-prose|paper-full|brief-light|audit|methodology|...]
        [--run-id RUN_ID]
        [--db PATH_TO_LEDGER.db]
        [--out-dir DIR]
        [--json] [--ci] [--verify]

Context file format (JSON list of items)::

    [
        {"id": "ctx_001", "text": "...", "source_agent": "policy-red-team"},
        {"id": "ctx_002", "text": "...", "source": "report.pdf"}
    ]

Actor identity file format (JSON object mapping role -> identity)::

    {
        "context_classifier": "agent:auto",
        "insight_compiler": "human:juan.vega",
        "source_curator": "human:juan.vega",
        "clean_room_writer": "model:claude-opus-4-7",
        "reviewer_qa": "agent:policy-red-team",
        "auditor": "human:director.so"
    }

Stdlib only. Python 3.8 compatible.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make the repository root importable when running this file directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from provenance.cbom import (  # noqa: E402
    CBOM,
    ClaimRecord,
    ClassificationOverrideRecord,
    ContextInput,
    build_cbom,
)
from provenance.context_admissibility import (  # noqa: E402
    BoundaryResult,
    ContextItem,
    classify_context,
    scan_prose_boundary,
)
from provenance.footer import render_override_footer  # noqa: E402
from provenance.overrides import list_overrides_for_run  # noqa: E402
from provenance.salience import LOAD_BEARING_THRESHOLD, is_load_bearing  # noqa: E402
from provenance.verify import extract_citation, verify_claim, verify_text  # noqa: E402
from provenance.extract import CLAIM_TRIGGERS, sentences  # noqa: E402
from provenance.gates import check_self_grounding  # noqa: E402


VERDICT_PASS = "PASS"
VERDICT_HOLD = "HOLD"
VERDICT_BLOCK = "BLOCK"
VERDICT_NOT_ASSESSABLE = "NOT_ASSESSABLE"

_NON_FINAL_PROFILES = frozenset({
    "audit", "methodology", "consultation_report", "changelog",
})


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warrantos",
        description=(
            "WarrantOS integration CLI. Runs Layer 1 classification, Layer 7 "
            "G1 prose-boundary scan, Layer 7 G2 claim detection (with optional "
            "verification), assembles a SPEC-v0.2 CBOM with actor_identity "
            "and classification_overrides, and emits a four-state "
            "consolidated verdict (PASS, HOLD, BLOCK, NOT_ASSESSABLE)."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    status_parser = sub.add_parser(
        "status",
        help="Print the per-layer WarrantOS conformance status.",
        description=(
            "Report which of the eight architecture layers (plus the "
            "foundation row) are BUILT / PARTIAL / STARTER / NOT_BUILT "
            "against the running install."
        ),
    )
    status_parser.add_argument(
        "--markdown",
        action="store_true",
        help="Emit Markdown (suitable for docs/STATUS.md).",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the status rows as a JSON list.",
    )

    check = sub.add_parser(
        "check",
        help="Run the WarrantOS check pipeline over a draft artefact.",
        description=(
            "Run the WarrantOS check pipeline over a draft artefact. "
            "NOT_ASSESSABLE fires when a final-prose artefact lacks "
            "actor_identity (Codex C1 closure)."
        ),
    )
    check.add_argument("draft", help="Path to the draft Markdown file.")
    check.add_argument(
        "--context",
        default=None,
        help="Path to a JSON file with context items (see module docstring).",
    )
    check.add_argument(
        "--actor-identity",
        default=None,
        help=(
            "Path to a JSON file mapping role name to actor identity. "
            "Required for final-prose artefacts; absent identity triggers "
            "NOT_ASSESSABLE per Codex C1."
        ),
    )
    check.add_argument(
        "--profile",
        default="final-prose",
        choices=(
            "final-prose",
            "brief-light",
            "paper-full",
            "prompt-template",
            "audit",
            "methodology",
            "consultation_report",
            "changelog",
        ),
        help=(
            "Layer 7 G1 boundary profile (default: final-prose). Use "
            "prompt-template for brief-prompt artefacts that legitimately "
            "discuss process-narration phrases."
        ),
    )
    check.add_argument(
        "--run-id",
        default=None,
        help="Stable run identifier. Generated when absent.",
    )
    check.add_argument(
        "--db",
        default=str(Path(".warrant") / "provenance.db"),
        help="Path to the override ledger database. Used to look up overrides.",
    )
    check.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Defaults to .warrant/runs/<run_id>/.",
    )
    check.add_argument(
        "--json",
        action="store_true",
        help="Emit the run report as JSON on stdout.",
    )
    check.add_argument(
        "--ci",
        action="store_true",
        help="Exit non-zero on HOLD, BLOCK, or NOT_ASSESSABLE verdicts.",
    )
    check.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Run the Layer 7 G2 verifier over detected claims. Offline by "
            "default (no network fetch); set ANTHROPIC_API_KEY to enable the "
            "LLM grader. Note: the offline heuristic cannot emit "
            "`contradicted` by construction."
        ),
    )
    check.add_argument(
        "--no-fetch",
        action="store_true",
        help=(
            "When --verify is set, do not fetch cited URLs. Forces every "
            "verification to run against citation metadata only."
        ),
    )
    check.add_argument(
        "--writer-model",
        default=None,
        help=(
            "Model identifier of the writer. Used by Layer 7 G3 "
            "self-grounding check. Optional; G3 is informational only "
            "(SPEC-L7-N003 SHALL FLAG, not SHALL BLOCK)."
        ),
    )
    check.add_argument(
        "--verifier-model",
        default=None,
        help=(
            "Model identifier of the verifier. Used by Layer 7 G3 "
            "self-grounding check. Optional. When equal to "
            "--writer-model, G3 flags requires_external_grounding."
        ),
    )
    # Cost-control flags (docs/COST.md)
    check.add_argument(
        "--max-verify-claims",
        type=int,
        default=0,
        help=(
            "Cap the number of claims sent to the verifier per run, "
            "prioritised by salience. 0 (default) = no cap. Has no "
            "effect without --verify."
        ),
    )
    check.add_argument(
        "--salience-min",
        type=float,
        default=0.0,
        help=(
            "Only verify claims at or above this salience score. "
            "Default 0.0 = verify every detected claim. Pass 0.5 to "
            "match the documented LOAD_BEARING_THRESHOLD."
        ),
    )

    # --- attest: bundle a checked run into a portable .warrant artefact ---
    attest = sub.add_parser(
        "attest",
        help="Bundle a checked run into a verifiable .warrant artefact.",
        description=(
            "Assemble a .warrant bundle (prose digest + CBOM + ledger entries + "
            "Merkle checkpoint, Ed25519-signed if a key is available) from a "
            "completed `warrantos check` run directory. The bundle verifies "
            "offline with `warrantos verify-external`."
        ),
    )
    attest.add_argument("prose", help="Path to the final prose (the checked draft).")
    attest.add_argument(
        "--run-dir", required=True,
        help="The run output directory from `warrantos check` (.warrant/runs/<id>).",
    )
    attest.add_argument("--db", default=None, help="Override-ledger SQLite DB path.")
    attest.add_argument("--out", default=None, help="Output .warrant path (default: <prose>.warrant).")

    # --- verify-external: verify a .warrant offline ---
    verify = sub.add_parser(
        "verify-external",
        help="Verify a .warrant artefact offline.",
        description=(
            "Verify a .warrant bundle with no access to the original ledger. The "
            "integrity check (recompute the Merkle root and match the checkpoint) "
            "is pure stdlib; the signature check needs the [attestation] extra."
        ),
    )
    verify.add_argument("warrant", help="Path to the .warrant file.")
    verify.add_argument("--prose", default=None, help="Optional prose to check the digest against.")
    verify.add_argument("--key", default=None, help="Expected signer public key (base64url) to pin attribution.")
    verify.add_argument("--json", action="store_true", help="Emit the verdict as JSON.")

    return parser


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def load_draft(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_context(path: Optional[str]) -> List[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("context file must be a JSON list of items")
    return data


def load_actor_identity(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("actor identity file must be a JSON object")
    return {str(k): str(v) for k, v in data.items()}


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def classify_all(items: List[dict]) -> List[Tuple[ContextItem, dict]]:
    """Run Layer 1 over every context item. Returns (item, raw) tuples."""
    result = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        context_id = str(
            raw.get("id")
            or raw.get("context_id")
            or "ctx_" + uuid.uuid4().hex[:8]
        )
        text = str(raw.get("text") or "")
        source_agent = raw.get("source_agent")
        item = classify_context(context_id, text, source_agent=source_agent)
        result.append((item, raw))
    return result


def detect_claims(draft_text: str) -> List[Dict[str, Any]]:
    """Detect candidate factual claims using the shared CLAIM_TRIGGERS.

    Returns one row per sentence that matches at least one trigger.
    Each row carries the sentence, the trigger names that fired, the
    citation token if any, and the salience score.
    """
    from provenance.salience import score_claim

    rows: List[Dict[str, Any]] = []
    for sent in sentences(draft_text):
        triggered = [name for name, rx in CLAIM_TRIGGERS if rx.search(sent)]
        if not triggered:
            continue
        citation = extract_citation(sent)
        rows.append(
            {
                "sentence": sent,
                "triggers": triggered,
                "citation": citation,
                "salience": score_claim(sent),
                "load_bearing": is_load_bearing(sent),
            }
        )
    return rows


def run_verifier(draft_text: str, fetch: bool) -> List[Dict[str, Any]]:
    """Run the existing verifier over the draft text and shape its output
    into JSON-friendly dicts."""
    verdicts = verify_text(draft_text, fetch=fetch)
    return [
        {
            "claim_text": v.claim_text,
            "citation": v.citation,
            "verdict": v.verdict,
            "confidence": v.confidence,
            "rationale": v.rationale,
            "grader": v.grader,
        }
        for v in verdicts
    ]


def run_verifier_capped(
    claim_rows: List[Dict[str, Any]],
    *,
    fetch: bool,
    salience_min: float,
    max_claims: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run the verifier against the already-detected claims, with cost
    caps.

    Filters claim_rows by salience (>= salience_min) and caps the
    survivors by max_claims (priority by descending salience).
    Verifies only the survivors. Returns the verifier_rows and a
    skipped-summary recording how many claims the caps removed.

    SPEC-aligned: this is the cost-controlled path documented in
    docs/COST.md. The skipped summary makes the saving visible in the
    report so an auditor can see what was traded.
    """
    if not claim_rows:
        return [], {"reason": "no_claims_detected", "count": 0, "examples": []}

    surviving = [c for c in claim_rows if c.get("salience", 0.0) >= salience_min]
    salience_skipped = len(claim_rows) - len(surviving)

    # Priority by descending salience so the most load-bearing claims
    # consume the budget first.
    surviving.sort(key=lambda c: c.get("salience", 0.0), reverse=True)

    cap_skipped = 0
    if max_claims and max_claims > 0 and len(surviving) > max_claims:
        cap_skipped = len(surviving) - max_claims
        surviving = surviving[:max_claims]

    verifier_rows: List[Dict[str, Any]] = []
    for claim in surviving:
        try:
            verdict = verify_claim(
                claim["sentence"],
                citation=claim.get("citation"),
            )
        except Exception as exc:
            verifier_rows.append({
                "claim_text": claim["sentence"],
                "citation": claim.get("citation"),
                "verdict": "error",
                "confidence": None,
                "rationale": str(exc)[:200],
                "grader": "exception",
            })
            continue
        verifier_rows.append({
            "claim_text": verdict.claim_text,
            "citation": verdict.citation,
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "rationale": verdict.rationale,
            "grader": verdict.grader,
        })

    total_skipped = salience_skipped + cap_skipped
    reason_parts = []
    if salience_skipped:
        reason_parts.append("salience_min=%.2f (%d skipped)" % (salience_min, salience_skipped))
    if cap_skipped:
        reason_parts.append("max_verify_claims=%d (%d skipped)" % (max_claims, cap_skipped))
    skipped_summary = {
        "reason": "; ".join(reason_parts) if reason_parts else "no_caps_applied",
        "count": total_skipped,
        "examples": [
            c["sentence"][:80]
            for c in claim_rows
            if c.get("salience", 0.0) < salience_min
        ][:3],
    }
    # Fetch flag is honoured by the underlying verify_claim through
    # the offline-by-default path; --no-fetch is implicit when the
    # caller passes fetch=False because verify_claim does not perform
    # a network fetch when there is no URL citation.
    _ = fetch
    return verifier_rows, skipped_summary


def to_context_input(item: ContextItem, raw: dict) -> ContextInput:
    """Adapt a classified ContextItem to the CBOM ContextInput record.

    The CBOM uses a flat shape (`material_type`, `admitted`, `reason`)
    while ContextItem carries the rich Layer 1/4 admissibility flags.
    Codex C2 fix: this adapter is the missing translation layer the
    earlier pseudocode glossed over.
    """
    admitted = item.can_appear_in_final_prose or item.allowed_transformation != "none"
    reason = ""
    if not item.can_appear_in_final_prose:
        reason = "process material; cannot appear in final prose"
    if item.audit_status == "excluded":
        reason = "excluded class; cannot influence output"
    if item.audit_status == "audit_only":
        reason = "audit-only material"
    return ContextInput(
        context_id=item.context_id,
        text=item.raw_text,
        source=str(raw.get("source") or ""),
        material_type=item.context_type,
        admitted=admitted,
        reason=reason,
    )


def to_claim_record(claim_row: Dict[str, Any], context_ids_admitted: List[str]) -> ClaimRecord:
    """Adapt a detected claim row to a CBOM ClaimRecord."""
    status = "supported" if claim_row.get("citation") else "unsupported"
    # The CBOM validates that support_ids reference admitted inputs.
    # Without an upstream binding step we cannot link a specific
    # context_id, so we leave support_ids empty when no citation is
    # present; when a citation is present we use the sentence as
    # provenance hint (status=supported is honest because the sentence
    # itself carries a citation token).
    return ClaimRecord(
        claim_id="claim_" + uuid.uuid4().hex[:8],
        text=claim_row["sentence"],
        support_ids=[],  # Day 5 does not perform binding; Path X4.
        status=status,
    )


# ---------------------------------------------------------------------------
# Consolidated verdict (Codex C1 fix: NOT_ASSESSABLE state)
# ---------------------------------------------------------------------------

# Profiles whose artefact is a final deliverable, where an independent human
# review is part of what certifies a PASS. A same-actor (single-actor) review on
# these compromises the separation-of-duties leg (SPEC-L8-S003).
_SOD_FINAL_ARTEFACT_PROFILES = frozenset({
    "final-prose", "audit", "paper-full", "methodology", "consultation_report",
})
# The strictest profiles: a same-actor review BLOCKs rather than HOLDs.
_SOD_BLOCK_PROFILES = frozenset({"audit"})


def consolidate_verdict(
    boundary_report: BoundaryResult,
    claim_rows: List[Dict[str, Any]],
    verifier_rows: List[Dict[str, Any]],
    actor_identity: Dict[str, str],
    classification_overrides: List[ClassificationOverrideRecord],
    artefact_role: str,
    single_actor_override: bool = False,
) -> Tuple[str, List[str]]:
    """Return (verdict, reasons).

    Verdict is one of PASS, HOLD, BLOCK, NOT_ASSESSABLE.

    Decision order:

    1. BLOCK if any verifier verdict is `contradicted`, any boundary
       violation occurred in a blocking profile, or a same-actor review
       (single_actor_override) was recorded on a strict profile (SoD).
    2. HOLD if any unsupported load-bearing claim exists, any verifier
       verdict is `unverifiable` for a load-bearing claim, or a same-actor
       review was recorded on a final-artefact profile (separation of
       duties, SPEC-L8-S003: an independent reviewer is required to PASS).
    3. NOT_ASSESSABLE if the artefact role is `final-prose` and the
       run has no `actor_identity` map. This is the Codex C1 fix:
       a final-prose artefact requires the minimum override/identity
       coupling evidence to be certifiable as PASS.
    4. PASS otherwise.

    `single_actor_override` is True when any human override on this run had
    the writer and reviewer as the same actor. P0.1 makes separation of
    duties a verdict-layer property, not just a footer marker.
    """
    reasons: List[str] = []
    role_lower = artefact_role.strip().lower()

    # 1. BLOCK conditions
    contradicted = [v for v in verifier_rows if v.get("verdict") == "contradicted"]
    for v in contradicted:
        snippet = (v.get("claim_text") or "")[:80]
        reasons.append("BLOCK: contradicted claim: " + snippet)

    if boundary_report.verdict == "blocked":
        for v in boundary_report.violations:
            reasons.append(
                "BLOCK: boundary violation [%s severity=%s] line %d: %s"
                % (v.rule_id, v.severity, v.line_number, v.matched_text[:60])
            )

    # Separation of duties (SPEC-L8-S003): on strict profiles a same-actor
    # review BLOCKs, because the independent-review leg cannot be vouched for.
    if single_actor_override and role_lower in _SOD_BLOCK_PROFILES:
        reasons.append(
            "BLOCK: separation of duties (SPEC-L8-S003): the writer and reviewer "
            "are the same actor on a '%s' artefact; an independent review is "
            "mandatory for this profile." % role_lower
        )

    if reasons:
        return (VERDICT_BLOCK, reasons)

    # 2. HOLD conditions
    for claim in claim_rows:
        if not claim.get("citation") and claim.get("load_bearing"):
            reasons.append(
                "HOLD: unsupported load-bearing claim (salience=%.2f): %s"
                % (claim.get("salience", 0.0), claim["sentence"][:80])
            )

    for v in verifier_rows:
        if v.get("verdict") == "unverifiable" and is_load_bearing(v.get("claim_text") or ""):
            reasons.append(
                "HOLD: unverifiable load-bearing claim: " + (v.get("claim_text") or "")[:80]
            )

    # Separation of duties (SPEC-L8-S003): on a final-artefact profile a same-actor
    # review downgrades to HOLD. An independent reviewer is required to certify PASS.
    if single_actor_override and role_lower in _SOD_FINAL_ARTEFACT_PROFILES:
        reasons.append(
            "HOLD: separation of duties (SPEC-L8-S003): the writer and reviewer are "
            "the same actor; an independent review is required to certify a final "
            "artefact as PASS."
        )

    if reasons:
        return (VERDICT_HOLD, reasons)

    # 3. NOT_ASSESSABLE (Codex C1)
    if role_lower == "final-prose" and not actor_identity:
        reasons.append(
            "NOT_ASSESSABLE: final-prose artefact requires actor_identity to "
            "certify the override/identity leg of the coupling thesis. No "
            "actor_identity supplied. Either provide --actor-identity or use "
            "a non-final-prose profile."
        )
        return (VERDICT_NOT_ASSESSABLE, reasons)

    return (VERDICT_PASS, reasons)


# ---------------------------------------------------------------------------
# Persistence (per-run JSON artefacts)
# ---------------------------------------------------------------------------

def write_run_artefacts(
    out_dir: Path,
    *,
    run_id: str,
    cbom: CBOM,
    classified: List[ContextItem],
    boundary: BoundaryResult,
    claim_rows: List[Dict[str, Any]],
    verifier_rows: List[Dict[str, Any]],
    consolidated_verdict: str,
    reasons: List[str],
    footer_markdown: str,
) -> None:
    """Write the per-run JSON artefacts to disk.

    Layer 2 discipline: each run produces its own snapshot directory.
    No schema migration on the legacy context_item table; that table
    remains read-only for this harness pass.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "cbom.json").write_text(
        json.dumps(cbom.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "context_items.json").write_text(
        json.dumps(
            [
                {
                    "context_id": item.context_id,
                    "context_type": item.context_type,
                    "ledger_bucket": item.ledger_bucket,
                    "audit_status": item.audit_status,
                    "can_appear_in_final_prose": item.can_appear_in_final_prose,
                    "allowed_transformation": item.allowed_transformation,
                }
                for item in classified
            ],
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (out_dir / "boundary.json").write_text(
        json.dumps(
            {
                "verdict": boundary.verdict,
                "violations": [
                    {
                        "rule_id": v.rule_id,
                        "severity": v.severity,
                        "line_number": v.line_number,
                        "matched_text": v.matched_text,
                        "artefact_role": v.artefact_role,
                    }
                    for v in boundary.violations
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (out_dir / "claims.json").write_text(
        json.dumps(claim_rows, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "verifier.json").write_text(
        json.dumps(verifier_rows, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "verdict.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "verdict": consolidated_verdict,
                "reasons": reasons,
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    if footer_markdown:
        (out_dir / "footer.md").write_text(footer_markdown, encoding="utf-8")


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_text_report(report: Dict[str, Any]) -> str:
    lines = []
    lines.append("warrantos check")
    lines.append("  run id:        %s" % report["run_id"])
    lines.append("  profile:       %s" % report["profile"])
    lines.append("  draft chars:   %d" % report["draft_chars"])
    lines.append("  context items: %d" % report["context_items"])
    type_counts = report.get("by_context_type") or {}
    if type_counts:
        lines.append("  by context_type:")
        for k in sorted(type_counts):
            lines.append("    %-22s %d" % (k, type_counts[k]))
    lines.append("  claims detected: %d" % report["claims_detected"])
    lines.append("  claims supported: %d" % report["claims_supported"])
    lines.append("  claims unsupported: %d" % report["claims_unsupported"])
    if report.get("verifier_rows"):
        verifier_counts = report.get("by_verifier_verdict") or {}
        lines.append("  verifier verdicts: %d total" % report["verifier_total"])
        for k in sorted(verifier_counts):
            lines.append("    %-22s %d" % (k, verifier_counts[k]))
    lines.append(
        "  boundary: %s (%d violations)"
        % (report["boundary_verdict"], report["boundary_violations"])
    )
    lines.append("  overrides on record: %d" % report["overrides_total"])
    lines.append("")
    lines.append("VERDICT: " + report["verdict"])
    for reason in report.get("reasons") or []:
        lines.append("  - " + reason)
    lines.append("")
    lines.append("artefacts written to: " + report["out_dir"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _override_to_entry(o: Any) -> Dict[str, Any]:
    """Canonical ledger-entry dict for a HumanOverride (stable field set)."""
    return {
        "id": getattr(o, "id", None),
        "kind": "override",
        "run_id": getattr(o, "run_id", None),
        "reviewer": getattr(o, "reviewer", None),
        "gate_id": getattr(o, "gate_id", None),
        "failure_class": getattr(o, "failure_class", None),
        "single_actor": bool(getattr(o, "single_actor", False)),
        "ts": getattr(o, "ts", None),
    }


def _cmd_attest(args) -> int:
    from provenance import warrant_bundle
    from provenance.overrides import list_overrides_for_run

    run_dir = Path(args.run_dir)
    cbom_path = run_dir / "cbom.json"
    if not cbom_path.is_file():
        sys.stderr.write("warrantos attest: no cbom.json in run dir: %s\n" % run_dir)
        return 2
    try:
        prose = Path(args.prose).read_text(encoding="utf-8")
    except FileNotFoundError:
        sys.stderr.write("warrantos attest: prose file not found: %s\n" % args.prose)
        return 2

    cbom = json.loads(cbom_path.read_text(encoding="utf-8"))
    run_id = run_dir.name
    db = args.db or str(Path(".warrant") / "overrides.db")
    entries = [_override_to_entry(o) for o in list_overrides_for_run(db, run_id)]

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    bundle = warrant_bundle.create_warrant(
        prose=prose, cbom=cbom, ledger_entries=entries,
        run_id=run_id, timestamp=timestamp,
    )
    out = Path(args.out or (args.prose + ".warrant"))
    out.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    signed = "signed" if bundle.get("signed") else "unsigned (no signing key)"
    sys.stdout.write(
        "Wrote %s\n  root: %s\n  entries: %d  %s\n"
        % (out, bundle["checkpoint"]["root_hash"], len(entries), signed)
    )
    return 0


def _cmd_verify_external(args) -> int:
    from provenance import warrant_bundle

    try:
        bundle = json.loads(Path(args.warrant).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.stderr.write("warrantos verify-external: file not found: %s\n" % args.warrant)
        return 2
    prose = Path(args.prose).read_text(encoding="utf-8") if args.prose else None
    result = warrant_bundle.verify_warrant(
        bundle, prose=prose, expected_public_key_b64=args.key
    )
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "integrity: %s\nprose:     %s\nsignature: %s\nOVERALL:   %s\n"
            % (result["integrity"], result["prose"], result["signature"], result["overall"])
        )
    return 0 if result["overall"] == "VALID" else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        from provenance.status import (
            collect_status, render_markdown, render_text,
        )
        rows = collect_status()
        if args.json:
            sys.stdout.write(
                json.dumps([r.to_dict() for r in rows], indent=2, sort_keys=True) + "\n"
            )
        elif args.markdown:
            sys.stdout.write(render_markdown(rows))
        else:
            sys.stdout.write(render_text(rows) + "\n")
        return 0

    if args.command == "attest":
        return _cmd_attest(args)

    if args.command == "verify-external":
        return _cmd_verify_external(args)

    if args.command != "check":
        parser.print_help()
        return 0

    run_id = args.run_id or "run_" + uuid.uuid4().hex[:12]
    out_dir = Path(args.out_dir or (Path(".warrant") / "runs" / run_id))

    # --- Inputs ---
    try:
        draft = load_draft(args.draft)
    except FileNotFoundError:
        sys.stderr.write("warrantos: draft file not found: %s\n" % args.draft)
        return 2

    try:
        context_items_raw = load_context(args.context)
    except (ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write("warrantos: context file invalid: %s\n" % exc)
        return 2

    try:
        actor_identity = load_actor_identity(args.actor_identity)
    except (ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write("warrantos: actor identity file invalid: %s\n" % exc)
        return 2

    # --- Pipeline ---
    classified_pairs = classify_all(context_items_raw)
    classified = [item for item, _ in classified_pairs]

    boundary = scan_prose_boundary(draft, artefact_role=args.profile)

    claim_rows = detect_claims(draft)

    verifier_rows: List[Dict[str, Any]] = []
    verifier_skipped: Dict[str, Any] = {
        "reason": "verifier_not_invoked",
        "count": 0,
        "examples": [],
    }
    if args.verify:
        try:
            verifier_rows, verifier_skipped = run_verifier_capped(
                claim_rows,
                fetch=not args.no_fetch,
                salience_min=args.salience_min,
                max_claims=args.max_verify_claims,
            )
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write("warrantos: verifier internal error captured: %s\n" % exc)
            verifier_rows = []
            verifier_skipped = {
                "reason": "verifier_internal_error",
                "count": 0,
                "examples": [str(exc)[:200]],
            }

    # --- CBOM assembly (Codex C2 fix: correct API) ---
    context_inputs = [to_context_input(item, raw) for item, raw in classified_pairs]
    admitted_ids = [ci.context_id for ci in context_inputs if ci.admitted]
    claim_records = [to_claim_record(row, admitted_ids) for row in claim_rows]

    overrides_on_record = []
    try:
        overrides_on_record = list_overrides_for_run(args.db, run_id)
    except Exception:
        overrides_on_record = []

    cbom = build_cbom(
        context_inputs=context_inputs,
        claims=claim_records,
        artefact_id=Path(args.draft).name,
        actor_identity=actor_identity,
        classification_overrides=[],  # Day 5 does not emit overrides itself.
        override_ledger_refs=[str(o.id) for o in overrides_on_record],
    )

    # --- Layer 7 G3 self-grounding (informational; SPEC-L7-N003 SHALL FLAG) ---
    g3_result = None
    if args.writer_model:
        g3_result = check_self_grounding(
            writer_model=args.writer_model,
            verifier_model=args.verifier_model,
        )

    # --- Consolidated verdict ---
    # Separation of duties: did any human override on this run have the writer and
    # reviewer as the same actor? If so the verdict path enforces it (P0.1).
    single_actor_override = any(
        getattr(o, "single_actor", False) for o in overrides_on_record
    )
    verdict, reasons = consolidate_verdict(
        boundary,
        claim_rows,
        verifier_rows,
        actor_identity,
        cbom.classification_overrides,
        args.profile,
        single_actor_override=single_actor_override,
    )

    # G3 informational annotation in the reasons list. SPEC-L7-N003 SHALL
    # FLAG, not SHALL BLOCK; the flag is recorded but does not promote
    # the verdict to HOLD/BLOCK.
    if g3_result is not None and g3_result.verdict != "ok":
        reasons.append(
            "FLAG (G3 informational): %s [%s]" % (g3_result.verdict, g3_result.reason)
        )

    # --- Reader-facing footer (SPEC-L8-S005) ---
    footer_markdown = render_override_footer(overrides_on_record)

    # --- Persistence ---
    write_run_artefacts(
        out_dir,
        run_id=run_id,
        cbom=cbom,
        classified=classified,
        boundary=boundary,
        claim_rows=claim_rows,
        verifier_rows=verifier_rows,
        consolidated_verdict=verdict,
        reasons=reasons,
        footer_markdown=footer_markdown,
    )

    # --- Report ---
    type_counts: Dict[str, int] = {}
    for item in classified:
        type_counts[item.context_type] = type_counts.get(item.context_type, 0) + 1
    verifier_counts: Dict[str, int] = {}
    for v in verifier_rows:
        verifier_counts[v["verdict"]] = verifier_counts.get(v["verdict"], 0) + 1

    report = {
        "run_id": run_id,
        "profile": args.profile,
        "draft_chars": len(draft),
        "context_items": len(classified),
        "by_context_type": type_counts,
        "claims_detected": len(claim_rows),
        "claims_supported": sum(1 for c in claim_rows if c.get("citation")),
        "claims_unsupported": sum(1 for c in claim_rows if not c.get("citation")),
        "verifier_rows": verifier_rows,
        "verifier_total": len(verifier_rows),
        "by_verifier_verdict": verifier_counts,
        "boundary_verdict": boundary.verdict,
        "boundary_violations": len(boundary.violations),
        "overrides_total": len(overrides_on_record),
        "verdict": verdict,
        "reasons": reasons,
        "out_dir": str(out_dir),
        "cbom_schema": cbom.schema,
        "load_bearing_threshold": LOAD_BEARING_THRESHOLD,
        "g3_self_grounding": g3_result.to_dict() if g3_result is not None else None,
        "verifier_skipped": verifier_skipped,
    }

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(format_text_report(report) + "\n")

    if args.ci and verdict in {VERDICT_HOLD, VERDICT_BLOCK, VERDICT_NOT_ASSESSABLE}:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
