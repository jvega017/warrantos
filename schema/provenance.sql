-- claude-provenance: claim -> source ledger
-- Portable SQLite schema. The hook creates these tables automatically;
-- this file is the canonical reference and is safe to apply by hand:
--   sqlite3 .provenance/provenance.db < schema/provenance.sql

CREATE TABLE IF NOT EXISTS provenance_run (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,           -- ISO-8601 UTC
    session_id   TEXT,
    source_event TEXT,                       -- Stop | PostToolUse
    file_path    TEXT,                       -- set for PostToolUse on Write/Edit
    mode         TEXT    NOT NULL,           -- report | enforce
    total        INTEGER NOT NULL,
    supported    INTEGER NOT NULL,
    tagged       INTEGER NOT NULL,           -- explicit [CITE NEEDED], compliant
    unsupported  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS provenance_claim (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES provenance_run(id),
    ts          TEXT    NOT NULL,
    session_id  TEXT,
    status      TEXT    NOT NULL,            -- supported | tagged | unsupported
    trigger     TEXT,                        -- which heuristic fired
    claim_text  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claim_status ON provenance_claim(status);
CREATE INDEX IF NOT EXISTS idx_run_ts       ON provenance_run(ts);

-- v1: out-of-band verification results
-- Records the verdict produced by verify_claim / verify_text for each
-- provenance_claim row. A claim may have zero or more verification rows
-- (zero if it was never verified out-of-band; multiple if re-checked).

CREATE TABLE IF NOT EXISTS provenance_verification (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id    INTEGER NOT NULL REFERENCES provenance_claim(id),
    ts          TEXT    NOT NULL,              -- ISO-8601 UTC
    citation    TEXT,                          -- URL or APA ref used, or NULL
    verdict     TEXT    NOT NULL,              -- verified | contradicted | not_addressed | unverifiable | skipped | error
    confidence  REAL,                          -- 0.0-1.0 or NULL
    rationale   TEXT,                          -- plain text, <=200 chars
    grader      TEXT    NOT NULL               -- heuristic | fetch+heuristic | llm:<model> | fetch+llm:<model>
);

CREATE INDEX IF NOT EXISTS idx_verif_claim   ON provenance_verification(claim_id);
CREATE INDEX IF NOT EXISTS idx_verif_verdict ON provenance_verification(verdict);
