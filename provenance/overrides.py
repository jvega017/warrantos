"""provenance.overrides: structured human override ledger for WarrantOS Layer 8.

Implements SPEC-L8-S002 (overrides recorded as ledger rows), SPEC-L8-S003
(separation of duties enforcement) and SPEC-L8-S004 (structured rationale
with non-empty risk_accepted and compensating_control).

Distinct from provenance.ledger: ledger.py is read-only by design and
opens the database with `mode=ro` URI flags. This module performs write
operations and uses its own read-write connection helper.

The human_override table is the canonical Override Ledger described in
SPEC-v0.2 §3.2. Empty risk_accepted or compensating_control SHALL block
the override at the write path; this is not a discipline rule.

Stdlib only. Python 3.8 compatible.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, Union
import sqlite3


_CREATE_TABLE_SQL = """
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

-- INV-004 storage-level enforcement: SPEC-L2-S002 append-only.
-- Idempotent via IF NOT EXISTS. New in v0.9.
CREATE TRIGGER IF NOT EXISTS prevent_update_human_override
BEFORE UPDATE ON human_override
BEGIN
    SELECT RAISE(ABORT, 'INV-004: human_override is append-only per SPEC-L2-S002');
END;
"""


# Documented escalation paths. New in v0.9. SPEC-L8-S004 carry-forward:
# `escalation_path_taken` was previously free text. v0.9 documents the
# canonical set so a downstream auditor can rely on a stable taxonomy
# for reporting. Any other string is accepted but prefixed with
# `custom:` so it is visibly outside the canonical set.
_CANONICAL_ESCALATION_PATHS = (
    "none recorded",
    "peer_review",
    "director_signoff",
    "executive_signoff",
    "cabinet_office",
    "legal_review",
    "second_coder_review",
    "external_auditor",
)


@dataclass(frozen=True)
class HumanOverride:
    """A structured human override of a Layer 7 gate verdict.

    Per SPEC-L8-S004 the rationale fields risk_accepted and
    compensating_control SHALL be non-empty. The dataclass enforces only
    the runtime guarantee that values are stored as provided; the
    non-empty validation runs at record_override() time so the write
    pathway is the gate.
    """

    id: int
    ts: str
    run_id: str
    reviewer: str
    gate_id: str
    failure_class: str
    risk_accepted: str
    compensating_control: str
    escalation_path_taken: str
    single_actor: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "run_id": self.run_id,
            "reviewer": self.reviewer,
            "gate_id": self.gate_id,
            "failure_class": self.failure_class,
            "risk_accepted": self.risk_accepted,
            "compensating_control": self.compensating_control,
            "escalation_path_taken": self.escalation_path_taken,
            "single_actor": bool(self.single_actor),
        }


def open_override_db(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a read-write SQLite connection at db_path.

    Creates the parent directory if absent, opens the database (creating
    the file if needed), and applies the human_override CREATE TABLE IF
    NOT EXISTS schema. Caller owns the connection and SHALL close it.

    Distinct from provenance.ledger.open_ledger() which returns a
    read-only connection.
    """
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.executescript(_CREATE_TABLE_SQL)
    con.commit()
    return con


def record_override(
    db_path: Union[str, Path],
    *,
    run_id: str,
    reviewer: str,
    gate_id: str,
    failure_class: str,
    risk_accepted: str,
    compensating_control: str,
    escalation_path_taken: str = "none recorded",
    single_actor: bool = False,
    ts: Optional[str] = None,
) -> HumanOverride:
    """Record a human override.

    SPEC-L8-S004 normative: risk_accepted and compensating_control SHALL
    be non-empty. Empty or whitespace-only values raise ValueError and
    write no row. The override does not exist if it cannot be recorded.

    Parameters
    ----------
    db_path
        Path to the SQLite override ledger.
    run_id
        WarrantOS run identifier this override applies to.
    reviewer
        Identity string of the human who approved the override.
        Identity scheme is implementation-declared (user name, API key
        id, agent identifier, tuple).
    gate_id
        Which Layer 7 gate failed (one of "G1", "G2", "G3", "G4", "G5").
    failure_class
        The verdict that fired (e.g. "boundary", "unsupported",
        "contradicted", "requires_external_grounding").
    risk_accepted
        Free text. SHALL be non-empty.
    compensating_control
        Free text describing the mitigation. SHALL be non-empty.
    escalation_path_taken
        Free text. MAY be "none recorded" but the column is non-null.
    single_actor
        True if reviewer == writer-pack actor for the same run_id
        (SPEC-L8-S003). When True, the artefact role SHALL have been
        downgraded out of final-prose by the caller before this row is
        written; see enforce_single_actor_rule().
    ts
        Optional ISO-8601 UTC timestamp. Defaults to current UTC.

    Returns
    -------
    HumanOverride
        The persisted row with assigned id.

    Raises
    ------
    ValueError
        If any of risk_accepted, compensating_control, reviewer,
        gate_id, failure_class, or run_id is empty or whitespace.
    """
    _require_non_empty("risk_accepted", risk_accepted, "SPEC-L8-S004")
    _require_non_empty("compensating_control", compensating_control, "SPEC-L8-S004")
    _require_non_empty("reviewer", reviewer)
    _require_non_empty("gate_id", gate_id)
    _require_non_empty("failure_class", failure_class)
    _require_non_empty("run_id", run_id)

    if ts is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    risk_clean = risk_accepted.strip()
    control_clean = compensating_control.strip()
    escalation_clean = (escalation_path_taken or "none recorded").strip() or "none recorded"
    # v0.9: tag custom escalation paths so the downstream taxonomy is
    # honest. Anything outside the canonical set is recorded verbatim
    # with a `custom:` prefix.
    if escalation_clean not in _CANONICAL_ESCALATION_PATHS and not escalation_clean.startswith("custom:"):
        escalation_clean = "custom:" + escalation_clean

    con = open_override_db(db_path)
    try:
        cur = con.execute(
            "INSERT INTO human_override ("
            " ts, run_id, reviewer, gate_id, failure_class,"
            " risk_accepted, compensating_control,"
            " escalation_path_taken, single_actor"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                run_id.strip(),
                reviewer.strip(),
                gate_id.strip(),
                failure_class.strip(),
                risk_clean,
                control_clean,
                escalation_clean,
                1 if single_actor else 0,
            ),
        )
        new_id = cur.lastrowid
        con.commit()
    finally:
        con.close()

    return HumanOverride(
        id=int(new_id) if new_id is not None else -1,
        ts=ts,
        run_id=run_id.strip(),
        reviewer=reviewer.strip(),
        gate_id=gate_id.strip(),
        failure_class=failure_class.strip(),
        risk_accepted=risk_clean,
        compensating_control=control_clean,
        escalation_path_taken=escalation_clean,
        single_actor=bool(single_actor),
    )


def enforce_single_actor_rule(
    reviewer_identity: str,
    writer_pack_actor: str,
    *,
    artefact_role: str,
) -> Tuple[bool, str]:
    """Apply SPEC-L8-S003: reviewer SHALL be distinct from the
    compose_writer_pack actor for the same run_id, OR single_actor=True
    and the artefact role SHALL be downgraded from final-prose.

    Returns
    -------
    (single_actor, effective_role)
        single_actor is True when reviewer_identity case-insensitively
        equals writer_pack_actor. effective_role is the role the caller
        SHALL use to ship the artefact: when single_actor is True and
        the requested role was "final-prose" the effective role is
        "draft" (downgrade). For non-final-prose roles the effective
        role is unchanged because they do not carry the final-prose
        reputational commitment SPEC-L8-S005 requires.

    Raises
    ------
    ValueError
        If reviewer_identity or writer_pack_actor is empty.
    """
    _require_non_empty("reviewer_identity", reviewer_identity)
    _require_non_empty("writer_pack_actor", writer_pack_actor)
    _require_non_empty("artefact_role", artefact_role)

    same_actor = reviewer_identity.strip().lower() == writer_pack_actor.strip().lower()
    if same_actor and artefact_role.strip().lower() == "final-prose":
        return (True, "draft")
    return (same_actor, artefact_role)


def get_override_by_id(
    db_path: Union[str, Path], override_id: int
) -> Optional[HumanOverride]:
    """Retrieve an override by its primary-key id, or None if missing."""
    p = Path(db_path)
    if not p.is_file():
        return None
    con = sqlite3.connect(str(p))
    try:
        row = con.execute(
            "SELECT id, ts, run_id, reviewer, gate_id, failure_class,"
            " risk_accepted, compensating_control, escalation_path_taken,"
            " single_actor FROM human_override WHERE id = ?",
            (override_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return _row_to_override(row)


def list_overrides_for_run(
    db_path: Union[str, Path], run_id: str
) -> List[HumanOverride]:
    """List every override recorded for the given run_id, in insertion order."""
    p = Path(db_path)
    if not p.is_file():
        return []
    con = sqlite3.connect(str(p))
    try:
        rows = con.execute(
            "SELECT id, ts, run_id, reviewer, gate_id, failure_class,"
            " risk_accepted, compensating_control, escalation_path_taken,"
            " single_actor FROM human_override WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
    finally:
        con.close()
    return [_row_to_override(r) for r in rows]


def list_canonical_escalation_paths() -> List[str]:
    """Return the documented escalation path taxonomy.

    New in v0.9. Useful for callers building UI or validation around
    the override-recording surface.
    """
    return list(_CANONICAL_ESCALATION_PATHS)


def _require_non_empty(name: str, value: str, spec: str = "") -> None:
    if value is None or not str(value).strip():
        prefix = "%s: " % spec if spec else ""
        raise ValueError("%s%s SHALL be a non-empty string" % (prefix, name))


def _row_to_override(row) -> HumanOverride:
    return HumanOverride(
        id=int(row[0]),
        ts=row[1],
        run_id=row[2],
        reviewer=row[3],
        gate_id=row[4],
        failure_class=row[5],
        risk_accepted=row[6],
        compensating_control=row[7],
        escalation_path_taken=row[8],
        single_actor=bool(row[9]),
    )
