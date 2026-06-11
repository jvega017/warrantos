#!/usr/bin/env python3
"""Run the four-verdict gallery and assert each example produces its
documented verdict.

This is the thesis demo: one command exercises Layer 1
classification, Layer 4 admissibility, Layer 7 G1 boundary, Layer 7
G2 detection, CBOM assembly, and the four-state verdict
consolidator across four canonical drafts and asserts that each
ends at the verdict the documentation promises. G2 verification,
G3 self-grounding, and the STARTER G4/G5 gates are not exercised by
the bundled invocations; pass `--verify` and `--writer-model`/
`--verifier-model` to a manual `warrantos check` to exercise them.

Exit codes:
    0  every example produced its expected verdict
    1  one or more verdicts did not match
    2  invocation error (warrantos CLI not found, JSON parse failure)

Usage:
    python tools/run_gallery.py
    python tools/run_gallery.py --verbose

Designed for both interactive demo use and CI. No third-party deps.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Case:
    name: str
    directory: str
    expected_verdict: str
    use_actor_identity: bool
    rationale: str


GALLERY: List[Case] = [
    Case(
        name="01-pass",
        directory="examples/01-pass",
        expected_verdict="PASS",
        use_actor_identity=True,
        rationale="Every claim cited inline; no boundary violation; actor identity supplied.",
    ),
    Case(
        name="quickstart-demo (HOLD)",
        directory="examples/quickstart-demo",
        expected_verdict="HOLD",
        use_actor_identity=True,
        rationale="One magnitude claim has no source; salience above the HOLD threshold.",
    ),
    Case(
        name="03-block-prose-boundary",
        directory="examples/03-block-prose-boundary",
        expected_verdict="BLOCK",
        use_actor_identity=True,
        rationale='"Based on your feedback" trips Layer 7 G1 in the final-prose profile.',
    ),
    Case(
        name="04-not-assessable-missing-actor",
        directory="examples/04-not-assessable-missing-actor",
        expected_verdict="NOT_ASSESSABLE",
        use_actor_identity=False,
        rationale="Final-prose profile without --actor-identity cannot certify.",
    ),
]


def run_case(case: Case, verbose: bool = False) -> Optional[str]:
    """Run a single gallery example and return its verdict string,
    or None if the CLI failed to produce a parseable verdict."""
    case_dir = REPO_ROOT / case.directory
    cmd = [
        sys.executable,
        str(REPO_ROOT / "warrantos" / "cli" / "warrantos_cli.py"),
        "check",
        str(case_dir / "draft.md"),
        "--context",
        str(case_dir / "context.json"),
        "--profile",
        "final-prose",
        "--json",
    ]
    if case.use_actor_identity:
        cmd.extend(["--actor-identity", str(case_dir / "actor.json")])

    if verbose:
        print(f"\n[run] {' '.join(cmd)}", file=sys.stderr)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(
            f"[error] {case.name}: warrantos CLI did not emit valid JSON.\n"
            f"        stdout: {proc.stdout[:200]!r}\n"
            f"        stderr: {proc.stderr[:200]!r}",
            file=sys.stderr,
        )
        return None
    return payload.get("verdict")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo the warrantos invocation for each case.",
    )
    args = parser.parse_args(argv)

    bar = "=" * 78
    print(bar)
    print("WarrantOS four-verdict gallery demo")
    print(bar)
    print(
        "Demonstrates the four-state model: every example reaches the verdict "
        "its README promises."
    )
    print()

    failures = []
    rows = []
    for case in GALLERY:
        verdict = run_case(case, verbose=args.verbose)
        if verdict is None:
            failures.append((case.name, "INVOCATION_ERROR"))
            rows.append((case.name, case.expected_verdict, "ERROR", "FAIL"))
            continue
        ok = verdict == case.expected_verdict
        if not ok:
            failures.append((case.name, verdict))
        rows.append(
            (
                case.name,
                case.expected_verdict,
                verdict,
                "ok" if ok else "MISMATCH",
            )
        )

    name_w = max(len(r[0]) for r in rows)
    exp_w = max(len(r[1]) for r in rows)
    got_w = max(len(r[2]) for r in rows)
    header = (
        f"{'Case'.ljust(name_w)}  {'Expected'.ljust(exp_w)}  "
        f"{'Got'.ljust(got_w)}  Status"
    )
    print(header)
    print("-" * len(header))
    for name, expected, got, status in rows:
        print(
            f"{name.ljust(name_w)}  {expected.ljust(exp_w)}  "
            f"{got.ljust(got_w)}  {status}"
        )
    print()
    print(bar)
    if failures:
        print(f"FAIL: {len(failures)} of {len(GALLERY)} cases mismatched.")
        for name, got in failures:
            print(f"  - {name}: produced {got}")
        print(bar)
        return 1
    print(f"OK: all {len(GALLERY)} cases produced the expected verdict.")
    print("The four-state model is exercised end-to-end on real drafts.")
    print(bar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
