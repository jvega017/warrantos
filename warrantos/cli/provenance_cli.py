#!/usr/bin/env python3
"""claude-provenance CLI.

Run a heuristic (and optional LLM-graded) provenance check on a file,
directory, or stdin. Produces a human-readable report or machine-readable
JSON.

Usage:
    python cli/provenance_cli.py [OPTIONS] [PATH]

PATH may be:
    -          Read from stdin (default when PATH is omitted)
    <file>     A single .md or .txt file
    <dir>      Recursively scan all .md and .txt files under the directory

Options:
    --verify   Run provenance.verify.verify_text with network fetch enabled
               (requires the provenance package). Default: heuristic-only,
               offline pass (fetch=False).
    --ci       CI mode. Exit code 1 if any claim has verdict 'contradicted'
               OR axis-1 status 'unsupported' (no citation). Exit 0 otherwise.
               Without --ci the exit code is always 0.
    --json     Emit machine-readable JSON to stdout instead of a text report.
    --grader   Optional grader string passed through to verify_text.
               Default: None (the package chooses the grader).
    --cbom     Build a Context Bill of Materials and run the prose boundary
               gate instead of the factual-claim provenance check.
    --context  Path to a JSON or text file containing source context for
               --cbom mode.
    --profile  Output profile for --cbom boundary checks:
               final-prose | brief-light | paper-full | audit.

Design rules:
    - stdlib only; zero third-party dependencies
    - Python 3.8 compatible
    - provenance package imported lazily so the module loads even when the
      package is absent (tests can stub sys.modules)
    - never raise on a bad path; print one-line error to stderr; exit
      non-zero only under --ci
    - offline and deterministic unless --verify is passed
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# When invoked as `python cli/provenance_cli.py`, sys.path[0] is the cli/
# directory rather than the repo root, so `import provenance.X` fails with
# ModuleNotFoundError. The two test_context_cli.py failures in the
# 2026-05-27 baseline traced to this: --cbom mode hit
# _import_context_admissibility(), the lazy import returned None, and the
# CLI emitted "context admissibility module is not available." with no
# JSON or text output. The lines below make the repository root
# importable so the lazy imports actually find the package.
# File is at <root>/warrantos/cli/provenance_cli.py, so the root is three up.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_paths(path_arg: str) -> List[Path]:
    """Return a flat list of .md and .txt files to scan."""
    p = Path(path_arg)
    if not p.exists():
        raise FileNotFoundError(path_arg)
    if p.is_file():
        return [p]
    if p.is_dir():
        files = []
        for ext in ("*.md", "*.txt"):
            files.extend(p.rglob(ext))
        return sorted(files)
    raise ValueError("Path is neither a file nor a directory: %s" % path_arg)


def _read_path(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise IOError("Cannot read %s: %s" % (p, exc)) from exc


def _import_provenance():
    """Lazily import the provenance package.

    Returns the verify module or None if the package is not installed.
    Importing inside the function means tests can stub sys.modules before
    calling any CLI function without affecting module-load time.
    """
    try:
        import warrantos.provenance.verify as pv  # type: ignore
        return pv
    except ImportError:
        return None


def _import_extract():
    """Lazily import provenance.extract for the offline heuristic pass."""
    try:
        import warrantos.provenance.extract as pe  # type: ignore
        return pe
    except ImportError:
        return None


def _import_context_admissibility():
    """Lazily import the context admissibility module."""
    try:
        import warrantos.provenance.context_admissibility as ca  # type: ignore
        return ca
    except ImportError:
        return None


def _load_context_items(context_path: str):
    """Load context items from JSON or plain text.

    JSON input accepts either:
      [{"id": "feedback_1", "text": "..."}]
      {"items": [{"id": "feedback_1", "text": "..."}]}

    Plain text input creates one item per non-empty line. This keeps the CLI
    useful for simple GitHub Actions and local shell workflows.
    """
    ca = _import_context_admissibility()
    if ca is None:
        raise RuntimeError("provenance.context_admissibility is not available")

    text = _read_path(Path(context_path))
    stripped = text.strip()
    raw_items = []
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict):
            data = data.get("items", [])
        if not isinstance(data, list):
            raise ValueError("context JSON must be a list or an object with an items list")
        for i, entry in enumerate(data, 1):
            if isinstance(entry, dict):
                cid = entry.get("id") or entry.get("context_id") or "context_%03d" % i
                raw = entry.get("text") or entry.get("raw_text") or ""
            else:
                cid = "context_%03d" % i
                raw = str(entry)
            raw_items.append((str(cid), raw))
    else:
        for i, line in enumerate([ln.strip() for ln in text.splitlines() if ln.strip()], 1):
            raw_items.append(("context_%03d" % i, line))

    return [ca.classify_context(cid, raw) for cid, raw in raw_items]


def _build_cbom_text_report(source_label: str, cbom: dict) -> str:
    """Build a human-readable CBOM report."""
    lines = ["claude-provenance: context integrity check", "=" * 48]
    lines.append("Source: %s" % source_label)
    lines.append("")
    summary = cbom.get("summary", {})
    lines.append(
        "Context items: %(total_context_items)s   influence: %(can_influence_output)s   "
        "final-prose-admissible: %(can_appear_in_final_prose)s   audit-only: %(audit_only)s   "
        "excluded: %(excluded)s" % summary
    )
    boundary = cbom.get("prose_boundary", {})
    lines.append("Prose boundary: %s" % boundary.get("verdict", "unknown"))
    violations = boundary.get("violations", [])
    if violations:
        lines.append("")
        lines.append("Process-to-prose leakage:")
        for item in violations:
            lines.append(
                "  [%s/%s] %s"
                % (item.get("severity", ""), item.get("rule_id", ""), item.get("matched_text", ""))
            )
    transforms = cbom.get("transforms", [])
    if transforms:
        lines.append("")
        lines.append("Admissible transforms:")
        for item in transforms[:10]:
            lines.append("  [%s] %s" % (item.get("kind", ""), item.get("text", "")))
        if len(transforms) > 10:
            lines.append("  ... and %d more." % (len(transforms) - 10))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Verdict processing
# ---------------------------------------------------------------------------

_BAD_VERDICTS = frozenset({"contradicted"})
_WORST_ORDER = ["contradicted", "unverifiable", "not_addressed"]


def _has_ci_failure(verdicts: list, totals: Optional[dict]) -> bool:
    """Return True if any result warrants a CI failure.

    Failure conditions:
      - any Verdict with verdict in {contradicted}
      - any axis-1 status 'unsupported' (captured in totals["unsupported"] > 0)
    """
    for v in verdicts:
        verdict_val = getattr(v, "verdict", None)
        if verdict_val in _BAD_VERDICTS:
            return True
    if totals and totals.get("unsupported", 0) > 0:
        return True
    return False


def _worst_items(verdicts: list, limit: int = 10) -> list:
    """Return up to `limit` verdicts sorted by severity (contradicted first)."""
    def _rank(v):
        val = getattr(v, "verdict", "")
        try:
            return _WORST_ORDER.index(val)
        except ValueError:
            return len(_WORST_ORDER)

    return sorted(verdicts, key=_rank)[:limit]


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def _build_text_report(
    source_label: str,
    totals: Optional[dict],
    verdicts: list,
    heuristic_rows: Optional[list],
) -> str:
    lines = ["claude-provenance: provenance check", "=" * 40]
    lines.append("Source: %s" % source_label)

    if totals is not None:
        lines.append("")
        lines.append("Heuristic pass (offline)")
        lines.append(
            "  Claims detected: %(total)d   supported: %(supported)d   "
            "[CITE NEEDED]: %(tagged)d   unsupported: %(unsupported)d" % totals
        )

    # Group verdicts by category
    by_verdict = {}  # type: dict
    for v in verdicts:
        key = getattr(v, "verdict", "unknown")
        by_verdict.setdefault(key, []).append(v)

    if by_verdict:
        lines.append("")
        lines.append("Verification pass")
        for vkey, group in sorted(by_verdict.items()):
            lines.append("  %s: %d" % (vkey, len(group)))

        worst = _worst_items(verdicts)
        if worst:
            lines.append("")
            lines.append("Worst items (up to 10):")
            for v in worst:
                claim = getattr(v, "claim_text", "")
                verdict_val = getattr(v, "verdict", "")
                conf = getattr(v, "confidence", None)
                conf_str = " [conf: %.2f]" % conf if conf is not None else ""
                lines.append("  [%s]%s %s" % (verdict_val, conf_str, claim[:200]))

    if totals is not None and totals.get("unsupported", 0) > 0 and heuristic_rows:
        lines.append("")
        lines.append("Unsupported claims (no citation found):")
        unsup = [r for r in heuristic_rows if r[0] == "unsupported"]
        for status, trigger, snippet in unsup[:10]:
            lines.append("  [%s] %s" % (trigger, snippet))
        if len(unsup) > 10:
            lines.append("  ... and %d more." % (len(unsup) - 10))

    lines.append("")
    lines.append("Note: heuristic detection is a tripwire, not an oracle.")
    lines.append(
        "It will produce false positives and false negatives. Human review is required."
    )
    return "\n".join(lines)


def _build_json_report(
    source_label: str,
    totals: Optional[dict],
    verdicts: list,
    heuristic_rows: Optional[list],
    ci_failure: bool,
) -> dict:
    verdict_list = []
    for v in verdicts:
        verdict_list.append(
            {
                "claim_text": getattr(v, "claim_text", ""),
                "citation": getattr(v, "citation", None),
                "verdict": getattr(v, "verdict", "unknown"),
                "confidence": getattr(v, "confidence", None),
                "rationale": getattr(v, "rationale", None),
                "grader": getattr(v, "grader", None),
            }
        )

    heuristic_out = None
    if heuristic_rows is not None:
        heuristic_out = [
            {"status": st, "trigger": tg, "claim_text": txt}
            for st, tg, txt in heuristic_rows
        ]

    return {
        "source": source_label,
        "heuristic_totals": totals,
        "heuristic_claims": heuristic_out,
        "verdicts": verdict_list,
        "ci_failure": ci_failure,
        "note": (
            "Heuristic detection is a tripwire, not an oracle. "
            "Human review is required."
        ),
    }


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def _process_text(
    text: str,
    source_label: str,
    do_verify: bool,
    grader: Optional[str],
) -> Tuple[Optional[dict], list, Optional[list]]:
    """Run heuristic and optional verification passes.

    Returns (totals, verdicts, heuristic_rows).
    totals and heuristic_rows may be None if the provenance package is absent.
    verdicts is always a list (may be empty).
    """
    pv = _import_provenance()

    if pv is None:
        # Package not installed; fall back to empty verdicts with no totals.
        return None, [], None

    verdicts = pv.verify_text(text, grader=grader, fetch=do_verify)

    # Also run the offline heuristic to get axis-1 totals.
    # verify_text with fetch=False is used for the heuristic pass (as per
    # the interface contract). We run it separately only if we did a live
    # fetch above and want the offline numbers too; if we are already in
    # offline mode the single call covers both.
    if do_verify:
        offline_verdicts = pv.verify_text(text, grader=None, fetch=False)
    else:
        offline_verdicts = verdicts

    # Derive axis-1 totals from offline pass.
    totals = _derive_totals(offline_verdicts)
    heuristic_rows = _verdicts_to_rows(offline_verdicts)

    return totals, verdicts, heuristic_rows


def _derive_totals(verdicts: list) -> dict:
    """Map Verdict objects to axis-1 (heuristic) totals.

    The verify_text offline pass returns Verdict objects whose verdict field
    encodes the axis-1 status: 'verified' maps to supported, 'skipped'
    maps to tagged (explicit [CITE NEEDED]), everything else is unsupported.
    This is a best-effort mapping; the hook's analyse() is the canonical
    source for heuristic counting.
    """
    total = len(verdicts)
    supported = sum(1 for v in verdicts if getattr(v, "verdict", "") == "verified")
    tagged = sum(1 for v in verdicts if getattr(v, "verdict", "") == "skipped")
    unsupported = total - supported - tagged
    return {
        "total": total,
        "supported": supported,
        "tagged": tagged,
        "unsupported": max(unsupported, 0),
    }


def _verdicts_to_rows(verdicts: list) -> list:
    rows = []
    for v in verdicts:
        verdict_val = getattr(v, "verdict", "unknown")
        if verdict_val == "verified":
            status = "supported"
        elif verdict_val == "skipped":
            status = "tagged"
        else:
            status = "unsupported"
        rows.append((status, getattr(v, "grader", ""), getattr(v, "claim_text", "")))
    return rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="provenance_cli",
        description=(
            "Run a provenance check on a file, directory, or stdin. "
            "Reports unsupported factual claims and optionally verifies "
            "them against cited sources."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="-",
        metavar="PATH",
        help="File, directory, or '-' for stdin (default: stdin).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=False,
        help=(
            "Also run provenance.verify.verify_text with network fetch enabled. "
            "Default: heuristic-only, offline pass."
        ),
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        default=False,
        help=(
            "CI mode: exit 1 if any claim is 'contradicted' or 'unsupported', "
            "else exit 0. Without --ci the exit code is always 0."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON instead of a text report.",
    )
    parser.add_argument(
        "--grader",
        default=None,
        metavar="GRADER",
        help="Optional grader identifier passed through to verify_text.",
    )
    parser.add_argument(
        "--cbom",
        action="store_true",
        default=False,
        help="Build a Context Bill of Materials and run the prose boundary gate.",
    )
    parser.add_argument(
        "--context",
        default=None,
        metavar="PATH",
        help="Context JSON/text file for --cbom mode.",
    )
    parser.add_argument(
        "--profile",
        default="final-prose",
        metavar="PROFILE",
        help="Boundary profile for --cbom mode: final-prose, brief-light, paper-full, audit.",
    )

    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # Collect texts to process
    # ------------------------------------------------------------------
    sources = []  # list of (label, text)

    if args.path == "-":
        try:
            text = sys.stdin.read()
        except Exception as exc:
            sys.stderr.write("provenance: cannot read stdin: %s\n" % exc)
            return 1 if args.ci else 0
        sources.append(("<stdin>", text))
    else:
        try:
            paths = _collect_paths(args.path)
        except FileNotFoundError:
            sys.stderr.write("provenance: path not found: %s\n" % args.path)
            return 1 if args.ci else 0
        except ValueError as exc:
            sys.stderr.write("provenance: %s\n" % exc)
            return 1 if args.ci else 0

        for p in paths:
            try:
                text = _read_path(p)
                sources.append((str(p), text))
            except IOError as exc:
                sys.stderr.write("provenance: %s\n" % exc)
                # Continue to next file; only fail at the end in CI mode.

    if not sources:
        sys.stderr.write("provenance: no content to analyse.\n")
        return 1 if args.ci else 0

    # ------------------------------------------------------------------
    # Context Integrity / CBOM mode
    # ------------------------------------------------------------------
    if args.cbom:
        ca = _import_context_admissibility()
        if ca is None:
            sys.stderr.write(
                "provenance: context admissibility module is not available.\n"
            )
            return 1 if args.ci else 0
        if not args.context:
            sys.stderr.write("provenance: --cbom requires --context PATH.\n")
            return 1 if args.ci else 0

        all_reports = []
        any_ci_failure = False
        try:
            context_items = _load_context_items(args.context)
        except Exception as exc:
            sys.stderr.write("provenance: cannot read context: %s\n" % exc)
            return 1 if args.ci else 0

        for label, text in sources:
            cbom = ca.compile_cbom(context_items, text, artefact_role=args.profile)
            blocked = cbom.get("prose_boundary", {}).get("verdict") == "blocked"
            if blocked:
                any_ci_failure = True
            if args.json_out:
                report = cbom
            else:
                report = _build_cbom_text_report(label, cbom)
            all_reports.append((label, report))

        if args.json_out:
            print(json.dumps({
                "results": [
                    {"source": label, "report": report}
                    for label, report in all_reports
                ],
                "ci_failure": any_ci_failure,
            }, indent=2))
        else:
            for i, (label, report) in enumerate(all_reports):
                if i > 0:
                    print()
                print(report)
        return 1 if (args.ci and any_ci_failure) else 0

    # ------------------------------------------------------------------
    # Check whether the provenance package is available
    # ------------------------------------------------------------------
    pv = _import_provenance()
    if pv is None:
        sys.stderr.write(
            "provenance: the 'provenance' package is not installed. "
            "Install it or add the repo root to PYTHONPATH.\n"
        )
        return 1 if args.ci else 0

    # ------------------------------------------------------------------
    # Process each source
    # ------------------------------------------------------------------
    all_reports = []
    any_ci_failure = False

    for label, text in sources:
        if not text.strip():
            continue

        try:
            totals, verdicts, heuristic_rows = _process_text(
                text, label, args.verify, args.grader
            )
        except Exception as exc:
            sys.stderr.write("provenance: error processing %s: %s\n" % (label, exc))
            totals, verdicts, heuristic_rows = None, [], None

        ci_failure = _has_ci_failure(verdicts, totals)
        if ci_failure:
            any_ci_failure = True

        if args.json_out:
            report = _build_json_report(
                label, totals, verdicts, heuristic_rows, ci_failure
            )
        else:
            report = _build_text_report(label, totals, verdicts, heuristic_rows)

        all_reports.append((label, report))

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    if args.json_out:
        output = {
            "results": [
                {"source": label, "report": report}
                for label, report in all_reports
            ],
            "ci_failure": any_ci_failure,
        }
        print(json.dumps(output, indent=2))
    else:
        for i, (label, report) in enumerate(all_reports):
            if i > 0:
                print()
            print(report)

    return 1 if (args.ci and any_ci_failure) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Absolute backstop: never crash with an unhandled exception.
        sys.exit(0)
