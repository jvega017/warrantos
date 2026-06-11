#!/usr/bin/env python3
"""claude-provenance: the Provenance Loop hook.

Reads a Claude Code hook event on stdin. Extracts candidate factual claims
from the model's final message (Stop) or a written file (PostToolUse), checks
each claim for an adjacent source or an explicit [CITE NEEDED] tag, logs the
result to a portable SQLite ledger, and either reports or hard-blocks.

Design rules:
  - stdlib only, zero dependencies (friction kills adoption)
  - never crash the session: any internal error exits 0 silently
  - Stop-loop safe: respects stop_hook_active, never blocks twice
  - heuristic by design (v0). It catches the claims that matter most in
    policy and research writing: numbers, years, percentages, statute
    references, and attribution verbs. It is not a substitute for human
    review and does not claim to be.

Modes (env PROVENANCE_MODE): report (default) | enforce | off
Ledger path (env PROVENANCE_DB): default <cwd>/.provenance/provenance.db
"""

import os
import re
import sys
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MAX_LISTED = 8  # cap unsupported claims shown in the report


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_event():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _last_assistant_text(transcript_path):
    """Return the text of the most recent assistant message in the jsonl
    transcript. Defensive against schema drift across Claude Code versions."""
    try:
        p = Path(transcript_path)
        if not p.is_file():
            return ""
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "assistant":
                continue
            msg = obj.get("message", obj)
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                if parts:
                    return "\n".join(parts)
        return ""
    except Exception:
        return ""


def _written_text(event):
    """Extract the content a Write/Edit/MultiEdit tool produced."""
    try:
        ti = event.get("tool_input", {}) or {}
        if "content" in ti:                       # Write
            return str(ti.get("content", ""))
        if "new_string" in ti:                    # Edit
            return str(ti.get("new_string", ""))
        if "edits" in ti and isinstance(ti["edits"], list):  # MultiEdit
            return "\n".join(str(e.get("new_string", "")) for e in ti["edits"])
        return ""
    except Exception:
        return ""


# --- heuristics -----------------------------------------------------------

CITATION_MARKERS = [
    re.compile(r"https?://", re.I),
    re.compile(r"\(?\bsource\s*:", re.I),
    re.compile(r"\[[^\]]+\]\([^)]+\)"),                    # markdown link
    re.compile(r"\[\^?\d+\]"),                              # footnote ref
    re.compile(r"\([A-Z][\w.'-]+(?:\s(?:&|et al\.?|and)\s[\w.'-]+)*,\s*\d{4}[a-z]?\)"),  # APA
]
CITE_NEEDED = re.compile(r"\[cite[ _-]?needed\]", re.I)

# A "citation-lead" sentence is one that is essentially just a source, e.g.
# the second sentence in "X rose 12%. Source: https://...". It may cover the
# claim immediately before it. A citation anywhere else does NOT bleed onto
# an unrelated neighbouring claim: that was the v0 false-negative.
CITATION_LEAD = re.compile(
    r"^\s*[\(\[]*\s*(?:source\s*:|https?://|\[\^?\d+\]|\[[^\]]+\]\([^)]+\))", re.I)

CLAIM_TRIGGERS = [
    ("year",        re.compile(r"\b(?:18|19|20)\d{2}\b")),
    ("percentage",  re.compile(r"\b\d+(?:\.\d+)?\s?%|\bper\s?cent\b|\bpercent\b", re.I)),
    ("magnitude",   re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:million|billion|trillion|bn|tn)\b", re.I)),
    ("statute",     re.compile(r"\b(?:s\.?\s?\d+|section\s\d+|Act\s(?:18|19|20)\d{2})\b")),
    ("attribution", re.compile(r"\b(?:according to|found that|reported that|estimated|shows that|study\b|survey\b|data show|statistics show)\b", re.I)),
    # Decision/obligation language. Closes the alignment bug where salience
    # _DECISION scores must/shall/require sentences load-bearing (0.55) but
    # extract never detected them, so they silently PASSed.
    ("decision",    re.compile(r"\b(?:must|shall|required\s+to|must\s+comply|requires?\b|recommend(?:s|ed)?)\b", re.I)),
    # Superlative claims ("the largest", "fastest", "first ever").
    ("superlative", re.compile(r"\b(?:largest|smallest|highest|lowest|fastest|slowest|best|worst|first|only|unprecedented|most|least)\b", re.I)),
    # Causal claims ("X caused Y", "led to", "as a result of").
    ("causal",      re.compile(r"\b(?:caused|causes|causing|led\s+to|leads?\s+to|results?\s+in|resulted\s+in|due\s+to|as\s+a\s+result\s+of|because\s+of|driven\s+by|attributable\s+to)\b", re.I)),
    # Numeric approximations ("around 40", "roughly 1,000", "about 12%").
    ("numeric_approx", re.compile(r"\b(?:approximately|roughly|around|about|nearly|almost|up\s+to|over|more\s+than|fewer\s+than|less\s+than)\s+\d", re.I)),
    # Named-body attribution (OECD, ABS, Treasury, ANAO and similar).
    ("named_body",  re.compile(r"\b(?:OECD|ABS|Treasury|ANAO|APSC|DTA|Productivity\s+Commission|World\s+Bank|IMF|United\s+Nations|UN|Reserve\s+Bank|RBA|Bureau\s+of\s+Statistics)\b")),
    # Empirical comparison ("more than", "compared to", "twice as", "increase of").
    ("comparison",  re.compile(r"\b(?:compared\s+(?:to|with)|relative\s+to|twice\s+as|half\s+as|\d+\s+times\s+(?:more|less|higher|lower)|increase\s+of|decrease\s+of|outperform(?:s|ed)?|higher\s+than|lower\s+than)\b", re.I)),
]

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|(?:^|\s)[-*]\s+")


def _sentences(text):
    chunks = [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]
    return chunks


def _has_citation(s):
    return any(rx.search(s) for rx in CITATION_MARKERS)


def _is_citation_lead(s):
    return bool(s) and bool(CITATION_LEAD.match(s))


def analyse(text):
    """Return (rows, totals). rows = list of (status, trigger, snippet)."""
    sents = _sentences(text)
    rows = []
    for i, s in enumerate(sents):
        trigger = None
        for name, rx in CLAIM_TRIGGERS:
            if rx.search(s):
                trigger = name
                break
        if not trigger:
            continue
        nxt = sents[i + 1] if i + 1 < len(sents) else ""
        if _has_citation(s) or _is_citation_lead(nxt):
            status = "supported"
        elif CITE_NEEDED.search(s):
            status = "tagged"
        else:
            status = "unsupported"
        snippet = s if len(s) <= 220 else s[:217] + "..."
        rows.append((status, trigger, snippet))
    totals = {
        "total": len(rows),
        "supported": sum(1 for r in rows if r[0] == "supported"),
        "tagged": sum(1 for r in rows if r[0] == "tagged"),
        "unsupported": sum(1 for r in rows if r[0] == "unsupported"),
    }
    return rows, totals


# --- ledger ---------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, session_id TEXT,
    source_event TEXT, file_path TEXT, mode TEXT NOT NULL,
    total INTEGER NOT NULL, supported INTEGER NOT NULL,
    tagged INTEGER NOT NULL, unsupported INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS provenance_claim (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
    ts TEXT NOT NULL, session_id TEXT, status TEXT NOT NULL,
    trigger TEXT, claim_text TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS trg_provenance_run_no_update
BEFORE UPDATE ON provenance_run
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;
CREATE TRIGGER IF NOT EXISTS trg_provenance_run_no_delete
BEFORE DELETE ON provenance_run
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;
CREATE TRIGGER IF NOT EXISTS trg_provenance_claim_no_update
BEFORE UPDATE ON provenance_claim
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;
CREATE TRIGGER IF NOT EXISTS trg_provenance_claim_no_delete
BEFORE DELETE ON provenance_claim
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;
"""


def _ledger_path():
    env = os.environ.get("PROVENANCE_DB")
    if env:
        return Path(env)
    return Path(os.getcwd()) / ".provenance" / "provenance.db"


def log(session_id, source_event, file_path, mode, rows, totals):
    try:
        path = _ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), timeout=10)
        con.executescript(SCHEMA)
        ts = _now()
        cur = con.execute(
            "INSERT INTO provenance_run "
            "(ts,session_id,source_event,file_path,mode,total,supported,tagged,unsupported) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, session_id, source_event, file_path, mode,
             totals["total"], totals["supported"], totals["tagged"], totals["unsupported"]),
        )
        run_id = cur.lastrowid
        con.executemany(
            "INSERT INTO provenance_claim "
            "(run_id,ts,session_id,status,trigger,claim_text) VALUES (?,?,?,?,?,?)",
            [(run_id, ts, session_id, st, tg, txt) for (st, tg, txt) in rows],
        )
        con.commit()
        con.close()
    except Exception:
        pass  # the ledger is best-effort; never break the session over it


# --- report ---------------------------------------------------------------

def build_report(totals, rows, where):
    lines = [
        "Provenance Loop: %d claim(s) checked in %s." % (totals["total"], where),
        "  supported: %d   [CITE NEEDED]: %d   UNSUPPORTED: %d"
        % (totals["supported"], totals["tagged"], totals["unsupported"]),
    ]
    unsup = [r for r in rows if r[0] == "unsupported"]
    if unsup:
        lines.append("")
        lines.append("Unsupported factual claims (add a source or an explicit [CITE NEEDED]):")
        for st, tg, txt in unsup[:MAX_LISTED]:
            lines.append("  - [%s] %s" % (tg, txt))
        if len(unsup) > MAX_LISTED:
            lines.append("  ... and %d more." % (len(unsup) - MAX_LISTED))
    return "\n".join(lines)


# --- main -----------------------------------------------------------------

def main():
    mode = os.environ.get("PROVENANCE_MODE", "report").strip().lower()
    if mode == "off":
        sys.exit(0)

    event = _read_event()
    ev_name = event.get("hook_event_name", "")
    session_id = event.get("session_id", "")

    # Stop-loop guard: if we already blocked once this turn, do nothing.
    if ev_name == "Stop" and event.get("stop_hook_active"):
        sys.exit(0)

    file_path = None
    if ev_name == "PostToolUse":
        text = _written_text(event)
        file_path = (event.get("tool_input", {}) or {}).get("file_path")
        where = "the written file"
    else:  # Stop, or anything else, falls back to the last assistant message
        text = _last_assistant_text(event.get("transcript_path", ""))
        where = "the final message"

    if not text or not text.strip():
        sys.exit(0)

    rows, totals = analyse(text)
    if totals["total"] == 0:
        sys.exit(0)

    log(session_id, ev_name or "Stop", file_path, mode, rows, totals)
    report = build_report(totals, rows, where)

    if mode == "enforce" and totals["unsupported"] > 0:
        # Block and hand the report back to Claude so it can add sources.
        print(json.dumps({"decision": "block", "reason": report}))
        sys.exit(0)

    # report mode: surface to the user without blocking (stderr is shown
    # for hooks in Claude Code), and exit clean.
    sys.stderr.write(report + "\n")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Absolute backstop: a provenance hook must never break a session.
        sys.exit(0)
