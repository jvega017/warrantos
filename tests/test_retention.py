#!/usr/bin/env python3
"""Tests for provenance.retention (F-retention as append-only tombstones).

All tests use a temporary on-disk SQLite database. No network, no sleeps.
The central invariant under test: retention NEVER hard-deletes a ledger row;
expiry is recorded as an additive tombstone, and both the tombstone ledger
and the retention_window override table are append-only.
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from warrantos.provenance import retention


def _utc(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class _RetentionDBTest(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db", prefix="pv_retention_")
        os.close(fd)
        # Fresh file; open_retention_db creates the schema. Seed runs.
        self.con = retention.open_retention_db(self.db)

    def tearDown(self):
        try:
            self.con.close()
        except Exception:
            pass
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _insert_run(self, ts: str, retention_window_days=None) -> int:
        cur = self.con.execute(
            "INSERT INTO provenance_run "
            "(ts, session_id, source_event, file_path, mode, total, supported, "
            " tagged, unsupported, retention_window_days) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, "sess", "Stop", None, "report", 0, 0, 0, 0, retention_window_days),
        )
        self.con.commit()
        return cur.lastrowid


class TestSchema(_RetentionDBTest):
    def test_provenance_run_has_retention_column(self):
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(provenance_run)")}
        self.assertIn("retention_window_days", cols)

    def test_tombstone_table_exists(self):
        names = {
            r[0] for r in self.con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("provenance_tombstone", names)
        self.assertIn("retention_window", names)


class TestSetWindow(_RetentionDBTest):
    def test_set_window_records_override_without_updating_run(self):
        run_id = self._insert_run(_utc(0), retention_window_days=None)
        retention.set_window(self.db, run_id, 30)
        # provenance_run column unchanged (append-only); override holds 30.
        self.assertEqual(retention.effective_window(self.con, run_id), 30)
        col = self.con.execute(
            "SELECT retention_window_days FROM provenance_run WHERE id=?",
            (run_id,),
        ).fetchone()[0]
        self.assertIsNone(col)

    def test_latest_override_wins(self):
        run_id = self._insert_run(_utc(0))
        retention.set_window(self.db, run_id, 30)
        retention.set_window(self.db, run_id, 7)
        self.assertEqual(retention.effective_window(self.con, run_id), 7)

    def test_column_default_used_when_no_override(self):
        run_id = self._insert_run(_utc(0), retention_window_days=90)
        self.assertEqual(retention.effective_window(self.con, run_id), 90)

    def test_negative_window_rejected(self):
        run_id = self._insert_run(_utc(0))
        with self.assertRaises(ValueError):
            retention.set_window(self.db, run_id, -1)

    def test_none_window_means_indefinite(self):
        run_id = self._insert_run(_utc(0), retention_window_days=10)
        retention.set_window(self.db, run_id, None)
        self.assertIsNone(retention.effective_window(self.con, run_id))


class TestListExpired(_RetentionDBTest):
    def test_run_past_window_is_expired(self):
        run_id = self._insert_run(_utc(40), retention_window_days=30)
        expired = retention.list_expired(self.db)
        self.assertEqual([e.run_id for e in expired], [run_id])

    def test_run_within_window_not_expired(self):
        self._insert_run(_utc(10), retention_window_days=30)
        self.assertEqual(retention.list_expired(self.db), [])

    def test_indefinite_run_never_expires(self):
        self._insert_run(_utc(1000), retention_window_days=None)
        self.assertEqual(retention.list_expired(self.db), [])

    def test_tombstoned_run_excluded(self):
        run_id = self._insert_run(_utc(40), retention_window_days=30)
        retention.tombstone_run(self.db, run_id)
        self.assertEqual(retention.list_expired(self.db), [])

    def test_override_changes_expiry(self):
        # 365-day default would not expire a 40-day-old run, but a 7-day
        # override does.
        run_id = self._insert_run(_utc(40), retention_window_days=365)
        self.assertEqual(retention.list_expired(self.db), [])
        retention.set_window(self.db, run_id, 7)
        self.assertEqual([e.run_id for e in retention.list_expired(self.db)], [run_id])


class TestTombstone(_RetentionDBTest):
    def test_tombstone_appends_row_and_preserves_run(self):
        run_id = self._insert_run(_utc(40), retention_window_days=30)
        tomb = retention.tombstone_run(self.db, run_id)
        self.assertEqual(tomb.run_id, run_id)
        self.assertEqual(tomb.reason, "retention_window_elapsed")
        # The underlying run row is STILL present: no hard delete.
        row = self.con.execute(
            "SELECT COUNT(*) FROM provenance_run WHERE id=?", (run_id,)
        ).fetchone()
        self.assertEqual(row[0], 1)

    def test_tombstone_backfills_window_snapshot(self):
        run_id = self._insert_run(_utc(40), retention_window_days=30)
        tomb = retention.tombstone_run(self.db, run_id)
        self.assertEqual(tomb.retention_window_days, 30)
        self.assertIsNotNone(tomb.expired_after)

    def test_empty_reason_rejected(self):
        run_id = self._insert_run(_utc(40), retention_window_days=30)
        with self.assertRaises(ValueError):
            retention.tombstone_run(self.db, run_id, reason="   ")

    def test_list_tombstones_returns_appended(self):
        r1 = self._insert_run(_utc(40), retention_window_days=30)
        r2 = self._insert_run(_utc(50), retention_window_days=30)
        retention.tombstone_run(self.db, r1)
        retention.tombstone_run(self.db, r2, reason="manual_retire")
        tombs = retention.list_tombstones(self.db)
        self.assertEqual([t.run_id for t in tombs], [r1, r2])
        self.assertEqual(tombs[1].reason, "manual_retire")


class TestAppendOnlyTombstone(_RetentionDBTest):
    def test_tombstone_update_blocked(self):
        run_id = self._insert_run(_utc(40), retention_window_days=30)
        retention.tombstone_run(self.db, run_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "UPDATE provenance_tombstone SET reason='x' WHERE run_id=?",
                (run_id,),
            )

    def test_tombstone_delete_blocked(self):
        run_id = self._insert_run(_utc(40), retention_window_days=30)
        retention.tombstone_run(self.db, run_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "DELETE FROM provenance_tombstone WHERE run_id=?", (run_id,)
            )

    def test_retention_window_update_blocked(self):
        run_id = self._insert_run(_utc(0))
        retention.set_window(self.db, run_id, 30)
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "UPDATE retention_window SET retention_window_days=1 WHERE run_id=?",
                (run_id,),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
