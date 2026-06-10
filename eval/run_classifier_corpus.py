#!/usr/bin/env python3
"""SPEC-L1-S006 classifier corpus runner.

Reads a JSONL labelled corpus (one example per line, fields: id, text,
expected_context_type) and runs Layer 1 classification over each
example. Reports per-class precision, the list of mismatches, and an
exit code (0 on full match, 1 on any mismatch).

Default corpus path is `eval/classifier-corpus/seeds.jsonl`.

Usage:

    python eval/run_classifier_corpus.py [--corpus PATH] [--json]

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Repo root on sys.path so `import provenance.X` works when this file
# is launched directly from the repo root or via CI.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from warrantos.provenance.context_admissibility import classify_context  # noqa: E402


_DEFAULT_CORPUS = _REPO_ROOT / "eval" / "classifier-corpus" / "seeds.jsonl"


def load_corpus(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL corpus and return its rows."""
    if not path.is_file():
        raise FileNotFoundError("corpus not found: %s" % path)
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def run(corpus_path: Path) -> Dict[str, Any]:
    """Run the classifier over every corpus row and return a report."""
    rows = load_corpus(corpus_path)

    matches: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    per_class_total: Dict[str, int] = {}
    per_class_correct: Dict[str, int] = {}

    for row in rows:
        expected = row.get("expected_context_type")
        item = classify_context(
            row.get("id") or "ctx_unknown",
            row.get("text") or "",
        )
        actual = item.context_type
        per_class_total[expected] = per_class_total.get(expected, 0) + 1
        if actual == expected:
            per_class_correct[expected] = per_class_correct.get(expected, 0) + 1
            matches.append({"id": row.get("id"), "expected": expected})
        else:
            mismatches.append({
                "id": row.get("id"),
                "expected": expected,
                "actual": actual,
            })

    per_class_precision: Dict[str, float] = {}
    for cls, total in per_class_total.items():
        correct = per_class_correct.get(cls, 0)
        per_class_precision[cls] = correct / total if total else 0.0

    total = len(rows)
    correct = len(matches)
    overall = correct / total if total else 0.0

    return {
        "schema": "warrantos-classifier-corpus-report/v1",
        "corpus_path": str(corpus_path),
        "total": total,
        "correct": correct,
        "mismatches": mismatches,
        "overall_precision": overall,
        "per_class_total": per_class_total,
        "per_class_precision": per_class_precision,
        "note": (
            "SPEC-L1-S006: this corpus is at SHOULD level when at least "
            "one example per class is present. v0.3 promotion to SHALL "
            "requires N >= 50 per class."
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_classifier_corpus",
        description="SPEC-L1-S006 classifier corpus runner.",
    )
    parser.add_argument(
        "--corpus", default=str(_DEFAULT_CORPUS),
        help="Path to the JSONL corpus.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the report as JSON.",
    )
    args = parser.parse_args(argv)

    try:
        report = run(Path(args.corpus))
    except FileNotFoundError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write("error: corpus is not valid JSONL: %s\n" % exc)
        return 2

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "classifier corpus report\n"
            "  corpus:        %s\n"
            "  total:         %d\n"
            "  correct:       %d\n"
            "  overall:       %.3f\n"
            % (report["corpus_path"], report["total"],
               report["correct"], report["overall_precision"])
        )
        if report["per_class_precision"]:
            sys.stdout.write("  per class precision:\n")
            for cls in sorted(report["per_class_precision"]):
                sys.stdout.write(
                    "    %-22s %.3f (%d total)\n"
                    % (cls, report["per_class_precision"][cls],
                       report["per_class_total"].get(cls, 0))
                )
        if report["mismatches"]:
            sys.stdout.write("  mismatches:\n")
            for m in report["mismatches"]:
                sys.stdout.write(
                    "    %s: expected %s, got %s\n"
                    % (m["id"], m["expected"], m["actual"])
                )
        sys.stdout.write("\n%s\n" % report["note"])

    return 0 if not report["mismatches"] else 1


if __name__ == "__main__":
    sys.exit(main())
