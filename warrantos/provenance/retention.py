"""provenance.retention: F-retention as append-only tombstones (INV-011).

Retention in WarrantOS is implemented WITHOUT hard delete. The ledger is
append-only (INV-004 / SPEC-L2-S002); a retention policy that physically
removed rows would destroy the audit trail it exists to protect. Instead:

- A retention window is a per-run number of days. The window can be set at
  run-creation time (the ``retention_window_days`` column on
  ``provenance_run``) or recorded later via :func:`set_window`, which appends
  an immutable row to the ``retention_window`` side table (latest row wins).
  The column itself is never UPDATEd, so the provenance_run append-only
  trigger is never tripped.
- When a run's effective window has elapsed, :func:`tombstone_run` appends a
  row to ``provenance_tombstone``. The tombstone is an ADDITIVE marker that
  the run is logically expired. The run's ledger rows are preserved. The
  tombstone ledger is itself append-only.
- :func:`list_expired` computes which non-tombstoned runs have passed their
  effective window so an operator (or a scheduled job) can decide to
  tombstone them. It performs no writes.

A reader treats a run as retired when a tombstone exists for it; the data
stays on disk for integrity and re-verification.

Stdlib only (sqlite3, datetime). Python 3.8 compatible.
Australian English throughout.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Union


# ---------------------------------------------------------------------------
# Schema (idempotent; mirrors schema/provenance.sql)
# ---------------------------------------------------------------------------

# The retention_window side table holds per-run window overrides recorded
# AFTER run creation. It is append-only: set_window() always inserts, and the
# latest row (highest id) is the effective override. This keeps the
# provenance_run row immutable and the change history auditable.
_RETENTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS retention_window (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT    NOT NULL,
    run_id                INTEGER NOT NULL,
    retention_window_days INTEGER
);

CREATE INDEX IF NOT EXISTS idx_retention_window_run ON retention_window(run_id);

CREATE TRIGGER IF NOT EXISTS trg_retention_window_no_update
BEFORE UPDATE ON retention_window
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_retention_window_no_delete
BEFORE DELETE ON retention_window
BEGIN
    SELECT RAISE(ABORT, 'append-only ledger: DELETE forbidden');
END;

CREATE TABLE IF NOT EXISTS provenance_tombstone (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT    NOT NULL,
    run_id                INTEGER NOT NULL,
    reason                TEXT    NOT NULL,
    retention_window_days INTEGER,
    expired_after         TEXT
);

CREATE INDEX IF NOT EXISTS idx_tombstone_run ON provenance_tombstone(run_id);

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
"""

_PROVENANCE_RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_run (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT    NOT NULL,
    session_id            TEXT,
    source_event          TEXT,
    file_path             TEXT,
    mode                  TEXT    NOT NULL,
    total                 INTEGER NOT NULL,
    supported             INTEGER NOT NULL,
    tagged                INTEGER NOT NULL,
    unsupported           INTEGER NOT NULL,
    retention_window_days INTEGER
);
"""


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 UTC timestamp leniently. Returns None on failure."""
    if not ts:
        return None
    text = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # Fall back to a date-only or space-separated form.
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(ts.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def open_retention_db(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a read-write connection and ensure the retention schema exists.

    Creates the parent directory if absent and applies the retention_window
    and provenance_tombstone schema (and a tolerant provenance_run create so
    the side tables have something to reference even on a fresh DB). The
    caller owns the connection and SHALL close it.
    """
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.executescript(_PROVENANCE_RUN_SCHEMA)
    con.executescript(_RETENTION_SCHEMA)
    con.commit()
    return con


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExpiredRun:
    """A run whose effective retention window has elapsed and which carries
    no tombstone yet."""

    run_id: int
    ts: str
    retention_window_days: int
    expired_after: str

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "ts": self.ts,
            "retention_window_days": self.retention_window_days,
            "expired_after": self.expired_after,
        }


@dataclass(frozen=True)
class Tombstone:
    """An append-only marker that a run is logically retired."""

    id: int
    ts: str
    run_id: int
    reason: str
    retention_window_days: Optional[int]
    expired_after: Optional[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "run_id": self.run_id,
            "reason": self.reason,
            "retention_window_days": self.retention_window_days,
            "expired_after": self.expired_after,
        }


# ---------------------------------------------------------------------------
# Effective-window resolution
# ---------------------------------------------------------------------------

def effective_window(con: sqlite3.Connection, run_id: int) -> Optional[int]:
    """Return the effective retention window (days) for a run, or None.

    Precedence: the most recent retention_window override row wins; otherwise
    the provenance_run.retention_window_days column. None means "keep
    indefinitely" (no retention policy applies).
    """
    row = con.execute(
        "SELECT retention_window_days FROM retention_window "
        "WHERE run_id = ? ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is not None:
        return row[0]
    row = con.execute(
        "SELECT retention_window_days FROM provenance_run WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is not None:
        return row[0]
    return None


# ---------------------------------------------------------------------------
# set_window
# ---------------------------------------------------------------------------

def set_window(
    db_path: Union[str, Path],
    run_id: int,
    retention_window_days: Optional[int],
    *,
    ts: Optional[str] = None,
) -> None:
    """Record a retention window for a run by APPENDING an override row.

    The provenance_run row is never UPDATEd (it is append-only); the window
    is recorded in the retention_window side table and the latest row wins.
    Pass ``retention_window_days=None`` to record "keep indefinitely".

    Raises ValueError on a negative window.
    """
    if retention_window_days is not None and retention_window_days < 0:
        raise ValueError("retention_window_days must be >= 0 or None")
    con = open_retention_db(db_path)
    try:
        con.execute(
            "INSERT INTO retention_window (ts, run_id, retention_window_days) "
            "VALUES (?, ?, ?)",
            (ts or _now_utc(), run_id, retention_window_days),
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# list_expired
# ---------------------------------------------------------------------------

def list_expired(
    db_path: Union[str, Path],
    *,
    now: Optional[datetime] = None,
) -> List[ExpiredRun]:
    """Return runs whose effective window has elapsed and which carry no
    tombstone yet. Performs NO writes.

    A run is expired when it has an effective window of N days (N is not
    None) and its creation timestamp is more than N days before ``now``
    (default: current UTC). Runs already tombstoned are excluded.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    con = open_retention_db(db_path)
    try:
        tombstoned = {
            r[0] for r in con.execute(
                "SELECT DISTINCT run_id FROM provenance_tombstone"
            ).fetchall()
        }
        rows = con.execute(
            "SELECT id, ts FROM provenance_run ORDER BY id"
        ).fetchall()
        expired: List[ExpiredRun] = []
        for run_id, ts in rows:
            if run_id in tombstoned:
                continue
            window = effective_window(con, run_id)
            if window is None:
                continue
            created = _parse_ts(ts)
            if created is None:
                continue
            cutoff = created + timedelta(days=window)
            if now > cutoff:
                expired.append(ExpiredRun(
                    run_id=run_id,
                    ts=ts,
                    retention_window_days=window,
                    expired_after=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
                ))
        return expired
    finally:
        con.close()


# ---------------------------------------------------------------------------
# tombstone_run
# ---------------------------------------------------------------------------

def tombstone_run(
    db_path: Union[str, Path],
    run_id: int,
    *,
    reason: str = "retention_window_elapsed",
    retention_window_days: Optional[int] = None,
    expired_after: Optional[str] = None,
    ts: Optional[str] = None,
) -> Tombstone:
    """Append a tombstone for a run. NEVER deletes any ledger row.

    Idempotency is intentionally NOT enforced at the row level (the table is
    append-only and a second tombstone is a legitimate additive record), but
    callers that walk :func:`list_expired` will not see an already-tombstoned
    run again because list_expired filters tombstoned run_ids.

    When ``retention_window_days`` / ``expired_after`` are omitted they are
    backfilled from the run's effective window where available, so the
    tombstone is a self-describing snapshot.
    """
    if not reason or not reason.strip():
        raise ValueError("tombstone reason must be non-empty")
    con = open_retention_db(db_path)
    try:
        if retention_window_days is None:
            retention_window_days = effective_window(con, run_id)
        if expired_after is None and retention_window_days is not None:
            row = con.execute(
                "SELECT ts FROM provenance_run WHERE id = ?", (run_id,)
            ).fetchone()
            created = _parse_ts(row[0]) if row else None
            if created is not None:
                expired_after = (
                    created + timedelta(days=retention_window_days)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = con.execute(
            "INSERT INTO provenance_tombstone "
            "(ts, run_id, reason, retention_window_days, expired_after) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts or _now_utc(), run_id, reason.strip(),
             retention_window_days, expired_after),
        )
        con.commit()
        new_id = cur.lastrowid
    finally:
        con.close()
    return Tombstone(
        id=new_id,
        ts=ts or _now_utc(),
        run_id=run_id,
        reason=reason.strip(),
        retention_window_days=retention_window_days,
        expired_after=expired_after,
    )


def list_tombstones(db_path: Union[str, Path]) -> List[Tombstone]:
    """Return all tombstones in id order. Read-only."""
    con = open_retention_db(db_path)
    try:
        rows = con.execute(
            "SELECT id, ts, run_id, reason, retention_window_days, expired_after "
            "FROM provenance_tombstone ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    return [
        Tombstone(
            id=r[0], ts=r[1], run_id=r[2], reason=r[3],
            retention_window_days=r[4], expired_after=r[5],
        )
        for r in rows
    ]
