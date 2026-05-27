#!/usr/bin/env python3
"""Claude Code Stop hook that hands unverified claims back to the session.

When Claude is about to end a turn, this hook:

1. Reads the most recent run artefacts in `.warrant/runs/<run_id>/`.
2. Finds claims marked HOLD-eligible (unsupported load-bearing, or
   unverifiable load-bearing).
3. If any exist, prints a structured hand-back message asking Claude
   to verify them in the next turn using the model's own knowledge
   plus any fetched source text, and exits with code 2 to block the
   turn from ending until Claude has responded.

This is the **no-API-key verification path**: Claude itself performs
the verification using the same session that wrote the draft. No
ANTHROPIC_API_KEY, no LocalLLMGrader, no separate model. The session's
existing auth is the only credential needed.

The hook is loop-safe: if a previous turn's hand-back is still
unaddressed (no new verifier verdicts appeared since the last hook
fire), the hook silently passes through rather than re-blocking.

Designed to be wired in `~/.claude/settings.json` (or
`.claude/settings.json` per project) under hooks.Stop:

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "python /path/to/claude-provenance/hooks/claude_code_verify_hook.py",
        "blocking": true
      }
    ]
  }
}
```

Stdlib only. Python 3.8 compatible. No third-party dependencies.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


_DEFAULT_WARRANT_DIR = Path(".warrant") / "runs"
_HANDBACK_SENTINEL = Path(".warrant") / "last-handback.json"


def find_latest_run(warrant_dir: Path) -> Optional[Path]:
    """Return the most recently modified run directory, or None."""
    if not warrant_dir.is_dir():
        return None
    candidates = [p for p in warrant_dir.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def collect_holds(run_dir: Path) -> List[Dict[str, Any]]:
    """Read verdict.json and claims.json and return claims that
    triggered (or would trigger) a HOLD: unsupported load-bearing, or
    unverifiable load-bearing.
    """
    verdict_path = run_dir / "verdict.json"
    claims_path = run_dir / "claims.json"
    if not verdict_path.is_file() or not claims_path.is_file():
        return []

    try:
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        claims = json.loads(claims_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    # Only act when the run actually reached HOLD (or would have).
    if verdict.get("verdict") != "HOLD":
        return []

    holds: List[Dict[str, Any]] = []
    for c in claims if isinstance(claims, list) else []:
        if not isinstance(c, dict):
            continue
        if not c.get("load_bearing"):
            continue
        if c.get("citation"):
            continue  # supported by an inline citation; nothing to verify here
        holds.append({
            "sentence": c.get("sentence", ""),
            "salience": c.get("salience", 0.0),
            "triggers": c.get("triggers", []),
        })
    return holds


def already_handled(run_id: str, holds: List[Dict[str, Any]]) -> bool:
    """Loop-safety: skip re-blocking when the previous hand-back is
    pending. We compare the run_id and the hold-count fingerprint."""
    if not _HANDBACK_SENTINEL.is_file():
        return False
    try:
        sentinel = json.loads(_HANDBACK_SENTINEL.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return (
        sentinel.get("run_id") == run_id
        and sentinel.get("hold_count") == len(holds)
    )


def record_handback(run_id: str, holds: List[Dict[str, Any]]) -> None:
    _HANDBACK_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    _HANDBACK_SENTINEL.write_text(
        json.dumps({
            "run_id": run_id,
            "hold_count": len(holds),
            "sentences": [h["sentence"][:120] for h in holds],
        }, indent=2),
        encoding="utf-8",
    )


def build_handback_message(run_id: str, holds: List[Dict[str, Any]]) -> str:
    """Build the message Claude reads in the next turn."""
    lines = [
        "WARRANTOS: %d unverified load-bearing claim(s) in run %s." % (len(holds), run_id),
        "",
        "Please verify each claim below. For each one, either:",
        "  (a) Add a citation to the draft (URL or APA-style reference), OR",
        "  (b) Provide a short verification rationale based on your own knowledge,",
        "      explicitly flagging if you cannot verify it.",
        "",
        "Unverified load-bearing claims:",
    ]
    for i, h in enumerate(holds, 1):
        salience = h.get("salience", 0.0)
        lines.append("  %d. [salience=%.2f] %s" % (i, salience, h["sentence"]))
    lines.append("")
    lines.append(
        "After verifying, re-run `warrantos check` over the updated "
        "draft to confirm the HOLD has cleared."
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    """Entry point.

    Exit codes follow the Claude Code hook contract:

    - 0: pass through; the Stop event continues normally.
    - 2: block; the message printed to stderr is shown to Claude as
      hook feedback, which Claude reads and addresses in the next turn.
    """
    warrant_dir = Path(os.environ.get("WARRANTOS_RUN_DIR", str(_DEFAULT_WARRANT_DIR)))
    run_dir = find_latest_run(warrant_dir)
    if run_dir is None:
        # No warrantos runs yet: pass through silently.
        return 0

    run_id = run_dir.name
    holds = collect_holds(run_dir)
    if not holds:
        return 0

    if already_handled(run_id, holds):
        # The hand-back for this exact set of holds was already
        # delivered; do not block twice. Pass through and let the
        # user / next run resolve.
        return 0

    message = build_handback_message(run_id, holds)
    record_handback(run_id, holds)

    # The hook contract: stdout is informational, stderr (with exit
    # code 2) is shown to Claude as feedback for the next turn.
    sys.stderr.write(message + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
