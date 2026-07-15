"""provenance.ledger: read and summarise the provenance ledger.

Provides read-only utilities for analysing the SQLite ledger written by
hooks/provenance_check.py. This module never creates or migrates tables;
it tolerates schema drift (e.g., an absent provenance_verification table)
and degrades gracefully rather than raising.

All functions are tolerant of an empty ledger: they return zero counts and
empty collections rather than raising.

Debt normalisation:
  When provenance_run rows contain non-zero word-count data the denominator
  is the total word count across all analysed runs. The provenance_run schema
  (v0/v1) does not store word counts, so this module uses total claims as the
  denominator proxy. The returned dict includes a 'denominator' key whose value
  is 'words' or 'claims' so callers can report the proxy honestly.

Stdlib only. Python 3.8 compatible. No third-party dependencies.
Australian English throughout.
"""

import csv
import io
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union

from warrantos.provenance.salience import is_load_bearing

# ---------------------------------------------------------------------------
# Schema probe helpers
# ---------------------------------------------------------------------------

def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    """Return True if *name* exists as a table in *con*."""
    row = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row and row[0])


# ---------------------------------------------------------------------------
# open_ledger
# ---------------------------------------------------------------------------

def open_ledger(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open the ledger database at *db_path* and return a connection.

    The connection is opened with the read-only URI flag when the file exists,
    so this function will never create a new database file or modify an existing
    one. If the file does not exist, an empty in-memory database is returned so
    that callers can proceed without raising.

    No tables are created by this function.

    Parameters
    ----------
    db_path:
        Path to the SQLite ledger file.

    Returns
    -------
    sqlite3.Connection
    """
    p = Path(db_path)
    if not p.is_file():
        # Return an empty in-memory DB so callers see an empty ledger.
        return sqlite3.connect(":memory:")
    # Use the URI form to request read-only access.
    uri = "file:" + str(p).replace("\\", "/") + "?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        # Fallback: open read-write (existing file, permission issues, etc.)
        return sqlite3.connect(str(p))


# ---------------------------------------------------------------------------
# epistemic_debt
# ---------------------------------------------------------------------------

def epistemic_debt(db_path: Union[str, Path]) -> dict:
    """Compute an epistemic-debt summary from the ledger.

    Returns a dict with the following keys:

    totals : dict
        runs         -- total number of provenance_run rows
        claims       -- total number of provenance_claim rows
        supported    -- claims with status='supported'
        tagged       -- claims with status='tagged'
        unsupported  -- claims with status='unsupported'

    verification : dict
        verified, contradicted, not_addressed, unverifiable, skipped
        (each is the count of provenance_verification rows with that verdict).
        All values are zero when the provenance_verification table is absent or
        empty.

    load_bearing_unsupported : int
        Count of provenance_claim rows where status='unsupported' and
        is_load_bearing(claim_text) is True. These are the highest-priority
        claims to remediate.

    debt_per_1000_words : float
        load_bearing_unsupported normalised to a per-1000-unit rate. The
        denominator is total claims (not words) because the v0/v1 schema does
        not store word counts. See the 'denominator' key.

    denominator : str
        'words' when word counts are available; 'claims' when claims are used
        as the proxy denominator (current behaviour). Always 'claims' in v1.

    trend : dict
        runs    -- list of up to 5 most recent runs as dicts with keys:
                   ts, unsupported, total
                   ordered oldest to newest.
        direction -- 'up', 'down', or 'flat' based on the unsupported rate
                     of the oldest vs newest run in the trend window.

    Parameters
    ----------
    db_path:
        Path to the SQLite ledger file.

    Returns
    -------
    dict
    """
    con = open_ledger(db_path)
    try:
        return _compute_debt(con)
    finally:
        con.close()


def _compute_debt(con: sqlite3.Connection) -> dict:
    # -----------------------------------------------------------------
    # Totals from provenance_run and provenance_claim
    # -----------------------------------------------------------------
    run_table = _table_exists(con, "provenance_run")
    claim_table = _table_exists(con, "provenance_claim")

    if run_table:
        runs = con.execute("SELECT COUNT(*) FROM provenance_run").fetchone()[0]
    else:
        runs = 0

    claims_total = 0
    supported = 0
    tagged = 0
    unsupported = 0

    if claim_table:
        row = con.execute(
            "SELECT COUNT(*) FROM provenance_claim"
        ).fetchone()
        claims_total = row[0] if row else 0

        row = con.execute(
            "SELECT COUNT(*) FROM provenance_claim WHERE status='supported'"
        ).fetchone()
        supported = row[0] if row else 0

        row = con.execute(
            "SELECT COUNT(*) FROM provenance_claim WHERE status='tagged'"
        ).fetchone()
        tagged = row[0] if row else 0

        row = con.execute(
            "SELECT COUNT(*) FROM provenance_claim WHERE status='unsupported'"
        ).fetchone()
        unsupported = row[0] if row else 0

    totals = {
        "runs": runs,
        "claims": claims_total,
        "supported": supported,
        "tagged": tagged,
        "unsupported": unsupported,
    }

    # -----------------------------------------------------------------
    # Verification counts (degrade to zeros if table absent/empty)
    # -----------------------------------------------------------------
    verif_counts: Dict[str, int] = {
        "verified": 0,
        "contradicted": 0,
        "not_addressed": 0,
        "unverifiable": 0,
        "skipped": 0,
    }
    if _table_exists(con, "provenance_verification"):
        try:
            rows = con.execute(
                "SELECT verdict, COUNT(*) FROM provenance_verification GROUP BY verdict"
            ).fetchall()
            for verdict, count in rows:
                if verdict in verif_counts:
                    verif_counts[verdict] = count
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            # D2: integrity path - catch specific, log unexpected
            sys.stderr.write(f"Warning: ledger verification counts read failed: {e}\n")

    # -----------------------------------------------------------------
    # Load-bearing unsupported claims
    # -----------------------------------------------------------------
    lb_unsupported = 0
    if claim_table:
        try:
            unsup_rows = con.execute(
                "SELECT claim_text FROM provenance_claim WHERE status='unsupported'"
            ).fetchall()
            for (claim_text,) in unsup_rows:
                if is_load_bearing(claim_text):
                    lb_unsupported += 1
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            # D2: integrity path - catch specific, log unexpected
            sys.stderr.write(f"Warning: ledger load-bearing claims read failed: {e}\n")

    # -----------------------------------------------------------------
    # debt_per_1000_words (proxy: uses claims as denominator)
    # -----------------------------------------------------------------
    if claims_total > 0:
        debt_per_1000 = (lb_unsupported / claims_total) * 1000.0
    else:
        debt_per_1000 = 0.0
    denominator = "claims"

    # -----------------------------------------------------------------
    # Trend: last 5 runs, oldest to newest
    # -----------------------------------------------------------------
    trend_runs: List[dict] = []
    direction = "flat"
    if run_table:
        try:
            trend_rows = con.execute(
                "SELECT ts, unsupported, total FROM provenance_run "
                "ORDER BY id DESC LIMIT 5"
            ).fetchall()
            # Reverse so oldest is first.
            trend_rows = list(reversed(trend_rows))
            trend_runs = [
                {"ts": ts, "unsupported": unsp, "total": tot}
                for ts, unsp, tot in trend_rows
            ]
            if len(trend_runs) >= 2:
                first = trend_runs[0]
                last = trend_runs[-1]
                first_rate = (
                    first["unsupported"] / first["total"]
                    if first["total"] > 0 else 0.0
                )
                last_rate = (
                    last["unsupported"] / last["total"]
                    if last["total"] > 0 else 0.0
                )
                if last_rate > first_rate:
                    direction = "up"
                elif last_rate < first_rate:
                    direction = "down"
                else:
                    direction = "flat"
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            # D2: integrity path - catch specific, log unexpected
            sys.stderr.write(f"Warning: ledger trend read failed: {e}\n")

    return {
        "totals": totals,
        "verification": verif_counts,
        "load_bearing_unsupported": lb_unsupported,
        "debt_per_1000_words": debt_per_1000,
        "denominator": denominator,
        "trend": {
            "runs": trend_runs,
            "direction": direction,
        },
    }


# ---------------------------------------------------------------------------
# export_evidence_matrix
# ---------------------------------------------------------------------------

# Columns for the evidence matrix output.
_COLUMNS = ["claim_id", "status", "trigger", "salience", "verdict", "citation", "claim_text"]

_NO_CLAIMS_NOTE = "no claims recorded"


def export_evidence_matrix(
    db_path: Union[str, Path],
    out_path: Union[str, Path],
    fmt: str = "md",
) -> str:
    """Write an evidence matrix to *out_path* and return the path written.

    Columns: claim_id, status, trigger, salience, verdict, citation, claim_text.

    Salience is computed at export time via salience.score_claim(). The verdict
    column contains the most recent provenance_verification verdict for each
    claim, or an empty string when no verification row exists.

    When the ledger is empty (no claims table or zero rows), a header-only file
    is written with a 'no claims recorded' note rather than raising.

    Parameters
    ----------
    db_path:
        Path to the SQLite ledger file.
    out_path:
        Destination file path. Parent directory must exist.
    fmt:
        'md' for a Markdown table; 'csv' for CSV. Default is 'md'.

    Returns
    -------
    str
        The absolute path of the written file as a string.

    Raises
    ------
    ValueError
        When *fmt* is not 'md' or 'csv'.
    """
    fmt = fmt.lower().strip()
    if fmt not in ("md", "csv"):
        raise ValueError("fmt must be 'md' or 'csv', got: %r" % fmt)

    con = open_ledger(db_path)
    try:
        rows = _collect_matrix_rows(con)
    finally:
        con.close()

    out_path = Path(out_path)
    if fmt == "md":
        content = _render_md(rows)
    else:
        content = _render_csv(rows)

    out_path.write_text(content, encoding="utf-8")
    return str(out_path.resolve())


def _collect_matrix_rows(con: sqlite3.Connection) -> List[dict]:
    """Return a list of row dicts for the evidence matrix.

    Each dict has keys matching _COLUMNS. Salience is computed here.
    Verdict is the most recent verification verdict per claim (empty if none).
    """
    if not _table_exists(con, "provenance_claim"):
        return []

    # Build a map: claim_id -> most recent verdict + citation from verification.
    verif_map: Dict[int, dict] = {}
    if _table_exists(con, "provenance_verification"):
        try:
            vrows = con.execute(
                "SELECT claim_id, verdict, citation "
                "FROM provenance_verification "
                "ORDER BY id ASC"   # latest wins because we overwrite in loop
            ).fetchall()
            for claim_id, verdict, citation in vrows:
                verif_map[claim_id] = {"verdict": verdict, "citation": citation or ""}
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            # D2: integrity path - catch specific, log unexpected
            sys.stderr.write(f"Warning: ledger verification map read failed: {e}\n")

    try:
        claim_rows = con.execute(
            "SELECT id, status, trigger, claim_text FROM provenance_claim ORDER BY id"
        ).fetchall()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        # D2: integrity path - catch specific, log unexpected
        sys.stderr.write(f"Warning: ledger claim rows read failed: {e}\n")
        return []

    result = []
    for claim_id, status, trigger, claim_text in claim_rows:
        salience = score_round(claim_text)
        verif = verif_map.get(claim_id, {})
        verdict = verif.get("verdict", "")
        citation = verif.get("citation", "")
        result.append({
            "claim_id": claim_id,
            "status": status or "",
            "trigger": trigger or "",
            "salience": salience,
            "verdict": verdict,
            "citation": citation,
            "claim_text": claim_text or "",
        })
    return result


def score_round(claim_text: str) -> str:
    """Return salience as a 2-decimal-place string (e.g., '0.75')."""
    from warrantos.provenance.salience import score_claim
    return "%.2f" % score_claim(claim_text)


def _render_md(rows: List[dict]) -> str:
    """Render rows as a Markdown table."""
    header = "| " + " | ".join(_COLUMNS) + " |"
    separator = "| " + " | ".join(["---"] * len(_COLUMNS)) + " |"
    lines = [header, separator]
    if not rows:
        empty_row = "| " + " | ".join(
            [_NO_CLAIMS_NOTE] + [""] * (len(_COLUMNS) - 1)
        ) + " |"
        lines.append(empty_row)
    else:
        for row in rows:
            cells = [str(row[col]).replace("|", "\\|") for col in _COLUMNS]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _render_csv(rows: List[dict]) -> str:
    """Render rows as CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()
    if not rows:
        writer.writerow({col: (_NO_CLAIMS_NOTE if col == "claim_id" else "") for col in _COLUMNS})
    else:
        for row in rows:
            writer.writerow({col: str(row[col]) for col in _COLUMNS})
    return buf.getvalue()
