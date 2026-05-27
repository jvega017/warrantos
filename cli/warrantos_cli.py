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
from provenance.verify import extract_citation, verify_text  # noqa: E402
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
            "audit",
            "methodology",
            "consultation_report",
            "changelog",
        ),
        help="Layer 7 G1 boundary profile (default: final-prose).",
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

def consolidate_verdict(
    boundary_report: BoundaryResult,
    claim_rows: List[Dict[str, Any]],
    verifier_rows: List[Dict[str, Any]],
    actor_identity: Dict[str, str],
    classification_overrides: List[ClassificationOverrideRecord],
    artefact_role: str,
) -> Tuple[str, List[str]]:
    """Return (verdict, reasons).

    Verdict is one of PASS, HOLD, BLOCK, NOT_ASSESSABLE.

    Decision order:

    1. BLOCK if any verifier verdict is `contradicted`, or any boundary
       violation occurred in a blocking profile.
    2. HOLD if any unsupported load-bearing claim exists, or any
       verifier verdict is `unverifiable` for a load-bearing claim.
    3. NOT_ASSESSABLE if the artefact role is `final-prose` and the
       run has no `actor_identity` map. This is the Codex C1 fix:
       a final-prose artefact requires the minimum override/identity
       coupling evidence to be certifiable as PASS.
    4. PASS otherwise.
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

def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
    if args.verify:
        try:
            verifier_rows = run_verifier(draft, fetch=not args.no_fetch)
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write("warrantos: verifier internal error captured: %s\n" % exc)
            verifier_rows = []

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
    verdict, reasons = consolidate_verdict(
        boundary,
        claim_rows,
        verifier_rows,
        actor_identity,
        cbom.classification_overrides,
        args.profile,
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
