#!/usr/bin/env python3
"""Tests for provenance.ledger_write (L3 persistence + INV-004 triggers)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from provenance.context_admissibility import classify_context, derive_requirement
from provenance.ledger_write import (
    enable_append_only_triggers,
    list_append_only_tables,
    list_context_transforms,
    open_writable_db,
    persist_context_transform,
)
from provenance.overrides import record_override


class TestPersistContextTransform(unittest.TestCase):
    """SPEC-L3-N001 closure: derive_requirement output round-trips
    through the context_transform table."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "provenance.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_persists_derived_requirement_and_returns_id(self):
        item = classify_context("ctx_fb", "This is not commercial enough.")
        req = derive_requirement(item)
        new_id = persist_context_transform(
            self.db_path,
            requirement=req,
            run_id="run_l3_demo",
        )
        self.assertGreater(new_id, 0)

        rows = list_context_transforms(self.db_path, run_id="run_l3_demo")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], req.kind)
        self.assertEqual(rows[0]["transform_text"], req.text)

    def test_list_with_no_filter_returns_all_rows(self):
        item = classify_context("ctx_s", "Source: report.pdf, 2026.")
        req = derive_requirement(item)
        persist_context_transform(self.db_path, requirement=req, run_id="r1")
        persist_context_transform(self.db_path, requirement=req, run_id="r2")
        self.assertEqual(len(list_context_transforms(self.db_path)), 2)

    def test_missing_db_returns_empty_list(self):
        self.assertEqual(
            list_context_transforms(self._tmp.name + "/absent.db"), []
        )


class TestAppendOnlyTriggers(unittest.TestCase):
    """INV-004 ENFORCED at storage: UPDATE on audit-bearing tables raises."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "provenance.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_trigger_blocks_update_on_human_override(self):
        # First write an override row (this also creates the table).
        record_override(
            self.db_path,
            run_id="run_trigger_test",
            reviewer="human:director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Test risk.",
            compensating_control="Test control.",
        )

        # Install the triggers AFTER the table exists.
        count = enable_append_only_triggers(self.db_path)
        self.assertGreaterEqual(count, 1)

        # Now an UPDATE should raise.
        con = sqlite3.connect(str(self.db_path))
        try:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute(
                    "UPDATE human_override SET risk_accepted = 'tampered' "
                    "WHERE id = 1"
                )
                con.commit()
            self.assertIn("INV-004", str(ctx.exception))
            self.assertIn("human_override", str(ctx.exception))
        finally:
            con.close()

    def test_trigger_blocks_delete_on_human_override(self):
        # Write an override row (also creates the table), then install triggers.
        record_override(
            self.db_path,
            run_id="run_delete_test",
            reviewer="human:director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Test risk.",
            compensating_control="Test control.",
        )
        count = enable_append_only_triggers(self.db_path)
        self.assertGreaterEqual(count, 1)

        # A DELETE must be rejected: append-only means rows cannot be removed,
        # which is as damaging to a tamper-evident ledger as an UPDATE.
        con = sqlite3.connect(str(self.db_path))
        try:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                con.execute("DELETE FROM human_override WHERE id = 1")
                con.commit()
            self.assertIn("INV-004", str(ctx.exception))
            self.assertIn("human_override", str(ctx.exception))
        finally:
            con.close()

    def test_trigger_does_not_block_insert(self):
        record_override(
            self.db_path,
            run_id="run_insert_test",
            reviewer="human:director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="A.",
            compensating_control="B.",
        )
        enable_append_only_triggers(self.db_path)
        # A second INSERT must still succeed.
        second = record_override(
            self.db_path,
            run_id="run_insert_test",
            reviewer="human:director.so",
            gate_id="G2",
            failure_class="unsupported",
            risk_accepted="C.",
            compensating_control="D.",
        )
        self.assertGreater(second.id, 0)

    def test_idempotent_returns_same_count_twice(self):
        record_override(
            self.db_path,
            run_id="r1",
            reviewer="x",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="A",
            compensating_control="B",
        )
        first = enable_append_only_triggers(self.db_path)
        second = enable_append_only_triggers(self.db_path)
        self.assertEqual(first, second)

    def test_missing_db_returns_zero(self):
        self.assertEqual(
            enable_append_only_triggers(self._tmp.name + "/absent.db"), 0
        )


class TestListAppendOnlyTables(unittest.TestCase):

    def test_human_override_is_in_the_list(self):
        tables = list_append_only_tables()
        self.assertIn("human_override", tables)
        self.assertIn("context_transform", tables)


if __name__ == "__main__":
    unittest.main(verbosity=2)
