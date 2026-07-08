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
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make the repository root importable when running this file directly.
# File is at <root>/warrantos/cli/warrantos_cli.py, so the root is three up.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from warrantos.provenance.pathguard import RUN_ID_RE, resolve_under  # noqa: E402
from warrantos.provenance.cbom import (  # noqa: E402
    CBOM,
    ClaimRecord,
    ClassificationOverrideRecord,
    ContextInput,
    build_cbom,
)
from warrantos.provenance.context_admissibility import (  # noqa: E402
    BoundaryResult,
    ContextItem,
    classify_context,
    scan_prose_boundary,
)
from warrantos.provenance.footer import render_override_footer  # noqa: E402
from warrantos.provenance.overrides import list_overrides_for_run  # noqa: E402
from warrantos.provenance.salience import LOAD_BEARING_THRESHOLD, is_load_bearing  # noqa: E402
from warrantos.provenance.verify import extract_citation, verify_claim, verify_text  # noqa: E402
from warrantos.provenance.extract import CLAIM_TRIGGERS, sentences  # noqa: E402
from warrantos.provenance.gates import check_self_grounding  # noqa: E402
from warrantos import __version__  # noqa: E402


VERDICT_PASS = "PASS"
VERDICT_HOLD = "HOLD"
VERDICT_BLOCK = "BLOCK"
VERDICT_NOT_ASSESSABLE = "NOT_ASSESSABLE"

_NON_FINAL_PROFILES = frozenset({
    "audit", "methodology", "consultation_report", "changelog",
})

# Profiles for which scan_prose_boundary() returns pass unconditionally,
# suppressing the G1 prose-boundary gate. Kept in sync with
# context_admissibility.scan_prose_boundary. Used for verdict transparency
# so a PASS under these profiles names the suppression.
_BOUNDARY_SUPPRESSING_PROFILES = frozenset({
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
    # An audit tool should be able to report which version produced a verdict.
    parser.add_argument(
        "--version",
        action="version",
        version="warrantos %s" % __version__,
        help="Print the WarrantOS version and exit.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser(
        "demo",
        help="Run the bundled honest demo (a real BLOCK verdict, no setup).",
        description=(
            "Run WarrantOS over a bundled synthetic AI-style draft that "
            "deliberately contains unsupported claims and scaffold residue. "
            "Returns a BLOCK verdict. Zero setup: the fixtures ship with the "
            "package, so this works from a clean install."
        ),
    )

    init_p = sub.add_parser(
        "init",
        help="Scaffold context.json and actor.json templates to start from.",
        description=(
            "Write starter context.json and actor.json files into a directory "
            "so a first-time user does not have to reverse-engineer the "
            "actor-identity six-role schema. Existing files are never "
            "overwritten unless --force is given."
        ),
    )
    init_p.add_argument(
        "--dir",
        default=".",
        help="Directory to write the templates into (default: current directory).",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing context.json / actor.json.",
    )

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
    check.add_argument(
        "draft",
        nargs="*",
        default=None,
        help=(
            "Path(s) to draft Markdown file(s). Each draft gets its own run. "
            "Optional only with --explain-profile."
        ),
    )
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
        default=os.environ.get(
            "WARRANTOS_DB", str(Path(".warrant") / "provenance.db")
        ),
        help=(
            "Path to the override ledger database. Used to look up overrides. "
            "Defaults to the WARRANTOS_DB environment variable when set, "
            "otherwise ./.warrant/provenance.db."
        ),
    )
    check.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Defaults to .warrant/runs/<run_id>/.",
    )
    check.add_argument(
        "--explain-profile",
        action="store_true",
        help=(
            "Print what each profile suppresses (boundary-gate suppression and "
            "the unsupported-fraction HOLD threshold) and exit without running "
            "the pipeline."
        ),
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
        "--sensitivity-check",
        action="store_true",
        help=(
            "Run the F-classification sensitivity gate over the draft "
            "before the pipeline. Material classified at a blocking tier "
            "(Sensitive/Protected or Credentials, per the default data "
            "gate) causes the command to refuse to process and exit "
            "non-zero. The keyword heuristics are a starter set; extend "
            "them for production. Off by default."
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

    # --- slop: zero-configuration AI scaffold-residue scanner ---
    slop_p = sub.add_parser(
        "slop",
        help="Scan docs for AI scaffold residue and print a SLOP SCORE.",
        description=(
            "Zero-configuration scanner for AI-assistant scaffold residue in "
            "documentation (.md, .rst, .txt). Recursively scans the given "
            "paths (default: the current directory), skipping .git, "
            "node_modules, dist, build, .venv and __pycache__. Each finding "
            "reports its category (chat bleed, identity leak, sign-off "
            "residue, scaffold, placeholder) and the command prints a "
            "density-based SLOP SCORE from 0.0 to 10.0. Uses the same "
            "canonical pattern list as the Layer 7 G1 prose-boundary gate. "
            "Exits 0 regardless of findings unless --fail-over is given."
        ),
    )
    slop_p.add_argument(
        "paths",
        nargs="*",
        default=[],
        help="Files or directories to scan (default: current directory).",
    )
    slop_p.add_argument(
        "--json",
        action="store_true",
        help="Emit the scan report as JSON on stdout.",
    )
    slop_p.add_argument(
        "--badge",
        action="store_true",
        help=(
            "Print a shields.io badge URL only (green 'slop free' at zero "
            "findings, red score badge otherwise)."
        ),
    )
    slop_p.add_argument(
        "--fail-over",
        type=float,
        default=None,
        metavar="THRESHOLD",
        help=(
            "Exit 1 when the SLOP SCORE exceeds THRESHOLD (CI opt-in; "
            "default behaviour is exit 0 regardless of findings)."
        ),
    )
    slop_p.add_argument(
        "--include-fences",
        action="store_true",
        help=(
            "Also scan lines inside fenced code blocks. By default fenced "
            "blocks are skipped: they usually quote command output or code "
            "where residue strings are deliberate examples."
        ),
    )

    # --- tells: opinionated AI-writing-style scanner (sibling of slop) ---
    tells_p = sub.add_parser(
        "tells",
        help="Scan docs for AI-writing style tells and print a TELL SCORE.",
        description=(
            "Opinionated scanner for prose that reads as machine-written "
            "even once chat residue is gone: contrastive negation, hedge "
            "stacking, em/en-dash punctuation, AI filler phrases, and a "
            "drumbeat of formulaic paragraph-openers. Where `warrantos "
            "slop` is objective (near-unambiguous chat bleed), `tells` is "
            "house style: every rule is a judgement call, and the score is "
            "a prompt for review, never proof of authorship. Recursively "
            "scans the given paths (default: the current directory), "
            "skipping .git, node_modules, dist, build, .venv and "
            "__pycache__. Each finding reports its category and rule id "
            "and the command prints a density-based TELL SCORE from 0.0 "
            "to 10.0, the same formula as SLOP SCORE. Exits 0 regardless "
            "of findings unless --fail-over is given."
        ),
    )
    tells_p.add_argument(
        "paths",
        nargs="*",
        default=[],
        help="Files or directories to scan (default: current directory).",
    )
    tells_p.add_argument(
        "--json",
        action="store_true",
        help="Emit the scan report as JSON on stdout.",
    )
    tells_p.add_argument(
        "--badge",
        action="store_true",
        help=(
            "Print a shields.io badge URL only (green 'tells clean' at "
            "zero findings, red score badge otherwise)."
        ),
    )
    tells_p.add_argument(
        "--fail-over",
        type=float,
        default=None,
        metavar="THRESHOLD",
        help=(
            "Exit 1 when the TELL SCORE exceeds THRESHOLD (CI opt-in; "
            "default behaviour is exit 0 regardless of findings)."
        ),
    )
    tells_p.add_argument(
        "--include-fences",
        action="store_true",
        help=(
            "Also scan lines inside fenced code blocks. By default fenced "
            "blocks are skipped: they usually quote command output or code "
            "where the flagged phrasing is a deliberate example."
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
    verify.add_argument(
        "--allow-unsigned", action="store_true",
        help="Accept an integrity-valid but UNSIGNED bundle as overall VALID. "
             "By default an unsigned or unverifiable signature is overall INVALID.",
    )
    verify.add_argument("--json", action="store_true", help="Emit the verdict as JSON.")

    # --- calibrate: run the eval harness and write .warrant/calibration.json ---
    calibrate = sub.add_parser(
        "calibrate",
        help="Run the grader eval corpus and write .warrant/calibration.json.",
        description=(
            "Run the Layer 7 G5 calibration: evaluate the grader against the "
            "labelled eval corpus (eval/run_eval.py) and write a "
            "calibration.json summary (grader, corpus size, per-class recall, "
            "coverage estimate) into .warrant/. The stored artefact can then "
            "be loaded by check_calibration() without re-running the eval."
        ),
    )
    calibrate.add_argument(
        "--grader",
        choices=("heuristic", "llm", "codex"),
        default="heuristic",
        help="Which grader to calibrate (default: heuristic, free/offline).",
    )
    calibrate.add_argument(
        "--grader-corpus",
        default=None,
        help="Path to the grader JSONL corpus (default: the bundled eval corpus).",
    )
    calibrate.add_argument(
        "--out",
        default=None,
        help="Output path for calibration.json (default: .warrant/calibration.json).",
    )
    calibrate.add_argument(
        "--json", action="store_true",
        help="Emit the calibration summary as JSON on stdout.",
    )

    # --- metrics: F-metrics shadow-log aggregation ---
    metrics_p = sub.add_parser(
        "metrics",
        help="Aggregate the shadow-observation log into .warrant/metrics.json.",
        description=(
            "F-metrics: read the shadow-observation JSON-lines log produced "
            "by tools/warrantos-shadow-observe.py and compute an aggregate "
            "(verdict distribution, unsupported-claim rate over the window, "
            "and a simple improving/worsening/stable trend split across the "
            "earlier and later halves of the observed rows). A missing or "
            "empty log is handled gracefully (observed=0, "
            "trend=insufficient_data). Writes .warrant/metrics.json unless "
            "--no-write is given."
        ),
    )
    metrics_p.add_argument(
        "--log",
        default=None,
        help=(
            "Path to the shadow-observation log "
            "(default: 08_Outputs/publish-gate-shadow.log under the repo)."
        ),
    )
    metrics_p.add_argument(
        "--out",
        default=None,
        help="Output path for metrics.json (default: .warrant/metrics.json).",
    )
    metrics_p.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write metrics.json; only emit the aggregate.",
    )
    metrics_p.add_argument(
        "--json", action="store_true",
        help="Emit the aggregate as JSON on stdout.",
    )

    # --- retention: F-retention tombstones (INV-011) ---
    retention = sub.add_parser(
        "retention",
        help="Manage F-retention windows and tombstones (no hard delete).",
        description=(
            "F-retention (INV-011): set a per-run retention window, list runs "
            "whose window has elapsed, and tombstone expired runs. Tombstoning "
            "is APPEND-ONLY: it marks a run as logically retired without "
            "deleting any ledger row, preserving the append-only audit trail."
        ),
    )
    retention.add_argument(
        "--db",
        default=os.environ.get(
            "WARRANTOS_DB", str(Path(".warrant") / "provenance.db")
        ),
        help=(
            "Path to the provenance ledger database. Defaults to the "
            "WARRANTOS_DB environment variable when set, otherwise "
            "./.warrant/provenance.db."
        ),
    )
    retention.add_argument(
        "--json", action="store_true",
        help="Emit the result as JSON on stdout.",
    )
    retention_sub = retention.add_subparsers(
        dest="retention_action", metavar="<action>"
    )

    rset = retention_sub.add_parser(
        "set-window",
        help="Record a retention window (days) for a run (append-only).",
    )
    rset.add_argument("--run-id", type=int, required=True, help="provenance_run id.")
    rset.add_argument(
        "--days", type=int, required=True,
        help="Retention window in days (>= 0). Use 0 to expire immediately.",
    )

    retention_sub.add_parser(
        "list-expired",
        help="List runs whose effective window has elapsed (read-only).",
    )

    rtomb = retention_sub.add_parser(
        "tombstone-run",
        help="Append a tombstone for a run (logical retire; no delete).",
    )
    rtomb.add_argument("--run-id", type=int, required=True, help="provenance_run id.")
    rtomb.add_argument(
        "--reason", default="retention_window_elapsed",
        help="Reason recorded on the tombstone (default: retention_window_elapsed).",
    )

    retention_sub.add_parser(
        "list", help="List all tombstones (read-only)."
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
    from warrantos.provenance.salience import score_claim

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

# Per-profile unsupported-claim fraction thresholds (Phase 1 item 3).
# When the fraction of detected claims that are unsupported exceeds the
# profile threshold, the verdict is raised to HOLD even when no single claim
# is load-bearing. This closes the bug where an audit run with 2 of 2 claims
# unsupported could return a bare PASS (the audit profile suppresses the
# boundary gate, and neither claim alone was load-bearing).
#
#   audit         0.00  any unsupported claim HOLDs
#   final-prose   0.00  backstop: any unsupported claim HOLDs
#   paper-full    0.20  tolerates a small uncited minority
#   brief-light   0.25  tolerates routine date references etc.
#   methodology   0.40  methods prose is allowed more uncited statement
#   changelog     1.00  never fires on fraction alone
_PROFILE_UNSUPPORTED_THRESHOLD: Dict[str, float] = {
    "audit": 0.0,
    "final-prose": 0.0,
    "paper-full": 0.20,
    "brief-light": 0.25,
    "methodology": 0.40,
    "changelog": 1.0,
}
# Profiles without an explicit entry use this default (lenient: never fires
# on fraction alone, preserving prior behaviour for prompt-template and the
# other process profiles).
_DEFAULT_UNSUPPORTED_THRESHOLD = 1.0


def consolidate_verdict(
    boundary_report: BoundaryResult,
    claim_rows: List[Dict[str, Any]],
    verifier_rows: List[Dict[str, Any]],
    actor_identity: Dict[str, str],
    classification_overrides: List[ClassificationOverrideRecord],
    artefact_role: str,
    single_actor_override: bool = False,
) -> Tuple[str, List[str], Optional[Dict[str, Any]]]:
    """Return (verdict, reasons, fired_rule).

    Verdict is one of PASS, HOLD, BLOCK, NOT_ASSESSABLE.

    `fired_rule` is None unless the per-profile unsupported-fraction
    threshold raised the verdict to HOLD, in which case it is a dict
    describing the rule that fired (for surfacing in the run report JSON).

    Decision order:

    1. BLOCK if any verifier verdict is `contradicted`, any boundary
       violation occurred in a blocking profile, or a same-actor review
       (single_actor_override) was recorded on a strict profile (SoD).
    2. HOLD if any unsupported load-bearing claim exists, any verifier
       verdict is `unverifiable` for a load-bearing claim, the unsupported
       fraction exceeds the per-profile threshold
       (`_PROFILE_UNSUPPORTED_THRESHOLD`), or a same-actor review was
       recorded on a final-artefact profile (separation of duties,
       SPEC-L8-S003: an independent reviewer is required to PASS).
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
    fired_rule: Optional[Dict[str, Any]] = None
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
        return (VERDICT_BLOCK, reasons, fired_rule)

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

    # Per-profile unsupported-fraction threshold (Phase 1 item 3).
    # Raise HOLD when the unsupported fraction exceeds the profile threshold,
    # even if no single claim is load-bearing. Surface the fired rule.
    total_claims = len(claim_rows)
    unsupported_claims = sum(1 for c in claim_rows if not c.get("citation"))
    if total_claims > 0:
        unsupported_fraction = unsupported_claims / total_claims
        threshold = _PROFILE_UNSUPPORTED_THRESHOLD.get(
            role_lower, _DEFAULT_UNSUPPORTED_THRESHOLD
        )
        if unsupported_fraction > threshold:
            fired_rule = {
                "rule": "profile_unsupported_fraction",
                "profile": role_lower,
                "unsupported": unsupported_claims,
                "total": total_claims,
                "unsupported_fraction": round(unsupported_fraction, 4),
                "threshold": threshold,
            }
            reasons.append(
                "HOLD: unsupported fraction %d/%d (%.0f%%) exceeds the '%s' "
                "profile threshold of %.0f%%; verify the uncited claims or add "
                "sources."
                % (
                    unsupported_claims,
                    total_claims,
                    unsupported_fraction * 100,
                    role_lower,
                    threshold * 100,
                )
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
        return (VERDICT_HOLD, reasons, fired_rule)

    # 3. NOT_ASSESSABLE (Codex C1)
    if role_lower == "final-prose" and not actor_identity:
        reasons.append(
            "NOT_ASSESSABLE: final-prose artefact requires actor_identity to "
            "certify the override/identity leg of the coupling thesis. No "
            "actor_identity supplied. Either provide --actor-identity or use "
            "a non-final-prose profile."
        )
        return (VERDICT_NOT_ASSESSABLE, reasons, fired_rule)

    return (VERDICT_PASS, reasons, fired_rule)


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

def explain_profiles() -> str:
    """Describe, per profile, what is suppressed.

    Phase 1 item 2: makes profile leniency self-documenting. Two suppression
    surfaces are reported: whether the G1 prose-boundary gate is suppressed,
    and the per-profile unsupported-fraction HOLD threshold.
    """
    profiles = [
        "final-prose",
        "brief-light",
        "paper-full",
        "prompt-template",
        "audit",
        "methodology",
        "consultation_report",
        "changelog",
    ]
    lines = ["warrantos profiles: what each profile suppresses", ""]
    lines.append(
        "  %-20s %-18s %s" % ("profile", "boundary gate", "unsupported-fraction HOLD")
    )
    lines.append("  " + "-" * 70)
    for p in profiles:
        boundary = (
            "SUPPRESSED" if p in _BOUNDARY_SUPPRESSING_PROFILES else "enforced"
        )
        threshold = _PROFILE_UNSUPPORTED_THRESHOLD.get(
            p, _DEFAULT_UNSUPPORTED_THRESHOLD
        )
        if threshold >= 1.0:
            thr = "never (fraction alone never HOLDs)"
        else:
            thr = "HOLD when unsupported fraction > %.0f%%" % (threshold * 100)
        lines.append("  %-20s %-18s %s" % (p, boundary, thr))
    lines.append("")
    lines.append(
        "Notes: a SUPPRESSED boundary gate means scan_prose_boundary() returns "
        "pass unconditionally for that profile, so AI-residue and "
        "process-narration leakage is not gated. A PASS under such a profile "
        "still reports any unsupported-claim count on the verdict line so the "
        "leniency is visible. Load-bearing unsupported claims always HOLD "
        "regardless of profile."
    )
    return "\n".join(lines)


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

    # Verdict transparency (Phase 1 item 2): always make the unsupported-claims
    # count visible on the verdict line, and annotate a PASS that carries
    # unsupported claims so leniency is never silent. Profiles that suppress
    # the boundary gate (audit/methodology/consultation_report/changelog) say so.
    verdict = report["verdict"]
    unsupported = report.get("claims_unsupported", 0)
    verdict_line = "VERDICT: " + verdict
    if verdict == VERDICT_PASS and unsupported > 0:
        profile = report.get("profile", "")
        if profile in _BOUNDARY_SUPPRESSING_PROFILES:
            verdict_line += (
                " (%d unsupported claim(s); %s profile suppresses the prose "
                "boundary gate; verify manually)" % (unsupported, profile)
            )
        else:
            verdict_line += (
                " (%d unsupported claim(s); none load-bearing under this "
                "profile; verify manually)" % unsupported
            )
    lines.append(verdict_line)
    for reason in report.get("reasons") or []:
        lines.append("  - " + reason)
    fired = report.get("verdict_rule_fired")
    if fired:
        lines.append(
            "  rule fired: %s (%d/%d unsupported = %.0f%% > %.0f%% threshold for '%s')"
            % (
                fired.get("rule"),
                fired.get("unsupported", 0),
                fired.get("total", 0),
                fired.get("unsupported_fraction", 0.0) * 100,
                fired.get("threshold", 0.0) * 100,
                fired.get("profile", ""),
            )
        )
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
    from warrantos.provenance import warrant_bundle
    from warrantos.provenance.overrides import list_overrides_for_run

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

    # B5 path containment: confine --db and --out under cwd.
    _cwd = Path(".").resolve()
    raw_db = args.db or str(Path(".warrant") / "overrides.db")
    try:
        db = str(resolve_under(_cwd, raw_db))
    except ValueError as exc:
        sys.stderr.write(
            "warrantos attest: --db path is outside the current working directory: %s\n" % exc
        )
        return 2

    raw_out = args.out or (args.prose + ".warrant")
    try:
        out = resolve_under(_cwd, raw_out)
    except ValueError as exc:
        sys.stderr.write(
            "warrantos attest: --out path is outside the current working directory: %s\n" % exc
        )
        return 2

    cbom = json.loads(cbom_path.read_text(encoding="utf-8"))
    run_id = run_dir.name
    entries = [_override_to_entry(o) for o in list_overrides_for_run(db, run_id)]

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    bundle = warrant_bundle.create_warrant(
        prose=prose, cbom=cbom, ledger_entries=entries,
        run_id=run_id, timestamp=timestamp,
    )
    out = Path(out)
    out.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    if bundle.get("signed"):
        signed = "signed"
    else:
        signed = "UNSIGNED (set WARRANTOS_SIGNING_KEY to attribute; verify needs --allow-unsigned)"
    sys.stdout.write(
        "Wrote %s\n  root: %s\n  entries: %d  %s\n"
        % (out, bundle["checkpoint"]["root_hash"], len(entries), signed)
    )
    return 0


def _cmd_verify_external(args) -> int:
    from warrantos.provenance import warrant_bundle

    try:
        bundle = json.loads(Path(args.warrant).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.stderr.write("warrantos verify-external: file not found: %s\n" % args.warrant)
        return 2
    prose = Path(args.prose).read_text(encoding="utf-8") if args.prose else None
    result = warrant_bundle.verify_warrant(
        bundle, prose=prose, expected_public_key_b64=args.key,
        allow_unsigned=args.allow_unsigned,
    )
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "integrity: %s\nprose:     %s\nsignature: %s\nOVERALL:   %s\n"
            % (result["integrity"], result["prose"], result["signature"], result["overall"])
        )
    return 0 if result["overall"] == "VALID" else 1


def _cmd_calibrate(args) -> int:
    """G5 calibration: run the grader eval corpus and write calibration.json.

    Reuses eval/run_eval.py's corpus loader, grader runner, and metric
    computation so the calibration figures come from the same code that
    produces the published eval report. Writes a compact summary
    (grader, corpus size, per-class recall, coverage estimate) into
    .warrant/calibration.json for check_calibration() to load.
    """
    import importlib.util

    eval_path = _REPO_ROOT / "eval" / "run_eval.py"
    if not eval_path.is_file():
        sys.stderr.write("warrantos calibrate: eval/run_eval.py not found at %s\n" % eval_path)
        return 2
    spec = importlib.util.spec_from_file_location("_warrantos_run_eval", str(eval_path))
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)

    from warrantos.provenance.grade import HeuristicGrader

    if args.grader == "heuristic":
        grader, grader_label = HeuristicGrader(), "HeuristicGrader"
    elif args.grader == "llm":
        from warrantos.provenance.grade import LLMGrader
        grader, grader_label = LLMGrader(), "LLMGrader"
    else:  # codex
        from warrantos.provenance.grade import CodexGrader
        grader, grader_label = CodexGrader(), "CodexGrader"

    corpus_path = args.grader_corpus or str(
        _REPO_ROOT / "eval" / "corpus" / "grader.jsonl"
    )
    items = run_eval.load_grader_corpus(corpus_path)
    results = run_eval.grade_grader_corpus(items, grader)
    metrics = run_eval.compute_grader_metrics(results)

    # Coverage estimate: the fraction of corpus rows whose graded verdict
    # is a typed calibration label (verified/contradicted). The offline
    # heuristic emits no numeric confidence, so confidence-coverage is 0;
    # the typed-fraction is the honest stand-in the heuristic CAN report.
    typed_labels = {"verified", "contradicted"}
    typed = sum(1 for _id, _gold, pred in results if pred in typed_labels)
    corpus_size = metrics["n"]
    coverage_estimate = (typed / corpus_size) if corpus_size else 0.0

    per_class_recall = {
        cls: round(d["recall"], 4) for cls, d in metrics["per_class"].items()
    }

    summary = {
        "grader": grader_label,
        "corpus": corpus_path,
        "corpus_size": corpus_size,
        "typed": typed,
        "per_class_recall": per_class_recall,
        "macro_recall": round(metrics["macro"]["recall"], 4),
        "accuracy": round(metrics["accuracy"], 4),
        "coverage_estimate": round(coverage_estimate, 4),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "G5 calibration summary. The offline HeuristicGrader emits no "
            "numeric confidence, so Brier-style confidence coverage is 0; "
            "coverage_estimate reports the typed-verdict fraction and "
            "per_class_recall is the meaningful calibration measure. Use an "
            "LLM grader for confidence-bearing calibration."
        ),
    }

    _cwd = Path(".").resolve()
    raw_out = args.out or str(Path(".warrant") / "calibration.json")
    try:
        out = resolve_under(_cwd, raw_out)
    except ValueError as exc:
        sys.stderr.write(
            "warrantos calibrate: --out path is outside the current working directory: %s\n" % exc
        )
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "warrantos calibrate\n"
            "  grader:            %s\n"
            "  corpus size:       %d\n"
            "  macro recall:      %.4f\n"
            "  accuracy:          %.4f\n"
            "  coverage estimate: %.4f (typed-verdict fraction)\n"
            "  written to:        %s\n"
            % (
                grader_label, corpus_size, summary["macro_recall"],
                summary["accuracy"], coverage_estimate, out,
            )
        )
    return 0


def _cmd_metrics(args) -> int:
    """F-metrics: aggregate the shadow-observation log into metrics.json.

    Reads the shadow JSON-lines log (default
    08_Outputs/publish-gate-shadow.log under the repo root), computes
    the verdict distribution, unsupported-claim rate, and trend via
    provenance.metrics.aggregate_shadow_log, and writes the aggregate
    to .warrant/metrics.json unless --no-write is given. A missing or
    empty log is handled gracefully.
    """
    from warrantos.provenance.metrics import (
        aggregate_shadow_log,
        write_metrics_json,
    )

    if args.log:
        log_path = Path(args.log)
    else:
        log_path = _REPO_ROOT / "08_Outputs" / "publish-gate-shadow.log"

    metrics = aggregate_shadow_log(log_path)

    if not args.no_write:
        _cwd = Path(".").resolve()
        raw_out = args.out or str(Path(".warrant") / "metrics.json")
        try:
            out = resolve_under(_cwd, raw_out)
        except ValueError as exc:
            sys.stderr.write(
                "warrantos metrics: --out path is outside the current "
                "working directory: %s\n" % exc
            )
            return 2
        write_metrics_json(metrics, out)
    else:
        out = None

    if args.json:
        sys.stdout.write(
            json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n"
        )
    else:
        d = metrics.to_dict()
        verdicts = d["verdict_distribution"]
        verdict_str = (
            ", ".join("%s=%d" % (k, verdicts[k]) for k in sorted(verdicts))
            if verdicts else "(none)"
        )
        rate = d["unsupported_rate"]
        rate_str = "n/a" if rate is None else ("%.4f" % rate)
        sys.stdout.write(
            "warrantos metrics\n"
            "  log:                 %s%s\n"
            "  observed rows:       %d\n"
            "  non-observed rows:   %d\n"
            "  malformed lines:     %d\n"
            "  verdict distribution:%s %s\n"
            "  unsupported rate:    %s\n"
            "  trend:               %s\n"
            "  window:              %s -> %s\n"
            "  written to:          %s\n"
            % (
                log_path,
                "" if log_path.is_file() else " (not found; empty aggregate)",
                d["observed"],
                d["non_observed"],
                d["malformed_lines"],
                "", verdict_str,
                rate_str,
                d["trend"],
                d["window_start"] or "n/a",
                d["window_end"] or "n/a",
                out if out is not None else "(not written; --no-write)",
            )
        )
    return 0


def _cmd_retention(args) -> int:
    """F-retention (INV-011): set-window / list-expired / tombstone-run / list.

    Tombstoning never deletes a ledger row; it appends a marker so the
    append-only guarantee (INV-004) is preserved.
    """
    from warrantos.provenance import retention as _retention

    action = getattr(args, "retention_action", None)
    if not action:
        sys.stderr.write(
            "warrantos retention: an action is required "
            "(set-window | list-expired | tombstone-run | list)\n"
        )
        return 2

    # B5 path containment: confine --db under cwd.
    _cwd = Path(".").resolve()
    try:
        db = str(resolve_under(_cwd, args.db))
    except ValueError as exc:
        sys.stderr.write(
            "warrantos retention: --db path is outside the current working directory: %s\n"
            % exc
        )
        return 2

    as_json = getattr(args, "json", False)

    if action == "set-window":
        try:
            _retention.set_window(db, args.run_id, args.days)
        except ValueError as exc:
            sys.stderr.write("warrantos retention: %s\n" % exc)
            return 2
        msg = {
            "action": "set-window",
            "run_id": args.run_id,
            "retention_window_days": args.days,
        }
        if as_json:
            sys.stdout.write(json.dumps(msg, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                "retention window set: run %d -> %d day(s) (recorded append-only)\n"
                % (args.run_id, args.days)
            )
        return 0

    if action == "list-expired":
        expired = _retention.list_expired(db)
        if as_json:
            sys.stdout.write(
                json.dumps([e.to_dict() for e in expired], indent=2, sort_keys=True) + "\n"
            )
        else:
            if not expired:
                sys.stdout.write("no runs have passed their retention window.\n")
            else:
                sys.stdout.write("expired runs (window elapsed, not yet tombstoned):\n")
                for e in expired:
                    sys.stdout.write(
                        "  run %d  window=%dd  expired_after=%s\n"
                        % (e.run_id, e.retention_window_days, e.expired_after)
                    )
        return 0

    if action == "tombstone-run":
        tomb = _retention.tombstone_run(db, args.run_id, reason=args.reason)
        if as_json:
            sys.stdout.write(json.dumps(tomb.to_dict(), indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                "tombstone appended: run %d  reason=%s  (no ledger row deleted)\n"
                % (tomb.run_id, tomb.reason)
            )
        return 0

    if action == "list":
        tombs = _retention.list_tombstones(db)
        if as_json:
            sys.stdout.write(
                json.dumps([t.to_dict() for t in tombs], indent=2, sort_keys=True) + "\n"
            )
        else:
            if not tombs:
                sys.stdout.write("no tombstones recorded.\n")
            else:
                sys.stdout.write("tombstones:\n")
                for t in tombs:
                    sys.stdout.write(
                        "  #%d  run %d  reason=%s  ts=%s\n"
                        % (t.id, t.run_id, t.reason, t.ts)
                    )
        return 0

    sys.stderr.write("warrantos retention: unknown action %r\n" % action)
    return 2


# Starter templates for `warrantos init`. The actor map is the canonical
# six-role registry; writer and reviewer are deliberately different identities
# so the default scaffold does not trip the separation-of-duties rule.
_INIT_ACTOR_TEMPLATE = {
    "context_classifier": "agent:your-classifier",
    "insight_compiler": "human:your.name",
    "source_curator": "human:your.name",
    "clean_room_writer": "model:claude-opus-4-8",
    "reviewer_qa": "human:your.reviewer",
    "auditor": "human:your.auditor",
}

_INIT_CONTEXT_TEMPLATE = [
    {
        "id": "ctx_001",
        "text": (
            "Replace this with a piece of source material, feedback, or "
            "instruction that informed the draft."
        ),
    }
]


def _cmd_init(args) -> int:
    """Scaffold context.json and actor.json so a first run has its inputs."""
    target = Path(getattr(args, "dir", ".") or ".")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.stderr.write("warrantos init: cannot create %s: %s\n" % (target, exc))
        return 2

    force = bool(getattr(args, "force", False))
    plan = [
        ("actor.json", _INIT_ACTOR_TEMPLATE),
        ("context.json", _INIT_CONTEXT_TEMPLATE),
    ]
    written = []
    skipped = []
    for name, payload in plan:
        dest = target / name
        if dest.exists() and not force:
            skipped.append(name)
            continue
        dest.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        written.append(name)

    for name in written:
        sys.stdout.write("created %s\n" % (target / name))
    for name in skipped:
        sys.stdout.write(
            "skipped %s (already exists; pass --force to overwrite)\n"
            % (target / name)
        )

    sys.stdout.write(
        "\nactor.json maps the six provenance roles to identities. Use the\n"
        "human: / model: / agent: prefixes. Keep clean_room_writer and\n"
        "reviewer_qa as different identities: the separation-of-duties rule\n"
        "downgrades a final-prose verdict to HOLD when one actor is both.\n"
        "\nNext: write your draft, then run\n"
        "  warrantos check YOUR_DRAFT.md \\\n"
        "    --context %s \\\n"
        "    --actor-identity %s --profile final-prose\n"
        % (target / "context.json", target / "actor.json")
    )
    # Treat an all-skipped run as a soft no-op success; nothing was harmed.
    return 0


def _cmd_demo(args) -> int:
    """Run the bundled honest demo from package data. Zero setup required.

    The three fixtures ship as package-data inside warrantos/demo_assets/, so
    this works from a clean `pip install` with no repository checkout. The run
    is isolated to a temporary directory so it never writes into the user's
    working tree.
    """
    import tempfile
    from importlib import resources

    assets = resources.files("warrantos") / "demo_assets"
    sys.stdout.write(
        "WarrantOS honest demo\n"
        "---------------------\n"
        "Checking a synthetic AI-style draft that deliberately contains\n"
        "unsupported factual claims and conversational scaffold residue.\n"
        "Expect a BLOCK verdict.\n\n"
    )
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="warrantos-demo-") as tmp:
        tmp_path = Path(tmp)
        for name in ("draft.md", "context.json", "actor.json"):
            (tmp_path / name).write_text(
                (assets / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
        # Run from inside the temp dir so the B5 path-containment guard (which
        # confines outputs under cwd) is satisfied and the demo never writes
        # into the user's working tree. Relative paths keep everything contained.
        try:
            os.chdir(tmp_path)
            return main([
                "check", "draft.md",
                "--context", "context.json",
                "--actor-identity", "actor.json",
                "--profile", "final-prose",
            ])
        finally:
            os.chdir(original_cwd)


def main(argv: Optional[List[str]] = None) -> int:
    # Reports may contain non-Latin-1 characters (maths symbols, Greek such as
    # the provenance tuple's tau, smart quotes). On Windows stdout defaults to
    # cp1252 and a bare write would crash with UnicodeEncodeError. Force UTF-8
    # so the CLI is robust to any document content on any platform.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        from warrantos.provenance.status import (
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

    if args.command == "init":
        return _cmd_init(args)

    if args.command == "demo":
        return _cmd_demo(args)

    if args.command == "slop":
        from warrantos.provenance.slop import run_slop
        return run_slop(
            args.paths,
            as_json=args.json,
            badge=args.badge,
            fail_over=args.fail_over,
            include_fences=args.include_fences,
        )

    if args.command == "tells":
        from warrantos.provenance.tells import run_tells
        return run_tells(
            args.paths,
            as_json=args.json,
            badge=args.badge,
            fail_over=args.fail_over,
            include_fences=args.include_fences,
        )

    if args.command == "attest":
        return _cmd_attest(args)

    if args.command == "verify-external":
        return _cmd_verify_external(args)

    if args.command == "calibrate":
        return _cmd_calibrate(args)

    if args.command == "metrics":
        return _cmd_metrics(args)

    if args.command == "retention":
        return _cmd_retention(args)

    if args.command != "check":
        parser.print_help()
        return 0

    if getattr(args, "explain_profile", False):
        sys.stdout.write(explain_profiles() + "\n")
        return 0

    # Accept a bare string for backwards compatibility with callers that
    # construct an argparse.Namespace by hand (tests, wrappers).
    drafts = [args.draft] if isinstance(args.draft, str) else (args.draft or [])

    if not drafts:
        sys.stderr.write(
            "warrantos check: at least one draft argument is required "
            "(it is optional only with --explain-profile)\n"
        )
        return 2

    if len(drafts) > 1 and args.run_id:
        sys.stderr.write(
            "warrantos check: --run-id cannot be combined with more than "
            "one draft; each draft gets its own generated run\n"
        )
        return 2

    worst = 0
    for _draft_path in drafts:
        worst = max(worst, _cmd_check_single(args, _draft_path))
    return worst


def _cmd_check_single(args, draft_path):
    """Run the check pipeline over one draft. Returns the process exit code."""
    run_id = args.run_id or "run_" + uuid.uuid4().hex[:12]

    # B5 path containment: run_id must match the safe-character pattern.
    if not RUN_ID_RE.match(run_id):
        sys.stderr.write(
            "warrantos: run_id %r is not allowed; "
            "use only [A-Za-z0-9_-] (1-64 characters)\n" % run_id
        )
        return 2

    # B5 path containment: confine out_dir and --db under cwd.
    _cwd = Path(".").resolve()
    raw_out_dir = args.out_dir or str(Path(".warrant") / "runs" / run_id)
    try:
        out_dir = resolve_under(_cwd, raw_out_dir)
    except ValueError as exc:
        sys.stderr.write(
            "warrantos: out_dir is outside the current working directory: %s\n" % exc
        )
        return 2

    try:
        _db_path_safe = str(resolve_under(_cwd, args.db))
    except ValueError as exc:
        sys.stderr.write(
            "warrantos: --db path is outside the current working directory: %s\n" % exc
        )
        return 2

    sys.stderr.write("warrantos: output directory resolved to: %s\n" % out_dir)

    # --- Inputs ---
    try:
        draft = load_draft(draft_path)
    except FileNotFoundError:
        sys.stderr.write("warrantos: draft file not found: %s\n" % draft_path)
        return 2

    # --- F-classification sensitivity gate (optional, fail-closed) ---
    if getattr(args, "sensitivity_check", False):
        from warrantos.provenance.classification import (
            SensitivityBlock,
            gate_sensitivity,
        )
        try:
            gate_sensitivity(draft)
        except SensitivityBlock as block:
            sys.stderr.write("warrantos: %s\n" % block)
            sys.stderr.write(
                "warrantos: --sensitivity-check refused to process this draft. "
                "The keyword heuristics are a starter set; review and extend "
                "for your environment if this is a false positive.\n"
            )
            return 3

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
        overrides_on_record = list_overrides_for_run(_db_path_safe, run_id)
    except Exception:
        overrides_on_record = []

    cbom = build_cbom(
        context_inputs=context_inputs,
        claims=claim_records,
        artefact_id=Path(draft_path).name,
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
    verdict, reasons, fired_rule = consolidate_verdict(
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
        "verdict_rule_fired": fired_rule,
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
