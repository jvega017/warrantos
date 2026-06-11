"""provenance.ledger_write: write-path helpers for the L2 ledger.

`provenance.ledger` is read-only by design (it opens databases with the
`mode=ro` URI flag). This module is the write-path counterpart for the
runtime operations that MUST persist:

- `persist_context_transform()` — Layer 3 SPEC-L3-N001: every derived
  requirement SHALL produce a ledger row.
- `enable_append_only_triggers()` — INV-004 storage-level enforcement.
  Installs SQLite triggers that abort UPDATE on audit-bearing tables.

This module performs read-write SQLite operations. Distinct from
`provenance.overrides` (which has its own write path for the
human_override table specifically). Stdlib only.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from warrantos.provenance.context_admissibility import ContextItem, DerivedRequirement


# Tables that SHALL be append-only at the storage layer (INV-004
# ENFORCED via trigger after this module is invoked against a db).
_APPEND_ONLY_TABLES = (
    "human_override",
    "context_transform",
    "provenance_run",
    "provenance_claim",
    "provenance_verification",
    "context_item",
    "cbom_run",
    "review_finding",
    "prose_boundary_violation",
)


_CREATE_CONTEXT_TRANSFORM_SQL = """
CREATE TABLE IF NOT EXISTS context_transform (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    context_row_id  INTEGER,
    ts              TEXT    NOT NULL,
    run_id          TEXT,
    kind            TEXT    NOT NULL,
    transform_text  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_context_transform_run  ON context_transform(run_id);
CREATE INDEX IF NOT EXISTS idx_context_transform_kind ON context_transform(kind);
"""

# Full ledger schema with INV-004 append-only triggers (shipped by default).
_CREATE_FULL_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_run (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    session_id   TEXT,
    source_event TEXT,
    file_path    TEXT,
    mode         TEXT    NOT NULL,
    total        INTEGER NOT NULL,
    supported    INTEGER NOT NULL,
    tagged       INTEGER NOT NULL,
    unsupported  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS provenance_claim (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES provenance_run(id),
    ts          TEXT    NOT NULL,
    session_id  TEXT,
    status      TEXT    NOT NULL,
    trigger     TEXT,
    claim_text  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claim_status ON provenance_claim(status);
CREATE INDEX IF NOT EXISTS idx_run_ts       ON provenance_run(ts);

CREATE TABLE IF NOT EXISTS provenance_verification (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id    INTEGER NOT NULL REFERENCES provenance_claim(id),
    ts          TEXT    NOT NULL,
    citation    TEXT,
    verdict     TEXT    NOT NULL,
    confidence  REAL,
    rationale   TEXT,
    grader      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_verif_claim   ON provenance_verification(claim_id);
CREATE INDEX IF NOT EXISTS idx_verif_verdict ON provenance_verification(verdict);

CREATE TABLE IF NOT EXISTS context_item (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                         TEXT    NOT NULL,
    context_id                 TEXT    NOT NULL,
    context_type               TEXT    NOT NULL,
    ledger_bucket              TEXT    NOT NULL,
    can_influence_output       INTEGER NOT NULL,
    can_appear_in_final_prose  INTEGER NOT NULL,
    allowed_transformation     TEXT    NOT NULL,
    audit_status               TEXT    NOT NULL,
    raw_text                   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS cbom_run (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT    NOT NULL,
    cbom_id        TEXT    NOT NULL,
    artefact       TEXT,
    artefact_role  TEXT    NOT NULL,
    summary_json   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS review_finding (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT    NOT NULL,
    review_pack_id      TEXT    NOT NULL,
    reviewer            TEXT    NOT NULL,
    angle               TEXT,
    finding_id          TEXT    NOT NULL,
    severity            TEXT    NOT NULL,
    confidence          TEXT,
    evidence            TEXT,
    recommended_action  TEXT,
    status              TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS context_transform (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    context_row_id INTEGER REFERENCES context_item(id),
    ts             TEXT    NOT NULL,
    run_id         TEXT,
    kind           TEXT    NOT NULL,
    transform_text TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_context_transform_run  ON context_transform(run_id);
CREATE INDEX IF NOT EXISTS idx_context_transform_kind ON context_transform(kind);

CREATE TABLE IF NOT EXISTS prose_boundary_violation (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    artefact     TEXT,
    rule_id      TEXT    NOT NULL,
    severity     TEXT    NOT NULL,
    matched_text TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_id       ON context_item(context_id);
CREATE INDEX IF NOT EXISTS idx_context_type     ON context_item(context_type);
CREATE INDEX IF NOT EXISTS idx_boundary_rule    ON prose_boundary_violation(rule_id);
CREATE INDEX IF NOT EXISTS idx_cbom_id          ON cbom_run(cbom_id);
CREATE INDEX IF NOT EXISTS idx_review_pack      ON review_finding(review_pack_id);

CREATE TABLE IF NOT EXISTS human_override (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                      TEXT    NOT NULL,
    run_id                  TEXT    NOT NULL,
    reviewer                TEXT    NOT NULL,
    gate_id                 TEXT    NOT NULL,
    failure_class           TEXT    NOT NULL,
    risk_accepted           TEXT    NOT NULL,
    compensating_control    TEXT    NOT NULL,
    escalation_path_taken   TEXT    NOT NULL,
    single_actor            INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_human_override_run_id  ON human_override(run_id);
CREATE INDEX IF NOT EXISTS idx_human_override_gate_id ON human_override(gate_id);

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

CREATE TRIGGER IF NOT EXISTS trg_provenance_verification_no_update
BEFORE UPDATE ON provenance_verification
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_provenance_verification_no_delete
BEFORE DELETE ON provenance_verification
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_context_item_no_update
BEFORE UPDATE ON context_item
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_context_item_no_delete
BEFORE DELETE ON context_item
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_cbom_run_no_update
BEFORE UPDATE ON cbom_run
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_cbom_run_no_delete
BEFORE DELETE ON cbom_run
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_finding_no_update
BEFORE UPDATE ON review_finding
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_finding_no_delete
BEFORE DELETE ON review_finding
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_context_transform_no_update
BEFORE UPDATE ON context_transform
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_context_transform_no_delete
BEFORE DELETE ON context_transform
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_prose_boundary_violation_no_update
BEFORE UPDATE ON prose_boundary_violation
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_prose_boundary_violation_no_delete
BEFORE DELETE ON prose_boundary_violation
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS prevent_update_human_override
BEFORE UPDATE ON human_override
BEGIN
    SELECT RAISE(ABORT, 'INV-004: human_override is append-only per SPEC-L2-S002');
END;

CREATE TRIGGER IF NOT EXISTS prevent_delete_human_override
BEFORE DELETE ON human_override
BEGIN
    SELECT RAISE(ABORT, 'INV-004: human_override is append-only per SPEC-L2-S002');
END;
"""


def open_writable_db(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a read-write SQLite connection at db_path.

    Creates the parent directory if absent. Creates the file if needed.
    Applies the full ledger schema with INV-004 append-only triggers.
    Caller owns the connection and SHALL close it.
    """
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.executescript(_CREATE_FULL_LEDGER_SCHEMA)
    con.commit()
    return con


def persist_context_transform(
    db_path: Union[str, Path],
    *,
    requirement: DerivedRequirement,
    run_id: Optional[str] = None,
    context_row_id: Optional[int] = None,
    ts: Optional[str] = None,
) -> int:
    """Write a context_transform row for the supplied DerivedRequirement.

    SPEC-L3-N001 normative: a ledger row SHALL accompany every derived
    requirement. v0.9 closes the runtime wiring that was missing in v0.8.

    Parameters
    ----------
    db_path
        SQLite database to write to. The table is created if absent.
    requirement
        The DerivedRequirement returned by
        provenance.context_admissibility.derive_requirement().
    run_id
        Optional run identifier so downstream queries can scope to a
        single run.
    context_row_id
        Optional FK pointing back to the context_item row that produced
        the requirement.
    ts
        Optional ISO-8601 UTC timestamp; defaults to now.

    Returns
    -------
    int
        The auto-incremented id of the new row.
    """
    if ts is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    con = open_writable_db(db_path)
    try:
        cur = con.execute(
            "INSERT INTO context_transform "
            "(context_row_id, ts, run_id, kind, transform_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                context_row_id,
                ts,
                run_id,
                requirement.kind,
                requirement.text,
            ),
        )
        new_id = int(cur.lastrowid) if cur.lastrowid is not None else -1
        con.commit()
    finally:
        con.close()
    return new_id


def list_context_transforms(
    db_path: Union[str, Path], run_id: Optional[str] = None
) -> list:
    """Return all context_transform rows for *run_id*, or all rows when
    run_id is None.
    """
    p = Path(db_path)
    if not p.is_file():
        return []
    con = sqlite3.connect(str(p))
    try:
        if run_id is None:
            rows = con.execute(
                "SELECT id, ts, run_id, kind, transform_text FROM context_transform ORDER BY id"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, ts, run_id, kind, transform_text FROM context_transform WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
    finally:
        con.close()
    return [
        {
            "id": r[0],
            "ts": r[1],
            "run_id": r[2],
            "kind": r[3],
            "transform_text": r[4],
        }
        for r in rows
    ]


def enable_append_only_triggers(db_path: Union[str, Path]) -> int:
    """Install SQLite BEFORE UPDATE and BEFORE DELETE triggers on every audit-bearing table.

    INV-004 ENFORCED at the storage layer. After this function runs
    against a database, an attempted UPDATE or DELETE on any of the
    tables in _APPEND_ONLY_TABLES raises sqlite3.IntegrityError with the
    spec-named abort reason. Append-only means rows can be inserted but
    never modified or removed; a DELETE is as damaging to a tamper-evident
    ledger as an UPDATE, so both are blocked.

    Idempotent: triggers use IF NOT EXISTS so repeated invocations are
    safe. Returns the number of triggers ensured (two per present table:
    one UPDATE guard and one DELETE guard).

    Tables that do not exist in the target db are skipped silently;
    triggers are only created for present tables.
    """
    p = Path(db_path)
    if not p.is_file():
        return 0

    con = sqlite3.connect(str(p))
    try:
        # Identify which audit-bearing tables actually exist in this db.
        present = set()
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        for (name,) in rows:
            if name in _APPEND_ONLY_TABLES:
                present.add(name)

        count = 0
        for table in sorted(present):
            con.execute(
                "CREATE TRIGGER IF NOT EXISTS prevent_update_" + table + " "
                "BEFORE UPDATE ON " + table + " "
                "BEGIN "
                "SELECT RAISE(ABORT, 'INV-004: " + table + " is append-only per SPEC-L2-S002'); "
                "END;"
            )
            count += 1
            con.execute(
                "CREATE TRIGGER IF NOT EXISTS prevent_delete_" + table + " "
                "BEFORE DELETE ON " + table + " "
                "BEGIN "
                "SELECT RAISE(ABORT, 'INV-004: " + table + " is append-only per SPEC-L2-S002'); "
                "END;"
            )
            count += 1
        con.commit()
    finally:
        con.close()
    return count


def list_append_only_tables() -> list:
    """Return the documented list of audit-bearing tables.

    Useful for callers building tooling around the trigger set.
    """
    return list(_APPEND_ONLY_TABLES)
