-- claude-provenance: claim -> source ledger
-- Portable SQLite schema. The hook creates these tables automatically;
-- this file is the canonical reference and is safe to apply by hand:
--   sqlite3 .provenance/provenance.db < schema/provenance.sql

CREATE TABLE IF NOT EXISTS provenance_run (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT    NOT NULL,           -- ISO-8601 UTC
    session_id            TEXT,
    source_event          TEXT,                       -- Stop | PostToolUse
    file_path             TEXT,                       -- set for PostToolUse on Write/Edit
    mode                  TEXT    NOT NULL,           -- report | enforce
    total                 INTEGER NOT NULL,
    supported             INTEGER NOT NULL,
    tagged                INTEGER NOT NULL,           -- explicit [CITE NEEDED], compliant
    unsupported           INTEGER NOT NULL,
    retention_window_days INTEGER                     -- F-retention (INV-011): NULL = keep indefinitely
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

-- v2: Context Integrity Layer
-- Tracks fuzzy/process context separately from final prose. This is the
-- BriefLock use case: context may influence output, appear only in audit
-- metadata, or be excluded entirely.

CREATE TABLE IF NOT EXISTS context_item (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                         TEXT    NOT NULL,      -- ISO-8601 UTC
    context_id                 TEXT    NOT NULL,
    context_type               TEXT    NOT NULL,      -- user_feedback | empirical_evidence | style_signal | ...
    ledger_bucket              TEXT    NOT NULL,      -- empirical | synthesised | process | excluded
    can_influence_output       INTEGER NOT NULL,      -- 0 | 1
    can_appear_in_final_prose  INTEGER NOT NULL,      -- 0 | 1
    allowed_transformation     TEXT    NOT NULL,      -- derived_requirement | claim_or_citation | ...
    audit_status               TEXT    NOT NULL,      -- recorded | audit_only | excluded
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
    context_row_id INTEGER NOT NULL REFERENCES context_item(id),
    ts             TEXT    NOT NULL,
    kind           TEXT    NOT NULL,
    transform_text TEXT    NOT NULL
);

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

-- SPEC-v0.2 Layer 8: structured human override ledger
-- A row in human_override records every human-recorded override of a
-- Layer 7 gate verdict. SPEC-L8-S002 requires that overrides are
-- recorded as ledger rows; SPEC-L8-S004 requires that the rationale
-- conforms to this structured schema with non-empty risk_accepted and
-- non-empty compensating_control fields (empty values SHALL block the
-- override at the write path). SPEC-L8-S003 requires that
-- single_actor=1 implies the artefact is downgraded out of final-prose.

CREATE TABLE IF NOT EXISTS human_override (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                      TEXT    NOT NULL,    -- ISO-8601 UTC
    run_id                  TEXT    NOT NULL,    -- WarrantOS run identifier
    reviewer                TEXT    NOT NULL,    -- identity that approved the override
    gate_id                 TEXT    NOT NULL,    -- which Layer 7 gate failed (G1/G2/G3/G4/G5)
    failure_class           TEXT    NOT NULL,    -- the verdict that fired (boundary | unsupported | contradicted | ...)
    risk_accepted           TEXT    NOT NULL,    -- SPEC-L8-S004: SHALL be non-empty
    compensating_control    TEXT    NOT NULL,    -- SPEC-L8-S004: SHALL be non-empty
    escalation_path_taken   TEXT    NOT NULL,    -- MAY be "none recorded" but column is non-null
    single_actor            INTEGER NOT NULL     -- 0 | 1 per SPEC-L8-S003
);

CREATE INDEX IF NOT EXISTS idx_human_override_run_id  ON human_override(run_id);
CREATE INDEX IF NOT EXISTS idx_human_override_gate_id ON human_override(gate_id);

-- INV-004 storage-level enforcement: SPEC-L2-S002 append-only.
-- Idempotent via IF NOT EXISTS. Triggers ship by default.
-- Ledger tables (human_override, context_transform, provenance_run,
-- provenance_claim, provenance_verification, context_item, cbom_run,
-- review_finding, prose_boundary_violation) block UPDATE and DELETE.

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

-- F-retention (INV-011): retention as tombstones, NEVER hard delete.
-- A provenance_run carries an optional retention_window_days. When the
-- window elapses, retention.tombstone_run() appends a row here recording
-- that the run is logically expired. The underlying ledger rows are
-- preserved (append-only is never violated); a tombstone is an additive
-- marker that downstream readers consult to treat the run as retired.
-- This is deliberately NOT a DELETE: the audit trail stays intact and the
-- expiry itself becomes part of the append-only record.

CREATE TABLE IF NOT EXISTS provenance_tombstone (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT    NOT NULL,           -- ISO-8601 UTC the tombstone was written
    run_id                INTEGER NOT NULL REFERENCES provenance_run(id),
    reason                TEXT    NOT NULL,           -- e.g. retention_window_elapsed
    retention_window_days INTEGER,                    -- the window that triggered expiry (snapshot)
    expired_after         TEXT                        -- ISO-8601 UTC cutoff the run fell past
);

CREATE INDEX IF NOT EXISTS idx_tombstone_run ON provenance_tombstone(run_id);

-- The tombstone ledger is itself append-only: a tombstone, once written,
-- is part of the permanent audit record and cannot be amended or removed.
CREATE TRIGGER IF NOT EXISTS trg_provenance_tombstone_no_update
BEFORE UPDATE ON provenance_tombstone
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_provenance_tombstone_no_delete
BEFORE DELETE ON provenance_tombstone
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;
