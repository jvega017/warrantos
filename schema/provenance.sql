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
