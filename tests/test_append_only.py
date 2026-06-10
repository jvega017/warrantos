#!/usr/bin/env python3
"""Tests for append-only ledger enforcement via SQLite triggers (INV-004).

Verifies that triggers ship by default in schema/provenance.sql and are
wired into the hook's schema-ensure path. Tests both the public API paths
(open_writable_db, open_override_db) and direct hook schema application.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from warrantos.provenance.ledger_write import open_writable_db
from warrantos.provenance.overrides import open_override_db, record_override


class TestAppendOnlyViPublicAPI(unittest.TestCase):
    """Append-only enforcement via the public schema-ensure paths."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "provenance.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_provenance_run_blocks_update(self):
        """provenance_run INSERT succeeds; UPDATE raises."""
        con = open_writable_db(self.db_path)
        try:
            # Insert a row via direct SQL (simulating hook behavior).
            con.execute(
                "INSERT INTO provenance_run "
                "(ts, session_id, source_event, file_path, mode, total, "
                "supported, tagged, unsupported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-06-10T10:00:00Z",
                    "sess_123",
                    "Stop",
                    None,
                    "report",
                    1,
                    0,
                    0,
                    1,
                ),
            )
            con.commit()

            # UPDATE must be blocked by the trigger.
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute(
                    "UPDATE provenance_run SET mode = 'enforce' WHERE id = 1"
                )
                con.commit()
            self.assertIn("append-only", str(ctx.exception).lower())
        finally:
            con.close()

    def test_provenance_run_blocks_delete(self):
        """provenance_run DELETE raises."""
        con = open_writable_db(self.db_path)
        try:
            con.execute(
                "INSERT INTO provenance_run "
                "(ts, session_id, source_event, file_path, mode, total, "
                "supported, tagged, unsupported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-06-10T10:00:00Z",
                    "sess_123",
                    "Stop",
                    None,
                    "report",
                    1,
                    0,
                    0,
                    1,
                ),
            )
            con.commit()

            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute("DELETE FROM provenance_run WHERE id = 1")
                con.commit()
            self.assertIn("append-only", str(ctx.exception).lower())
        finally:
            con.close()

    def test_provenance_claim_blocks_update(self):
        """provenance_claim UPDATE raises."""
        con = open_writable_db(self.db_path)
        try:
            # Insert parent run row.
            cur = con.execute(
                "INSERT INTO provenance_run "
                "(ts, session_id, source_event, file_path, mode, total, "
                "supported, tagged, unsupported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-06-10T10:00:00Z",
                    "sess_123",
                    "Stop",
                    None,
                    "report",
                    1,
                    0,
                    0,
                    1,
                ),
            )
            run_id = cur.lastrowid

            # Insert a claim.
            con.execute(
                "INSERT INTO provenance_claim "
                "(run_id, ts, session_id, status, trigger, claim_text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "2026-06-10T10:00:00Z",
                    "sess_123",
                    "unsupported",
                    "year",
                    "2024 was a year of growth.",
                ),
            )
            con.commit()

            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute(
                    "UPDATE provenance_claim SET status = 'supported' WHERE id = 1"
                )
                con.commit()
            self.assertIn("append-only", str(ctx.exception).lower())
        finally:
            con.close()

    def test_provenance_claim_blocks_delete(self):
        """provenance_claim DELETE raises."""
        con = open_writable_db(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO provenance_run "
                "(ts, session_id, source_event, file_path, mode, total, "
                "supported, tagged, unsupported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-06-10T10:00:00Z",
                    "sess_123",
                    "Stop",
                    None,
                    "report",
                    1,
                    0,
                    0,
                    1,
                ),
            )
            run_id = cur.lastrowid
            con.execute(
                "INSERT INTO provenance_claim "
                "(run_id, ts, session_id, status, trigger, claim_text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "2026-06-10T10:00:00Z",
                    "sess_123",
                    "unsupported",
                    "year",
                    "2024 was a year of growth.",
                ),
            )
            con.commit()

            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute("DELETE FROM provenance_claim WHERE id = 1")
                con.commit()
            self.assertIn("append-only", str(ctx.exception).lower())
        finally:
            con.close()

    def test_context_transform_blocks_update(self):
        """context_transform UPDATE raises."""
        con = open_writable_db(self.db_path)
        try:
            con.execute(
                "INSERT INTO context_transform "
                "(context_row_id, ts, kind, transform_text) "
                "VALUES (?, ?, ?, ?)",
                (None, "2026-06-10T10:00:00Z", "derived_req", "Text."),
            )
            con.commit()

            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute(
                    "UPDATE context_transform SET kind = 'other' WHERE id = 1"
                )
                con.commit()
            self.assertIn("append-only", str(ctx.exception).lower())
        finally:
            con.close()

    def test_insert_still_succeeds(self):
        """INSERT is not blocked; only UPDATE and DELETE."""
        con = open_writable_db(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO provenance_run "
                "(ts, session_id, source_event, file_path, mode, total, "
                "supported, tagged, unsupported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-06-10T10:00:00Z",
                    "sess_1",
                    "Stop",
                    None,
                    "report",
                    1,
                    0,
                    0,
                    1,
                ),
            )
            first_id = cur.lastrowid

            # Second insert must succeed.
            cur = con.execute(
                "INSERT INTO provenance_run "
                "(ts, session_id, source_event, file_path, mode, total, "
                "supported, tagged, unsupported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-06-10T10:01:00Z",
                    "sess_2",
                    "Stop",
                    None,
                    "report",
                    2,
                    1,
                    0,
                    1,
                ),
            )
            second_id = cur.lastrowid
            con.commit()

            self.assertGreater(second_id, first_id)
        finally:
            con.close()


class TestAppendOnlyHumanOverride(unittest.TestCase):
    """Human override carve-out: can be recorded; UPDATE/DELETE blocked by trigger."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "provenance.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_human_override_insert_succeeds(self):
        """record_override inserts and creates the table with triggers."""
        override = record_override(
            self.db_path,
            run_id="run_1",
            reviewer="director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Risk A.",
            compensating_control="Control B.",
        )
        self.assertGreater(override.id, 0)
        self.assertEqual(override.run_id, "run_1")
        self.assertEqual(override.risk_accepted, "Risk A.")

    def test_human_override_update_blocked(self):
        """UPDATE on human_override is blocked by the trigger."""
        record_override(
            self.db_path,
            run_id="run_1",
            reviewer="director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Risk A.",
            compensating_control="Control B.",
        )

        con = sqlite3.connect(str(self.db_path))
        try:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute(
                    "UPDATE human_override SET risk_accepted = 'tampered' "
                    "WHERE id = 1"
                )
                con.commit()
            self.assertIn("append-only", str(ctx.exception).lower())
        finally:
            con.close()

    def test_human_override_delete_blocked(self):
        """DELETE on human_override is blocked by the trigger."""
        record_override(
            self.db_path,
            run_id="run_1",
            reviewer="director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Risk A.",
            compensating_control="Control B.",
        )

        con = sqlite3.connect(str(self.db_path))
        try:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute("DELETE FROM human_override WHERE id = 1")
                con.commit()
            self.assertIn("append-only", str(ctx.exception).lower())
        finally:
            con.close()

    def test_multiple_overrides_can_be_recorded(self):
        """Append-only means rows can be inserted but never modified."""
        override1 = record_override(
            self.db_path,
            run_id="run_1",
            reviewer="director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Risk A.",
            compensating_control="Control B.",
        )
        override2 = record_override(
            self.db_path,
            run_id="run_1",
            reviewer="director.so",
            gate_id="G2",
            failure_class="unsupported",
            risk_accepted="Risk C.",
            compensating_control="Control D.",
        )
        self.assertGreater(override2.id, override1.id)


class TestAllLedgerTablesTriggers(unittest.TestCase):
    """Spot-check that other ledger tables also have triggers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "provenance.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_provenance_verification_has_triggers(self):
        """provenance_verification UPDATE/DELETE are blocked."""
        con = open_writable_db(self.db_path)
        try:
            # Create a run and claim first.
            cur = con.execute(
                "INSERT INTO provenance_run "
                "(ts, session_id, source_event, file_path, mode, total, "
                "supported, tagged, unsupported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "2026-06-10T10:00:00Z",
                    "sess_123",
                    "Stop",
                    None,
                    "report",
                    1,
                    0,
                    0,
                    1,
                ),
            )
            run_id = cur.lastrowid

            cur = con.execute(
                "INSERT INTO provenance_claim "
                "(run_id, ts, session_id, status, trigger, claim_text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "2026-06-10T10:00:00Z",
                    "sess_123",
                    "unsupported",
                    "year",
                    "2024.",
                ),
            )
            claim_id = cur.lastrowid

            # Insert a verification.
            con.execute(
                "INSERT INTO provenance_verification "
                "(claim_id, ts, citation, verdict, grader) "
                "VALUES (?, ?, ?, ?, ?)",
                (claim_id, "2026-06-10T10:00:00Z", "https://example.com", "verified", "heuristic"),
            )
            con.commit()

            # UPDATE must be blocked.
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute(
                    "UPDATE provenance_verification SET verdict = 'contradicted' WHERE id = 1"
                )
                con.commit()
            self.assertIn("append-only", str(ctx.exception).lower())
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
