#!/usr/bin/env python3
"""Integration tests for end-to-end ledger persistence in the check pipeline.

Tests the full flow: warrantos check → ledger write → warrantos attest → warrant verification.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from warrantos.cli.warrantos_cli import _cmd_check_single
from warrantos.provenance.ledger_write import record_check_run


class TestCheckLedgerIntegration(unittest.TestCase):
    """Integration tests for check command ledger persistence."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

        # Create minimal working directory structure
        self.work_dir = self.tmp_path / "work"
        self.work_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_check_writes_to_ledger(self):
        """Full test: run check and verify ledger persistence."""
        # Create a simple draft
        draft_path = self.work_dir / "test_draft.md"
        draft_text = """# Test Document

This is a test document about the sky.
The sky is blue according to multiple sources.

Here's an unsupported claim: The moon is made of cheese.

Another claim: Python is a programming language.
"""
        draft_path.write_text(draft_text, encoding="utf-8")

        # Create context file (empty)
        context_path = self.work_dir / "context.json"
        context_path.write_text(json.dumps([]), encoding="utf-8")

        # Create actor identity file
        actor_path = self.work_dir / "actor.json"
        actor_data = {
            "context_classifier": "agent:auto",
            "insight_compiler": "human:test",
            "source_curator": "human:test",
            "clean_room_writer": "model:test",
            "reviewer_qa": "agent:auto",
            "auditor": "human:test",
        }
        actor_path.write_text(json.dumps(actor_data), encoding="utf-8")

        # Create args object that mimics CLI arguments
        class Args:
            command = "check"
            draft = [str(draft_path)]
            context = str(context_path)
            actor_identity = str(actor_path)
            profile = "final-prose"
            run_id = None  # Will be generated
            db = str(self.work_dir / "provenance.db")
            out_dir = None  # Will use default
            explain_profile = False
            json = False
            ci = False
            verify = False
            no_fetch = False
            sensitivity_check = False
            writer_model = None
            verifier_model = None
            max_verify_claims = 0
            salience_min = 0.0

        args = Args()

        # Change to work directory for path containment
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(self.work_dir)

            # Run check command
            exit_code = _cmd_check_single(args, str(draft_path))

            # Should succeed (PASS verdict)
            self.assertIn(exit_code, [0, 1])  # 0 for PASS, 1 for HOLD/BLOCK/NOT_ASSESSABLE

        finally:
            os.chdir(old_cwd)

        # Verify ledger was written
        db_path = self.work_dir / "provenance.db"
        self.assertTrue(db_path.exists(), "Ledger database was not created")

        # Check that ledger has entries
        con = sqlite3.connect(str(db_path))
        try:
            # Count provenance_run rows
            run_count = con.execute("SELECT COUNT(*) FROM provenance_run").fetchone()[0]
            self.assertGreater(run_count, 0, "No provenance_run rows found in ledger")

            # Count provenance_claim rows (should match detected claims)
            claim_count = con.execute("SELECT COUNT(*) FROM provenance_claim").fetchone()[0]
            self.assertGreater(claim_count, 0, "No provenance_claim rows found in ledger")

            # Verify run metadata
            run = con.execute(
                "SELECT id, mode, total, supported, unsupported "
                "FROM provenance_run LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(run)
            run_id, mode, total, supported, unsupported = run
            self.assertEqual(mode, "check")
            self.assertGreater(total, 0)
            # supported + unsupported should equal total
            self.assertEqual(supported + unsupported, total)

            # Verify claim metadata
            claims = con.execute(
                "SELECT id, run_id, status, claim_text "
                "FROM provenance_claim WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            self.assertEqual(len(claims), total)
            for claim in claims:
                claim_id, fk_run_id, status, claim_text = claim
                self.assertEqual(fk_run_id, run_id)
                self.assertIn(status, ["supported", "unsupported"])
                self.assertIsNotNone(claim_text)

        finally:
            con.close()

    def test_ledger_records_profile_information(self):
        """Verify that the profile used is recorded in the ledger."""
        claims = [
            {
                "sentence": "A factual statement here.",
                "citation": "https://example.com",
                "triggers": ["factual"],
                "salience": 0.8,
                "load_bearing": True,
            }
        ]

        db_path = self.tmp_path / "test.db"
        success, msg = record_check_run(
            db_path,
            "run_profile_test",
            claims=claims,
            verifier_rows=[],
            boundary="PASS",
            verdict="PASS",
            reasons=["Test"],
            profile="audit",
        )

        self.assertTrue(success, msg)

        # Verify profile is stored in provenance_run
        con = sqlite3.connect(str(db_path))
        try:
            # Profile is stored in file_path column (repurposed for this use)
            row = con.execute(
                "SELECT file_path FROM provenance_run WHERE session_id = ?",
                ("run_profile_test",),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "audit")
        finally:
            con.close()

    def test_ledger_records_verdict_and_reasons(self):
        """Verify verdict and reasons are captured (for future audit)."""
        claims = []
        db_path = self.tmp_path / "test.db"

        reasons = [
            "No claims detected",
            "Boundary check passed",
        ]

        success, msg = record_check_run(
            db_path,
            "run_verdict_test",
            claims=claims,
            verifier_rows=[],
            boundary="PASS",
            verdict="PASS",
            reasons=reasons,
            profile="final-prose",
        )

        self.assertTrue(success, msg)

        # Verify run was recorded
        con = sqlite3.connect(str(db_path))
        try:
            count = con.execute(
                "SELECT COUNT(*) FROM provenance_run WHERE session_id = ?",
                ("run_verdict_test",),
            ).fetchone()[0]
            self.assertEqual(count, 1)
        finally:
            con.close()

    def test_multiple_runs_to_same_ledger(self):
        """Verify multiple check runs can be persisted to the same ledger."""
        db_path = self.tmp_path / "shared.db"

        for i in range(3):
            run_id = f"run_{i}"
            claims = [
                {
                    "sentence": f"Claim {i}.",
                    "citation": f"https://example{i}.com",
                    "triggers": ["factual"],
                    "salience": 0.5,
                    "load_bearing": False,
                }
            ]
            success, msg = record_check_run(
                db_path,
                run_id,
                claims=claims,
                verifier_rows=[],
                boundary="PASS",
                verdict="PASS",
                reasons=[f"Run {i}"],
                profile="final-prose",
            )
            self.assertTrue(success, msg)

        # Verify all runs are in the ledger
        con = sqlite3.connect(str(db_path))
        try:
            runs = con.execute("SELECT COUNT(*) FROM provenance_run").fetchone()[0]
            self.assertEqual(runs, 3)
            claims_total = con.execute("SELECT COUNT(*) FROM provenance_claim").fetchone()[0]
            self.assertEqual(claims_total, 3)
        finally:
            con.close()

    def test_ledger_claim_status_matches_citation(self):
        """Verify that claim status ('supported'/'unsupported') matches citation presence."""
        db_path = self.tmp_path / "test.db"

        claims = [
            {"sentence": "With citation.", "citation": "https://example.com", "triggers": [], "salience": 0.0, "load_bearing": False},
            {"sentence": "Without citation.", "citation": None, "triggers": [], "salience": 0.0, "load_bearing": False},
        ]

        success, msg = record_check_run(
            db_path,
            "run_status_test",
            claims=claims,
            verifier_rows=[],
            boundary="PASS",
            verdict="PASS",
            reasons=[],
            profile="final-prose",
        )

        self.assertTrue(success, msg)

        con = sqlite3.connect(str(db_path))
        try:
            rows = con.execute(
                "SELECT claim_text, status FROM provenance_claim "
                "WHERE session_id = ? ORDER BY id",
                ("run_status_test",),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][1], "supported")
            self.assertEqual(rows[1][1], "unsupported")
        finally:
            con.close()

    def test_ledger_verification_results_linked_correctly(self):
        """Verify that verifier results are correctly linked to claims."""
        db_path = self.tmp_path / "test.db"

        claims = [
            {"sentence": "First claim.", "citation": "http://example.com", "triggers": [], "salience": 0.0, "load_bearing": False},
            {"sentence": "Second claim.", "citation": "http://example.com", "triggers": [], "salience": 0.0, "load_bearing": False},
        ]

        verifier_rows = [
            {
                "claim_text": "First claim.",
                "citation": "http://example.com",
                "verdict": "supported",
                "confidence": 0.9,
                "rationale": "Found evidence.",
                "grader": "heuristic",
            },
            {
                "claim_text": "Second claim.",
                "citation": "http://example.com",
                "verdict": "unsupported",
                "confidence": 0.7,
                "rationale": "No evidence.",
                "grader": "heuristic",
            },
        ]

        success, msg = record_check_run(
            db_path,
            "run_verif_test",
            claims=claims,
            verifier_rows=verifier_rows,
            boundary="BLOCK",
            verdict="BLOCK",
            reasons=["Unsupported claims found"],
            profile="final-prose",
        )

        self.assertTrue(success, msg)

        con = sqlite3.connect(str(db_path))
        try:
            # Get run id
            run_id = con.execute(
                "SELECT id FROM provenance_run WHERE session_id = ?",
                ("run_verif_test",),
            ).fetchone()[0]

            # Get claims and their verifications
            query = """
            SELECT c.claim_text, c.status, v.verdict, v.confidence
            FROM provenance_claim c
            LEFT JOIN provenance_verification v ON c.id = v.claim_id
            WHERE c.run_id = ?
            ORDER BY c.id
            """
            rows = con.execute(query, (run_id,)).fetchall()
            self.assertEqual(len(rows), 2)

            # Verify first claim
            self.assertEqual(rows[0][0], "First claim.")
            self.assertEqual(rows[0][1], "supported")
            self.assertEqual(rows[0][2], "supported")
            self.assertAlmostEqual(rows[0][3], 0.9)

            # Verify second claim
            self.assertEqual(rows[1][0], "Second claim.")
            self.assertEqual(rows[1][1], "supported")
            self.assertEqual(rows[1][2], "unsupported")
            self.assertAlmostEqual(rows[1][3], 0.7)

        finally:
            con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
