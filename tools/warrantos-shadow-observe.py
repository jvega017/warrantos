#!/usr/bin/env python3
"""warrantos-shadow-observe: read-only observer for live brief artefacts.

Path X4-B. Runs the warrantos pipeline over an already-published
brief in observation mode only. Never blocks anything. Never modifies
any production script. Appends a single line per run to a shadow log
so a two-week observation window can be used to calibrate the
boundary profile before any decision to wire the harness into the
publish path.

Defaults are conservative:

- Input: the most recent file in --brief-dir (default the user's
  publish-built directory). If no file is found, the observer exits 0
  with a "no brief found" line in the log.
- Profile: brief-light (the closest match to a daily brief artefact).
- Verifier: OFF by default. Offline detection only. --verify enables
  the Layer 7 G2 verifier.
- Output: a single line appended to --log (default
  08_Outputs/publish-gate-shadow.log).

The shadow log is the only side effect. The morning brief script
remains the source of truth for what is published. This observer
runs after the brief has been written, on the artefact that has
already shipped.

Usage:

    python tools/warrantos-shadow-observe.py
        [--brief-dir DIR]
        [--log PATH]
        [--profile final-prose|brief-light|paper-full|audit]
        [--verify]

To schedule (NOT done automatically by this script; Juan registers
when ready):

    schtasks /Create /TN 'Warrantos-Shadow-Observe' /SC DAILY /ST 07:00 \\
      /TR "python C:\\Users\\jvega\\Claude-Workspace\\03_Projects\\Claude-Provenance\\tools\\warrantos-shadow-observe.py" \\
      /RL LIMITED

Stdlib only. Python 3.8 compatible.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Optional

# Make the claude-provenance repo root importable when this script
# runs from any working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def find_latest_brief(brief_dir: Path) -> Optional[Path]:
    """Return the most recently modified .md or .html under brief_dir,
    or None if the directory does not exist or contains no candidates."""
    if not brief_dir.is_dir():
        return None
    candidates = []
    for ext in ("*.md", "*.html", "*.txt"):
        candidates.extend(brief_dir.rglob(ext))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def observe_one(
    brief_path: Path,
    profile: str,
    verify: bool,
    log_path: Path,
) -> int:
    """Run the harness once and append a one-line summary to the log."""
    from warrantos.provenance.mcp_server import tool_warrant_check

    try:
        result = tool_warrant_check(
            {
                "draft_path": str(brief_path),
                "profile": profile,
                "verify": verify,
                "no_fetch": True,
                "out_dir": str(_REPO_ROOT / ".warrant" / "shadow"),
                "db_path": str(_REPO_ROOT / ".warrant" / "shadow-overrides.db"),
            }
        )
    except Exception as exc:
        _append(
            log_path,
            {
                "ts": _now(),
                "brief": str(brief_path),
                "profile": profile,
                "shadow_status": "observer_error",
                "error": str(exc),
            },
        )
        return 0

    _append(
        log_path,
        {
            "ts": _now(),
            "brief": str(brief_path),
            "profile": profile,
            "shadow_status": "observed",
            "verdict": result.get("verdict"),
            "boundary_verdict": result.get("boundary_verdict"),
            "boundary_violations": result.get("boundary_violations"),
            "claims_detected": result.get("claims_detected"),
            "claims_supported": result.get("claims_supported"),
            "context_items": result.get("context_items"),
            "out_dir": result.get("out_dir"),
            "note": (
                "shadow mode: this verdict is NOT enforced; the brief was "
                "published as-is regardless of this row."
            ),
        },
    )
    return 0


def _append(log_path: Path, row: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, sort_keys=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_brief_dir() -> Path:
    """Best-guess default location of Juan's published brief artefacts.

    Falls back to a known harmless location if the workspace path is
    not present on this host.
    """
    candidates = [
        Path.home() / "Claude-Workspace" / "08_Outputs" / "publish-built",
        Path.home() / "Claude-Workspace" / "08_Outputs",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return Path.cwd()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="warrantos-shadow-observe",
        description=(
            "Read-only observer that runs the warrantos pipeline over the "
            "most recent published brief artefact and appends a single "
            "JSON-line summary to a shadow log. Never blocks anything."
        ),
    )
    parser.add_argument(
        "--brief-dir",
        default=None,
        help="Directory to scan for the most recent brief artefact.",
    )
    parser.add_argument(
        "--log",
        default=None,
        help="Path to the shadow log file.",
    )
    parser.add_argument(
        "--profile",
        default="prompt-template",
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
            "Layer 7 G1 boundary profile to apply during observation. "
            "Default prompt-template is appropriate when --brief-dir "
            "contains brief-prompt templates rather than rendered briefs."
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run the Layer 7 G2 verifier in offline mode.",
    )
    args = parser.parse_args(argv)

    brief_dir = Path(args.brief_dir) if args.brief_dir else _default_brief_dir()
    log_path = Path(args.log) if args.log else (
        Path.home() / "Claude-Workspace" / "08_Outputs" / "publish-gate-shadow.log"
    )

    latest = find_latest_brief(brief_dir)
    if latest is None:
        _append(
            log_path,
            {
                "ts": _now(),
                "brief_dir": str(brief_dir),
                "shadow_status": "no_brief_found",
            },
        )
        return 0

    return observe_one(latest, args.profile, args.verify, log_path)


if __name__ == "__main__":
    sys.exit(main())
