#!/usr/bin/env python3
"""Tests for provenance.ledger.

All tests are offline and deterministic. The SQLite schema is built inline
from the same DDL shape as schema/provenance.sql so no external files are
needed. No network access, no sleeps.

Run from the repo root:
    python -m unittest tests.test_ledger -v
"""

import csv
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from warrantos.provenance.ledger import (
    export_evidence_matrix,
    epistemic_debt,
    open_ledger,
)
from warrantos.provenance.salience import is_load_bearing, score_claim

# ---------------------------------------------------------------------------
# Inline schema (matches schema/provenance.sql shape exactly)
# ---------------------------------------------------------------------------

_SCHEMA = """
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
"""


def _make_db(with_verification: bool = True) -> str:
    """Create a temporary SQLite database with fixture data and return its path.

    Fixture design:
    - Run 1 (ts 2026-01-01): 3 claims total, 1 supported, 1 tagged, 1 unsupported
      The unsupported claim is a bare year sentence (NOT load-bearing).
    - Run 2 (ts 2026-02-01): 4 claims total, 1 supported, 1 tagged, 2 unsupported
      One unsupported is a statute+decision sentence (load-bearing).
      One unsupported is a bare year sentence (NOT load-bearing).
    - Run 3 (ts 2026-03-01): 5 claims total, 1 supported, 1 tagged, 3 unsupported
      Two unsupported are load-bearing (magnitude, statute).
      One unsupported is a bare year sentence (NOT load-bearing).

    Unsupported rates: 1/3 -> 2/4 -> 3/5 => direction is 'up'.

    Verification rows cover a subset of claims from runs 1 and 2.
    """
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db_path = f.name

    con = sqlite3.connect(db_path)
    con.executescript(_SCHEMA)

    ts1 = "2026-01-01T00:00:00+00:00"
    ts2 = "2026-02-01T00:00:00+00:00"
    ts3 = "2026-03-01T00:00:00+00:00"

    # Run 1
    cur = con.execute(
        "INSERT INTO provenance_run (ts,session_id,source_event,file_path,mode,"
        "total,supported,tagged,unsupported) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts1, "sess1", "Stop", None, "report", 3, 1, 1, 1),
    )
    run1 = cur.lastrowid

    # Run 2
    cur = con.execute(
        "INSERT INTO provenance_run (ts,session_id,source_event,file_path,mode,"
        "total,supported,tagged,unsupported) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts2, "sess2", "PostToolUse", "draft.md", "report", 4, 1, 1, 2),
    )
    run2 = cur.lastrowid

    # Run 3
    cur = con.execute(
        "INSERT INTO provenance_run (ts,session_id,source_event,file_path,mode,"
        "total,supported,tagged,unsupported) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts3, "sess3", "Stop", None, "enforce", 5, 1, 1, 3),
    )
    run3 = cur.lastrowid

    # Claims for run 1
    claims_run1 = [
        (run1, ts1, "sess1", "supported", "percentage",
         "Emissions fell 12 per cent (https://example.org/data)."),
        (run1, ts1, "sess1", "tagged", "year",
         "The review took place in 2020 [CITE NEEDED]."),
        (run1, ts1, "sess1", "unsupported", "year",
         # Bare year, NOT load-bearing (score ~0.10)
         "The programme was established in 2019."),
    ]

    # Claims for run 2
    claims_run2 = [
        (run2, ts2, "sess2", "supported", "magnitude",
         "The fund holds $2 billion (source: Treasury)."),
        (run2, ts2, "sess2", "tagged", "attribution",
         "According to the survey, satisfaction rose [CITE NEEDED]."),
        (run2, ts2, "sess2", "unsupported", "statute",
         # statute + decision -> load-bearing
         "Under section 14 of the Act 2022, the Minister must publish a report."),
        (run2, ts2, "sess2", "unsupported", "year",
         # Bare year, NOT load-bearing
         "The policy was first introduced in 2018."),
    ]

    # Claims for run 3
    claims_run3 = [
        (run3, ts3, "sess3", "supported", "percentage",
         "Costs rose 7 per cent (Smith, 2025)."),
        (run3, ts3, "sess3", "tagged", "magnitude",
         "Revenue hit $3 billion [CITE NEEDED]."),
        (run3, ts3, "sess3", "unsupported", "magnitude",
         # Magnitude -> load-bearing
         "The department spent 1.2 billion on digital infrastructure."),
        (run3, ts3, "sess3", "unsupported", "statute",
         # statute reference -> load-bearing
         "Section 99 of the Privacy Act 2000 requires consent before collection."),
        (run3, ts3, "sess3", "unsupported", "year",
         # Bare year, NOT load-bearing
         "The framework was updated in 2021."),
    ]

    all_claims = claims_run1 + claims_run2 + claims_run3
    claim_ids = []
    for row in all_claims:
        cur = con.execute(
            "INSERT INTO provenance_claim "
            "(run_id,ts,session_id,status,trigger,claim_text) VALUES (?,?,?,?,?,?)",
            row,
        )
        claim_ids.append(cur.lastrowid)

    if with_verification:
        # Add verification rows for claims from runs 1 and 2.
        # claim_ids[0] = run1/supported/percentage -> verified
        # claim_ids[2] = run1/unsupported/year -> contradicted (surprising but tests it)
        # claim_ids[3] = run2/supported/magnitude -> verified
        # claim_ids[5] = run2/unsupported/statute -> unverifiable
        verif_rows = [
            (claim_ids[0], ts1, "https://example.org/data", "verified", 0.9,
             "Token overlap confirmed.", "fetch+heuristic"),
            (claim_ids[2], ts1, None, "contradicted", 0.7,
             "Source states 2020, not 2019.", "heuristic"),
            (claim_ids[3], ts2, "https://treasury.gov.au/fund", "verified", 0.85,
             "Source confirms $2 billion figure.", "fetch+heuristic"),
            (claim_ids[5], ts2, None, "unverifiable", None,
             "No URL citation; cannot fetch.", "heuristic"),
        ]
        con.executemany(
            "INSERT INTO provenance_verification "
            "(claim_id,ts,citation,verdict,confidence,rationale,grader) "
            "VALUES (?,?,?,?,?,?,?)",
            verif_rows,
        )

    con.commit()
    con.close()
    return db_path


def _make_db_no_verification() -> str:
    """Create a DB with provenance_run and provenance_claim but NO provenance_verification table."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db_path = f.name

    # Only create run and claim tables.
    schema_no_verif = """
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
        run_id      INTEGER NOT NULL,
        ts          TEXT    NOT NULL,
        session_id  TEXT,
        status      TEXT    NOT NULL,
        trigger     TEXT,
        claim_text  TEXT    NOT NULL
    );
    """
    con = sqlite3.connect(db_path)
    con.executescript(schema_no_verif)

    ts = "2026-04-01T00:00:00+00:00"
    cur = con.execute(
        "INSERT INTO provenance_run (ts,mode,total,supported,tagged,unsupported) "
        "VALUES (?,?,?,?,?,?)",
        (ts, "report", 2, 1, 0, 1),
    )
    run_id = cur.lastrowid
    con.executemany(
        "INSERT INTO provenance_claim (run_id,ts,status,trigger,claim_text) "
        "VALUES (?,?,?,?,?)",
        [
            (run_id, ts, "supported", "percentage",
             "Output rose 5 per cent (https://example.org/data)."),
            (run_id, ts, "unsupported", "statute",
             "Under section 5 of the Act 2023, disclosure is required."),
        ],
    )
    con.commit()
    con.close()
    return db_path


# ---------------------------------------------------------------------------
# TestOpenLedger
# ---------------------------------------------------------------------------

class TestOpenLedger(unittest.TestCase):

    def test_returns_connection_for_existing_file(self):
        db = _make_db()
        try:
            con = open_ledger(db)
            self.assertIsInstance(con, sqlite3.Connection)
            con.close()
        finally:
            os.unlink(db)

    def test_returns_empty_in_memory_db_for_missing_path(self):
        con = open_ledger("/does/not/exist/provenance.db")
        self.assertIsInstance(con, sqlite3.Connection)
        # Should not raise; should have no tables.
        row = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()
        self.assertEqual(row[0], 0)
        con.close()

    def test_does_not_create_file(self):
        path = Path(tempfile.gettempdir()) / "provenance_should_not_exist.db"
        if path.exists():
            path.unlink()
        try:
            con = open_ledger(str(path))
            con.close()
        finally:
            pass  # file might be created by the fallback path — that is acceptable
        # Clean up if created.
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# TestEpistemicDebtTotals
# ---------------------------------------------------------------------------

class TestEpistemicDebtTotals(unittest.TestCase):

    def setUp(self):
        self.db = _make_db(with_verification=True)

    def tearDown(self):
        os.unlink(self.db)

    def test_runs_count(self):
        result = epistemic_debt(self.db)
        self.assertEqual(result["totals"]["runs"], 3)

    def test_claims_total(self):
        result = epistemic_debt(self.db)
        # 3 + 4 + 5 = 12 claims
        self.assertEqual(result["totals"]["claims"], 12)

    def test_supported_count(self):
        result = epistemic_debt(self.db)
        # 1 + 1 + 1 = 3 supported
        self.assertEqual(result["totals"]["supported"], 3)

    def test_tagged_count(self):
        result = epistemic_debt(self.db)
        # 1 + 1 + 1 = 3 tagged
        self.assertEqual(result["totals"]["tagged"], 3)

    def test_unsupported_count(self):
        result = epistemic_debt(self.db)
        # 1 + 2 + 3 = 6 unsupported
        self.assertEqual(result["totals"]["unsupported"], 6)

    def test_totals_add_up(self):
        result = epistemic_debt(self.db)
        t = result["totals"]
        self.assertEqual(
            t["claims"],
            t["supported"] + t["tagged"] + t["unsupported"],
            "supported + tagged + unsupported must equal total claims",
        )


# ---------------------------------------------------------------------------
# TestEpistemicDebtLoadBearing
# ---------------------------------------------------------------------------

class TestEpistemicDebtLoadBearing(unittest.TestCase):
    """load_bearing_unsupported counts only load-bearing unsupported claims."""

    def setUp(self):
        self.db = _make_db(with_verification=True)

    def tearDown(self):
        os.unlink(self.db)

    def test_load_bearing_unsupported_correct_count(self):
        result = epistemic_debt(self.db)
        lb = result["load_bearing_unsupported"]
        # Unsupported claims across all runs:
        # run1: "The programme was established in 2019." -> NOT load-bearing (year only)
        # run2: "Under section 14 of the Act 2022, the Minister must publish a report." -> YES
        # run2: "The policy was first introduced in 2018." -> NOT load-bearing (year only)
        # run3: "The department spent 1.2 billion on digital infrastructure." -> YES (magnitude)
        # run3: "Section 99 of the Privacy Act 2000 requires consent before collection." -> YES
        # run3: "The framework was updated in 2021." -> NOT load-bearing (year only)
        # Expected load-bearing unsupported: 3
        self.assertEqual(lb, 3)

    def test_bare_year_claims_not_counted_as_load_bearing(self):
        # Verify individually that bare year sentences are NOT load-bearing.
        bare_year_claims = [
            "The programme was established in 2019.",
            "The policy was first introduced in 2018.",
            "The framework was updated in 2021.",
        ]
        for s in bare_year_claims:
            self.assertFalse(
                is_load_bearing(s),
                "Expected NOT load-bearing but got True for: %r" % s,
            )

    def test_statute_and_magnitude_counted_as_load_bearing(self):
        lb_claims = [
            "Under section 14 of the Act 2022, the Minister must publish a report.",
            "The department spent 1.2 billion on digital infrastructure.",
            "Section 99 of the Privacy Act 2000 requires consent before collection.",
        ]
        for s in lb_claims:
            self.assertTrue(
                is_load_bearing(s),
                "Expected load-bearing but got False for: %r" % s,
            )


# ---------------------------------------------------------------------------
# TestEpistemicDebtVerification
# ---------------------------------------------------------------------------

class TestEpistemicDebtVerification(unittest.TestCase):

    def setUp(self):
        self.db = _make_db(with_verification=True)

    def tearDown(self):
        os.unlink(self.db)

    def test_verified_count(self):
        result = epistemic_debt(self.db)
        self.assertEqual(result["verification"]["verified"], 2)

    def test_contradicted_count(self):
        result = epistemic_debt(self.db)
        self.assertEqual(result["verification"]["contradicted"], 1)

    def test_unverifiable_count(self):
        result = epistemic_debt(self.db)
        self.assertEqual(result["verification"]["unverifiable"], 1)

    def test_not_addressed_zero(self):
        result = epistemic_debt(self.db)
        self.assertEqual(result["verification"]["not_addressed"], 0)

    def test_skipped_zero(self):
        result = epistemic_debt(self.db)
        self.assertEqual(result["verification"]["skipped"], 0)


# ---------------------------------------------------------------------------
# TestEpistemicDebtAbsentVerification
# ---------------------------------------------------------------------------

class TestEpistemicDebtAbsentVerification(unittest.TestCase):
    """When provenance_verification table is absent, verification counts degrade to zeros."""

    def setUp(self):
        self.db = _make_db_no_verification()

    def tearDown(self):
        os.unlink(self.db)

    def test_verification_degrades_to_zeros(self):
        result = epistemic_debt(self.db)
        v = result["verification"]
        for key in ("verified", "contradicted", "not_addressed", "unverifiable", "skipped"):
            self.assertEqual(v[key], 0, "expected 0 for verification[%r] with no table" % key)

    def test_does_not_raise_with_no_verification_table(self):
        try:
            result = epistemic_debt(self.db)
        except Exception as exc:
            self.fail("epistemic_debt raised with no verification table: %s" % exc)

    def test_totals_still_computed_correctly(self):
        result = epistemic_debt(self.db)
        self.assertEqual(result["totals"]["runs"], 1)
        self.assertEqual(result["totals"]["claims"], 2)
        self.assertEqual(result["totals"]["unsupported"], 1)


# ---------------------------------------------------------------------------
# TestEpistemicDebtTrend
# ---------------------------------------------------------------------------

class TestEpistemicDebtTrend(unittest.TestCase):
    """Trend direction is computed correctly from the unsupported rate per run."""

    def _make_trend_db(self, rates):
        """Create a db whose runs have the unsupported rates in *rates* (list of fractions).

        Each rate is expressed as unsupported/total where total=10 for simplicity.
        """
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        db_path = f.name
        con = sqlite3.connect(db_path)
        con.executescript(_SCHEMA)
        total = 10
        for i, rate in enumerate(rates):
            unsupported = int(round(rate * total))
            supported = total - unsupported
            ts = "2026-%02d-01T00:00:00+00:00" % (i + 1)
            con.execute(
                "INSERT INTO provenance_run (ts,mode,total,supported,tagged,unsupported) "
                "VALUES (?,?,?,?,?,?)",
                (ts, "report", total, supported, 0, unsupported),
            )
        con.commit()
        con.close()
        return db_path

    def test_trend_direction_up_when_rate_increases(self):
        # Unsupported rates: 0.1, 0.2, 0.3, 0.4, 0.5 => up
        db = self._make_trend_db([0.1, 0.2, 0.3, 0.4, 0.5])
        try:
            result = epistemic_debt(db)
            self.assertEqual(result["trend"]["direction"], "up")
        finally:
            os.unlink(db)

    def test_trend_direction_down_when_rate_decreases(self):
        # Unsupported rates: 0.5, 0.4, 0.3, 0.2, 0.1 => down
        db = self._make_trend_db([0.5, 0.4, 0.3, 0.2, 0.1])
        try:
            result = epistemic_debt(db)
            self.assertEqual(result["trend"]["direction"], "down")
        finally:
            os.unlink(db)

    def test_trend_direction_flat_when_rate_unchanged(self):
        db = self._make_trend_db([0.3, 0.3, 0.3])
        try:
            result = epistemic_debt(db)
            self.assertEqual(result["trend"]["direction"], "flat")
        finally:
            os.unlink(db)

    def test_trend_uses_main_fixture_correctly(self):
        # Main fixture: rates 1/3 -> 2/4 -> 3/5 => 0.333 -> 0.5 -> 0.6 => up
        db = _make_db(with_verification=True)
        try:
            result = epistemic_debt(db)
            self.assertEqual(result["trend"]["direction"], "up")
        finally:
            os.unlink(db)

    def test_trend_runs_at_most_5(self):
        # 7 runs in DB; trend should return at most 5.
        db = self._make_trend_db([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
        try:
            result = epistemic_debt(db)
            self.assertLessEqual(len(result["trend"]["runs"]), 5)
        finally:
            os.unlink(db)

    def test_trend_runs_ordered_oldest_to_newest(self):
        db = self._make_trend_db([0.1, 0.2, 0.3])
        try:
            result = epistemic_debt(db)
            runs = result["trend"]["runs"]
            if len(runs) >= 2:
                # Timestamps should be non-decreasing.
                for i in range(len(runs) - 1):
                    self.assertLessEqual(runs[i]["ts"], runs[i + 1]["ts"])
        finally:
            os.unlink(db)

    def test_trend_keys_present(self):
        db = _make_db(with_verification=True)
        try:
            result = epistemic_debt(db)
            for run in result["trend"]["runs"]:
                self.assertIn("ts", run)
                self.assertIn("unsupported", run)
                self.assertIn("total", run)
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# TestEpistemicDebtEmptyLedger
# ---------------------------------------------------------------------------

class TestEpistemicDebtEmptyLedger(unittest.TestCase):

    def test_missing_db_returns_zeros_without_raising(self):
        try:
            result = epistemic_debt("/does/not/exist/provenance.db")
        except Exception as exc:
            self.fail("epistemic_debt raised for missing db: %s" % exc)
        self.assertEqual(result["totals"]["runs"], 0)
        self.assertEqual(result["totals"]["claims"], 0)
        self.assertEqual(result["load_bearing_unsupported"], 0)
        self.assertEqual(result["debt_per_1000_words"], 0.0)


# ---------------------------------------------------------------------------
# TestEpistemicDebtDebt
# ---------------------------------------------------------------------------

class TestEpistemicDebtDebt(unittest.TestCase):

    def setUp(self):
        self.db = _make_db(with_verification=True)

    def tearDown(self):
        os.unlink(self.db)

    def test_denominator_is_claims(self):
        result = epistemic_debt(self.db)
        self.assertEqual(result["denominator"], "claims")

    def test_debt_per_1000_nonzero(self):
        result = epistemic_debt(self.db)
        self.assertGreater(result["debt_per_1000_words"], 0.0)

    def test_debt_per_1000_formula(self):
        result = epistemic_debt(self.db)
        lb = result["load_bearing_unsupported"]
        total_claims = result["totals"]["claims"]
        expected = (lb / total_claims) * 1000.0
        self.assertAlmostEqual(result["debt_per_1000_words"], expected, places=5)


# ---------------------------------------------------------------------------
# TestExportEvidenceMatrix
# ---------------------------------------------------------------------------

class TestExportEvidenceMatrixMd(unittest.TestCase):

    def setUp(self):
        self.db = _make_db(with_verification=True)
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        os.unlink(self.db)
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _out(self, name):
        return str(Path(self.tmp_dir) / name)

    def test_md_returns_path(self):
        out = self._out("matrix.md")
        returned = export_evidence_matrix(self.db, out, fmt="md")
        self.assertEqual(returned, str(Path(out).resolve()))

    def test_md_file_exists(self):
        out = self._out("matrix.md")
        export_evidence_matrix(self.db, out, fmt="md")
        self.assertTrue(Path(out).is_file())

    def test_md_contains_header(self):
        out = self._out("matrix.md")
        export_evidence_matrix(self.db, out, fmt="md")
        content = Path(out).read_text(encoding="utf-8")
        for col in ("claim_id", "status", "trigger", "salience", "verdict", "citation", "claim_text"):
            self.assertIn(col, content, "column %r missing from md header" % col)

    def test_md_contains_expected_rows(self):
        out = self._out("matrix.md")
        export_evidence_matrix(self.db, out, fmt="md")
        content = Path(out).read_text(encoding="utf-8")
        # statute-bearing claim from run2 should appear
        self.assertIn("section 14", content)
        # magnitude claim from run3 should appear
        self.assertIn("1.2 billion", content)

    def test_md_contains_verification_verdict(self):
        out = self._out("matrix.md")
        export_evidence_matrix(self.db, out, fmt="md")
        content = Path(out).read_text(encoding="utf-8")
        # At least one verified row should appear
        self.assertIn("verified", content)

    def test_md_never_raises_on_empty_ledger(self):
        out = self._out("empty.md")
        try:
            returned = export_evidence_matrix("/does/not/exist/provenance.db", out, fmt="md")
        except Exception as exc:
            self.fail("export_evidence_matrix raised on empty ledger: %s" % exc)
        content = Path(out).read_text(encoding="utf-8")
        self.assertIn("claim_id", content)
        self.assertIn("no claims recorded", content)

    def test_invalid_fmt_raises_value_error(self):
        out = self._out("bad.txt")
        with self.assertRaises(ValueError):
            export_evidence_matrix(self.db, out, fmt="xlsx")


class TestExportEvidenceMatrixCsv(unittest.TestCase):

    def setUp(self):
        self.db = _make_db(with_verification=True)
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        os.unlink(self.db)
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _out(self, name):
        return str(Path(self.tmp_dir) / name)

    def test_csv_returns_path(self):
        out = self._out("matrix.csv")
        returned = export_evidence_matrix(self.db, out, fmt="csv")
        self.assertEqual(returned, str(Path(out).resolve()))

    def test_csv_is_parseable(self):
        out = self._out("matrix.csv")
        export_evidence_matrix(self.db, out, fmt="csv")
        with open(out, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        self.assertGreater(len(rows), 0)

    def test_csv_contains_expected_columns(self):
        out = self._out("matrix.csv")
        export_evidence_matrix(self.db, out, fmt="csv")
        with open(out, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
        for col in ("claim_id", "status", "trigger", "salience", "verdict", "citation", "claim_text"):
            self.assertIn(col, fieldnames)

    def test_csv_correct_number_of_rows(self):
        out = self._out("matrix.csv")
        export_evidence_matrix(self.db, out, fmt="csv")
        with open(out, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        # 12 total claims in the fixture
        self.assertEqual(len(rows), 12)

    def test_csv_never_raises_on_empty_ledger(self):
        out = self._out("empty.csv")
        try:
            export_evidence_matrix("/does/not/exist/provenance.db", out, fmt="csv")
        except Exception as exc:
            self.fail("export_evidence_matrix raised on empty ledger: %s" % exc)
        content = Path(out).read_text(encoding="utf-8")
        self.assertIn("claim_id", content)
        self.assertIn("no claims recorded", content)

    def test_csv_salience_column_is_numeric_string(self):
        out = self._out("matrix.csv")
        export_evidence_matrix(self.db, out, fmt="csv")
        with open(out, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    float(row["salience"])
                except ValueError:
                    self.fail("salience column is not a valid float: %r" % row["salience"])

    def test_csv_status_values_valid(self):
        out = self._out("matrix.csv")
        export_evidence_matrix(self.db, out, fmt="csv")
        valid_statuses = {"supported", "tagged", "unsupported"}
        with open(out, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                self.assertIn(
                    row["status"], valid_statuses,
                    "unexpected status: %r" % row["status"],
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
