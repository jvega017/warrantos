#!/usr/bin/env python3
"""warrantos slop: zero-configuration AI scaffold-residue scanner.

Recursively scans documentation trees (.md, .rst, .txt) for near-unambiguous
AI-assistant residue that bled from a chat session into a shipped artefact.
The pattern list is the canonical ``_AI_RESIDUE_RULES`` set from
``context_admissibility`` (the SPEC-L7-G1 prose-boundary rules). This module
adds no patterns of its own; it only maps each rule id to a reader-facing
category, so a ``warrantos slop`` finding and a ``warrantos check`` G1
violation are always explained by the same rule.

Categories
----------

==================  ========================================================
category            rule ids (from _AI_RESIDUE_RULES)
==================  ========================================================
chat bleed          assistant_opener, apology, hedge_provenance
identity leak       ai_self_reference, ai_capability_disclaimer
sign-off residue    assistant_closer, future_promise
scaffold            delivery_framing, request_acknowledgement
placeholder         scaffold_placeholder
==================  ========================================================

SLOP SCORE
----------

The score is a density measure on a 0.0 to 10.0 scale::

    d     = findings / files_scanned        (0.0 when no files scanned)
    score = round(10 * d / (d + 1), 1)

Properties: 0 findings = 0.0; strictly monotonic in the finding count for a
fixed number of scanned files; one finding per scanned file scores 5.0; the
score approaches (never reaches) 10.0 as density grows.

Exit codes
----------

0 by default regardless of findings. With ``--fail-over THRESHOLD`` the
command exits 1 when the reported (rounded) score is strictly greater than
THRESHOLD. A path argument that does not exist exits 2.

Stdlib only. Regexes are compiled once at import time (in
context_admissibility), so a whole-repository scan stays fast.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import quote

# The canonical AI-residue pattern list. slop deliberately imports the
# module-level list rather than copying it: SPEC-L7-G1 and `warrantos slop`
# must never drift apart, and context_admissibility stays the single source
# of truth for what counts as AI residue.
from warrantos.provenance.context_admissibility import _AI_RESIDUE_RULES

CATEGORY_CHAT_BLEED = "chat bleed"
CATEGORY_IDENTITY_LEAK = "identity leak"
CATEGORY_SIGN_OFF = "sign-off residue"
CATEGORY_SCAFFOLD = "scaffold"
CATEGORY_PLACEHOLDER = "placeholder"

CATEGORY_BY_RULE: Dict[str, str] = {
    "assistant_opener": CATEGORY_CHAT_BLEED,
    "apology": CATEGORY_CHAT_BLEED,
    "hedge_provenance": CATEGORY_CHAT_BLEED,
    "ai_self_reference": CATEGORY_IDENTITY_LEAK,
    "ai_capability_disclaimer": CATEGORY_IDENTITY_LEAK,
    "assistant_closer": CATEGORY_SIGN_OFF,
    "future_promise": CATEGORY_SIGN_OFF,
    "delivery_framing": CATEGORY_SCAFFOLD,
    "request_acknowledgement": CATEGORY_SCAFFOLD,
    "scaffold_placeholder": CATEGORY_PLACEHOLDER,
}

# A rule added upstream without a category mapping still surfaces rather
# than being silently dropped; scaffold is the least specific label.
_DEFAULT_CATEGORY = CATEGORY_SCAFFOLD

# (rule_id, compiled_pattern) pairs; severity is not used by slop.
SLOP_RULES: Tuple[Tuple[str, object], ...] = tuple(
    (rule_id, pattern) for rule_id, pattern, _severity in _AI_RESIDUE_RULES
)

SKIP_DIRS = frozenset(
    {".git", "node_modules", "dist", "build", ".venv", "__pycache__"}
)
TEXT_SUFFIXES = frozenset({".md", ".rst", ".txt"})
MATCH_TRUNCATE = 60

_SHIELDS_BASE = "https://img.shields.io/badge/"

# CommonMark fence delimiter: up to three leading spaces then ``` or ~~~.
# Fenced blocks quote command output and code, where residue strings are
# usually deliberate examples rather than leaked scaffold, so they are
# skipped by default (opt back in with --include-fences).
_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")


@dataclass
class SlopFinding:
    """One matched residue pattern in one scanned file."""

    path: str
    line: int
    match: str
    category: str
    rule_id: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "match": self.match,
            "category": self.category,
            "rule_id": self.rule_id,
        }


def _truncate(text: str, limit: int = MATCH_TRUNCATE) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def scan_text(
    text: str, display_path: str, *, include_fences: bool = False
) -> List[SlopFinding]:
    """Scan one document's text; return findings with 1-based line numbers.

    Lines inside fenced code blocks (``` or ~~~) are skipped unless
    include_fences is true; an unclosed fence skips to end of document.
    """
    findings: List[SlopFinding] = []
    in_fence = False
    fence_marker = ""
    for line_number, line in enumerate(text.splitlines(), 1):
        if not include_fences:
            fence = _FENCE_RE.match(line)
            if fence:
                if not in_fence:
                    in_fence, fence_marker = True, fence.group(1)
                elif fence.group(1) == fence_marker:
                    in_fence = False
                continue
            if in_fence:
                continue
        for rule_id, pattern in SLOP_RULES:
            for match in pattern.finditer(line):
                findings.append(
                    SlopFinding(
                        path=display_path,
                        line=line_number,
                        match=_truncate(match.group(0)),
                        category=CATEGORY_BY_RULE.get(rule_id, _DEFAULT_CATEGORY),
                        rule_id=rule_id,
                    )
                )
    return findings


def iter_candidate_files(root: Path) -> Iterator[Path]:
    """Yield scannable files under root, pruning the skip directories.

    Sorted traversal keeps output deterministic across platforms.
    """
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if Path(name).suffix.lower() in TEXT_SUFFIXES:
                yield Path(dirpath) / name


def _display_path(file_path: Path, root: Path) -> str:
    """Repo-relative display path: relative to cwd when possible, else to
    the scanned root, else absolute. Posix separators for stable output."""
    resolved = file_path.resolve()
    for base in (Path.cwd(), root):
        try:
            return resolved.relative_to(base.resolve()).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def scan_paths(
    paths: Sequence[str], *, include_fences: bool = False
) -> Tuple[List[SlopFinding], int]:
    """Scan the given files and directories.

    Directories are walked recursively for .md, .rst and .txt files with
    the skip list applied. A path naming a file directly is scanned
    whatever its extension (an explicit request wins over the filter).
    Returns (findings, files_scanned). Raises FileNotFoundError for a
    path argument that does not exist.
    """
    findings: List[SlopFinding] = []
    files_scanned = 0
    seen: set = set()
    for raw in paths:
        root = Path(raw)
        if root.is_dir():
            candidates = iter_candidate_files(root)
        elif root.is_file():
            candidates = iter((root,))
        else:
            raise FileNotFoundError(raw)
        for file_path in candidates:
            resolved = file_path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files_scanned += 1
            findings.extend(
                scan_text(
                    text,
                    _display_path(file_path, root),
                    include_fences=include_fences,
                )
            )
    return findings, files_scanned


def slop_score(findings_count: int, files_scanned: int) -> float:
    """Density-based score on 0.0 to 10.0 (formula in the module docstring)."""
    if findings_count <= 0 or files_scanned <= 0:
        return 0.0
    density = findings_count / files_scanned
    return round(10.0 * density / (density + 1.0), 1)


def badge_url(score: float, findings_count: int) -> str:
    """shields.io badge URL: green 'slop free' at 0 findings, red score line
    otherwise. Label and message segments are URL-encoded."""
    if findings_count == 0:
        label, message, colour = "slop", "free", "brightgreen"
    else:
        label, message, colour = "slop", "%.1f/10" % score, "red"
    return _SHIELDS_BASE + "%s-%s-%s" % (
        quote(label, safe=""),
        quote(message, safe=""),
        colour,
    )


def build_report(
    findings: List[SlopFinding], files_scanned: int
) -> Dict[str, object]:
    score = slop_score(len(findings), files_scanned)
    return {
        "schema": "warrantos-slop/v1",
        "score": score,
        "files_scanned": files_scanned,
        "findings_count": len(findings),
        "findings": [f.to_dict() for f in findings],
        "badge_url": badge_url(score, len(findings)),
    }


def format_table(findings: List[SlopFinding], files_scanned: int) -> str:
    score = slop_score(len(findings), files_scanned)
    lines = [
        "SLOP SCORE: %.1f/10  (%d finding(s) across %d file(s) scanned)"
        % (score, len(findings), files_scanned)
    ]
    if not findings:
        lines.append("No AI scaffold residue detected.")
        return "\n".join(lines)
    lines.append("")
    path_w = max(len("path"), max(len(f.path) for f in findings))
    cat_w = max(len("category"), max(len(f.category) for f in findings))
    header = "%-*s  %5s  %-*s  %s" % (path_w, "path", "line", cat_w, "category", "match")
    lines.append(header)
    lines.append("-" * len(header))
    for f in findings:
        lines.append(
            "%-*s  %5d  %-*s  %s" % (path_w, f.path, f.line, cat_w, f.category, f.match)
        )
    return "\n".join(lines)


def run_slop(
    paths: Optional[Sequence[str]] = None,
    *,
    as_json: bool = False,
    badge: bool = False,
    fail_over: Optional[float] = None,
    include_fences: bool = False,
) -> int:
    """Entry point for the ``warrantos slop`` subcommand.

    Output precedence: --badge prints only the badge URL (pipeable), then
    --json, then the human table. Exit code is 0 unless fail_over is set
    and the rounded score exceeds it (1), or a path does not exist (2).
    """
    scan_targets = list(paths) if paths else ["."]
    try:
        findings, files_scanned = scan_paths(
            scan_targets, include_fences=include_fences
        )
    except FileNotFoundError as exc:
        sys.stderr.write("warrantos slop: path not found: %s\n" % exc)
        return 2

    score = slop_score(len(findings), files_scanned)

    if badge:
        sys.stdout.write(badge_url(score, len(findings)) + "\n")
    elif as_json:
        sys.stdout.write(
            json.dumps(build_report(findings, files_scanned), indent=2, sort_keys=True)
            + "\n"
        )
    else:
        sys.stdout.write(format_table(findings, files_scanned) + "\n")

    if fail_over is not None and score > fail_over:
        return 1
    return 0
