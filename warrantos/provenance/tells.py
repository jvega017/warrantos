#!/usr/bin/env python3
"""warrantos tells: opinionated AI-writing-style scanner.

Sibling of ``warrantos slop``. Where slop hunts for chat RESIDUE (scaffold
that visibly leaked from an assistant session: "Certainly!", "As an AI
language model", stray TODO placeholders), tells hunts for prose that is
already clean of residue but still SOUNDS machine-written: contrastive
negation ("it's not X, it's Y"), hedge stacking, em-dash punctuation, AI
filler phrases, and a drumbeat of formulaic paragraph-openers.

tells is OPINIONATED where slop is (mostly) objective. Every rule here is a
house-style judgement call, not a claim that the flagged sentence was
written by a model. See ``docs/TELLS.md`` for the philosophy and limits.

This module reuses the slop scanning engine rather than copying it: file
discovery (``iter_candidate_files``), display-path resolution
(``_display_path``), the density score formula (``slop_score``), and the
shields.io badge base (``_SHIELDS_BASE``) are all imported from
``warrantos.provenance.slop``. Only the rule set and the sentence/line
scanning glue that applies it are new.

TELL SCORE
----------

Same density formula as SLOP SCORE, on the same 0.0 to 10.0 scale::

    d     = findings / files_scanned        (0.0 when no files scanned)
    score = round(10 * d / (d + 1), 1)

Exit codes
----------

0 by default regardless of findings. With ``--fail-over THRESHOLD`` the
command exits 1 when the reported (rounded) score is strictly greater than
THRESHOLD. A path argument that does not exist exits 2.

Stdlib only. Regexes are compiled once at import time.
"""

from __future__ import annotations

import bisect
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import quote

from warrantos.provenance.slop import (
    MATCH_TRUNCATE,
    _SHIELDS_BASE,
    _display_path,
    _FENCE_RE,
    _truncate,
    iter_candidate_files,
    slop_score as _density_score,
)

CATEGORY_CONTRASTIVE_NEGATION = "contrastive-negation"
CATEGORY_HEDGE_STACKING = "hedge-stacking"
CATEGORY_DASH_PUNCTUATION = "dash-punctuation"
CATEGORY_FILLER_LEXICON = "filler-lexicon"
CATEGORY_FORMULAIC_TRANSITION = "formulaic-transition"

_IGNORECASE = re.IGNORECASE

# --- 1. contrastive-negation -------------------------------------------
#
# The pivot ("but", the second "it is"/"this is", "more about") must land
# within ~60 characters of the trigger phrase so a long, unrelated sentence
# containing both halves by coincidence does not fire. Bare "rather than"
# and "instead of" are deliberately NOT rules here: too common in ordinary
# prose to be a useful signal on their own.
_CONTRASTIVE_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    (
        "contrastive_not_x_but",
        re.compile(r"\bnot\s+(?:just|only|merely|simply)\b.{0,60}?\bbut\b", _IGNORECASE),
    ),
    (
        "contrastive_it_is_not",
        re.compile(
            r"\bit\s+is\s+not\s+(?:about|a|an|the)\b.{0,60}?[,.;:]\s*it\s+is\b",
            _IGNORECASE,
        ),
    ),
    (
        "contrastive_its_not",
        re.compile(
            r"\bit['’]s\s+not\s+(?:about|a|an|the)\b.{0,60}?[,.;:]\s*it['’]s\b",
            _IGNORECASE,
        ),
    ),
    (
        "contrastive_isnt",
        re.compile(r"\bisn['’]t\b.{0,60}?[,.;:]\s*it['’]s\b", _IGNORECASE),
    ),
    (
        "contrastive_less_more",
        re.compile(r"\bless\s+about\b.{0,60}?\b(?:and\s+)?more\s+about\b", _IGNORECASE),
    ),
    (
        "contrastive_this_is_not",
        re.compile(r"\bthis\s+is\s+not\b.{0,60}?[,.;:]\s*this\s+is\b", _IGNORECASE),
    ),
)

# --- 3. dash-punctuation -------------------------------------------------
#
# An em dash used as punctuation anywhere in the line; a spaced en dash
# (surrounded by whitespace on both sides, so "2020-2021"-style number
# ranges without spaces are left alone).
_DASH_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("dash_em", re.compile("—")),
    ("dash_en_spaced", re.compile(r"(?<=\s)–(?=\s)")),
)

# --- 4. filler-lexicon ----------------------------------------------------
#
# Near-unambiguous AI filler phrases. Case-insensitive; apostrophe variants
# (straight and curly) both accepted.
_FILLER_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("filler_delve_into", re.compile(r"\bdelve\s+into\b", _IGNORECASE)),
    ("filler_rich_tapestry", re.compile(r"\brich\s+tapestry\b", _IGNORECASE)),
    (
        "filler_testament",
        re.compile(r"\bstands\s+as\s+a\s+testament\b", _IGNORECASE),
    ),
    (
        "filler_fast_paced_today",
        re.compile(r"\bin\s+today['’]s\s+fast-paced\b", _IGNORECASE),
    ),
    (
        "filler_evolving_today",
        re.compile(r"\bin\s+today['’]s\s+rapidly\s+evolving\b", _IGNORECASE),
    ),
    (
        "filler_important_note",
        re.compile(r"\bit\s+is\s+important\s+to\s+note\s+that\b", _IGNORECASE),
    ),
    (
        "filler_worth_noting",
        re.compile(r"\bit['’]s\s+worth\s+noting\s+that\b", _IGNORECASE),
    ),
    (
        "filler_ever_evolving",
        re.compile(r"\bin\s+the\s+ever-evolving\b", _IGNORECASE),
    ),
    ("filler_gamechanger", re.compile(r"\bgame-changer\b", _IGNORECASE)),
    (
        "filler_unlock_power",
        re.compile(r"\bunlock\s+the\s+(?:full\s+)?(?:power|potential)\b", _IGNORECASE),
    ),
    (
        "filler_seamlessly",
        re.compile(r"\bseamlessly\s+integrates\b", _IGNORECASE),
    ),
    (
        "filler_end_of_day",
        re.compile(r"\bat\s+the\s+end\s+of\s+the\s+day,", _IGNORECASE),
    ),
    (
        "filler_lets_dive_in",
        re.compile(r"\blet['’]s\s+dive\s+in\b", _IGNORECASE),
    ),
)

# Rules applied per line (fenced lines already blanked out by the caller):
# contrastive-negation, dash-punctuation, filler-lexicon.
_LINE_RULES: Tuple[Tuple[str, str, "re.Pattern[str]"], ...] = tuple(
    (rule_id, CATEGORY_CONTRASTIVE_NEGATION, pattern)
    for rule_id, pattern in _CONTRASTIVE_RULES
) + tuple(
    (rule_id, CATEGORY_DASH_PUNCTUATION, pattern) for rule_id, pattern in _DASH_RULES
) + tuple(
    (rule_id, CATEGORY_FILLER_LEXICON, pattern) for rule_id, pattern in _FILLER_RULES
)

# --- 2. hedge-stacking -----------------------------------------------------
#
# One hedge in a sentence is ordinary caution; two or more is the tell.
_HEDGE_RE = re.compile(
    r"\b(?:may|might|could|perhaps|possibly|arguably|potentially|seemingly|"
    r"somewhat|appears to|tends to)\b",
    _IGNORECASE,
)

# --- 5. formulaic-transition ------------------------------------------------
#
# Sentence-initial paragraph openers. A single one is normal writing; the
# drumbeat (two or more in one document) is the tell. Reported from the
# second occurrence onward.
_FORMULAIC_MARKERS: Tuple[Tuple[str, str], ...] = (
    ("formulaic_in_conclusion", "In conclusion,"),
    ("formulaic_furthermore", "Furthermore,"),
    ("formulaic_moreover", "Moreover,"),
    ("formulaic_additionally", "Additionally,"),
)

_SENTENCE_END_RE = re.compile(r"[.!?]")


@dataclass
class TellFinding:
    """One matched style marker in one scanned file."""

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


def _unfenced_lines(
    text: str, *, include_fences: bool
) -> List[Tuple[int, str]]:
    """1-based (line_number, line_text) pairs; fenced lines blanked unless
    include_fences is true. Reuses slop's fence-delimiter regex so a line is
    "inside a fence" by exactly the same definition ``warrantos slop`` uses.
    """
    lines: List[Tuple[int, str]] = []
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
                lines.append((line_number, ""))
                continue
            if in_fence:
                lines.append((line_number, ""))
                continue
        lines.append((line_number, line))
    return lines


def _line_starts(texts: Sequence[str]) -> List[int]:
    """Character offset of the start of each line in "\\n".join(texts)."""
    starts: List[int] = []
    offset = 0
    for t in texts:
        starts.append(offset)
        offset += len(t) + 1
    return starts


def _line_for_offset(starts: List[int], offset: int) -> int:
    idx = bisect.bisect_right(starts, offset) - 1
    if idx < 0:
        idx = 0
    return idx + 1


def _iter_sentences(text: str) -> Iterator[Tuple[int, str]]:
    """Yield (start_offset, sentence_text) split on . ! ? boundaries.

    A simple splitter (no abbreviation handling): precision is enforced by
    the rules that consume sentences, not by sentence detection itself.
    """
    start = 0
    for m in _SENTENCE_END_RE.finditer(text):
        end = m.end()
        yield start, text[start:end]
        start = end
    if start < len(text):
        yield start, text[start:]


def scan_text(
    text: str, display_path: str, *, include_fences: bool = False
) -> List[TellFinding]:
    """Scan one document's text; return findings with 1-based line numbers.

    Lines inside fenced code blocks (``` or ~~~) are skipped unless
    include_fences is true, matching ``warrantos slop`` semantics exactly.
    """
    findings: List[TellFinding] = []
    lines = _unfenced_lines(text, include_fences=include_fences)

    # Line-scoped rules: contrastive-negation, dash-punctuation, filler-lexicon.
    for line_number, line in lines:
        if not line:
            continue
        for rule_id, category, pattern in _LINE_RULES:
            for match in pattern.finditer(line):
                findings.append(
                    TellFinding(
                        path=display_path,
                        line=line_number,
                        match=_truncate(match.group(0)),
                        category=category,
                        rule_id=rule_id,
                    )
                )

    # Sentence-scoped rules: hedge-stacking, formulaic-transition.
    texts = [t for _, t in lines]
    unfenced_text = "\n".join(texts)
    starts = _line_starts(texts)

    transition_count = 0
    for sent_start, sentence in _iter_sentences(unfenced_text):
        if not sentence.strip():
            continue

        hedge_matches = list(_HEDGE_RE.finditer(sentence))
        if len(hedge_matches) >= 2:
            # Anchor the line to the first non-whitespace character so a
            # sentence that begins after a newline reports its own line.
            hedge_lead = len(sentence) - len(sentence.lstrip())
            line_no = _line_for_offset(starts, sent_start + hedge_lead)
            findings.append(
                TellFinding(
                    path=display_path,
                    line=line_no,
                    match=_truncate(sentence.strip()),
                    category=CATEGORY_HEDGE_STACKING,
                    rule_id="hedge_stacking",
                )
            )

        stripped = sentence.lstrip()
        lead_ws = len(sentence) - len(stripped)
        for rule_id, marker in _FORMULAIC_MARKERS:
            if stripped.startswith(marker):
                transition_count += 1
                if transition_count >= 2:
                    line_no = _line_for_offset(starts, sent_start + lead_ws)
                    findings.append(
                        TellFinding(
                            path=display_path,
                            line=line_no,
                            match=marker,
                            category=CATEGORY_FORMULAIC_TRANSITION,
                            rule_id=rule_id,
                        )
                    )
                break

    findings.sort(key=lambda f: (f.line, f.rule_id, f.match))
    return findings


def scan_paths(
    paths: Sequence[str], *, include_fences: bool = False
) -> Tuple[List[TellFinding], int]:
    """Scan the given files and directories.

    Same discovery semantics as ``warrantos.provenance.slop.scan_paths``:
    directories are walked recursively for .md, .rst and .txt files with
    the skip list applied (via the imported ``iter_candidate_files``); a
    path naming a file directly is scanned whatever its extension. Returns
    (findings, files_scanned). Raises FileNotFoundError for a path argument
    that does not exist.
    """
    findings: List[TellFinding] = []
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


def tell_score(findings_count: int, files_scanned: int) -> float:
    """Density-based score on 0.0 to 10.0; identical formula to SLOP SCORE
    (imported from ``warrantos.provenance.slop.slop_score``)."""
    return _density_score(findings_count, files_scanned)


def badge_url(score: float, findings_count: int) -> str:
    """shields.io badge URL: green 'tells clean' at 0 findings, red score
    line otherwise. Reuses the slop shields.io base so both badges render
    from the same visual family."""
    if findings_count == 0:
        label, message, colour = "tells", "clean", "brightgreen"
    else:
        label, message, colour = "tells", "%.1f/10" % score, "red"
    return _SHIELDS_BASE + "%s-%s-%s" % (
        quote(label, safe=""),
        quote(message, safe=""),
        colour,
    )


def build_report(
    findings: List[TellFinding], files_scanned: int
) -> Dict[str, object]:
    score = tell_score(len(findings), files_scanned)
    return {
        "schema": "warrantos-tells/v1",
        "score": score,
        "files_scanned": files_scanned,
        "findings_count": len(findings),
        "findings": [f.to_dict() for f in findings],
        "badge_url": badge_url(score, len(findings)),
    }


def format_table(findings: List[TellFinding], files_scanned: int) -> str:
    score = tell_score(len(findings), files_scanned)
    lines = [
        "TELL SCORE: %.1f/10  (%d finding(s) across %d file(s) scanned)"
        % (score, len(findings), files_scanned)
    ]
    if not findings:
        lines.append("No AI-writing tells detected.")
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


def run_tells(
    paths: Optional[Sequence[str]] = None,
    *,
    as_json: bool = False,
    badge: bool = False,
    fail_over: Optional[float] = None,
    include_fences: bool = False,
) -> int:
    """Entry point for the ``warrantos tells`` subcommand.

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
        sys.stderr.write("warrantos tells: path not found: %s\n" % exc)
        return 2

    score = tell_score(len(findings), files_scanned)

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
