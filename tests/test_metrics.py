#!/usr/bin/env python3
"""Tests for warrantos.provenance.metrics (F-metrics shadow-log aggregation).

Covers:

- a missing log aggregates to an empty, honest result (no error)
- an empty log file aggregates to observed=0
- verdict distribution and unsupported-claim rate over observed rows
- non-observed rows (observer_error / no_brief_found) are counted but
  excluded from the rates
- malformed JSON lines are counted and skipped, never guessed
- the trend label: improving / worsening / stable / insufficient_data
- claim rows with bad counts (supported > detected, negatives, missing)
  are excluded from the denominator
- write_metrics_json writes a valid metrics.json
- calibration_supplement exposes the monitoring signal honestly
- gates.calibration_with_monitoring links the two surfaces without
  conflating them
"""

import json
import tempfile
import unittest
from pathlib import Path

from warrantos.provenance.metrics import (
    ShadowMetrics,
    aggregate_shadow_log,
    calibration_supplement,
    write_metrics_json,
)
from warrantos.provenance import gates


def _write_log(lines):
    """Write a list of dicts (or raw strings) as JSON-lines to a temp file.

    Returns the Path. Caller is responsible for the enclosing tmpdir.
    """
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".log", delete=False, encoding="utf-8"
    )
    for line in lines:
        if isinstance(line, str):
            tmp.write(line + "\n")
        else:
            tmp.write(json.dumps(line) + "\n")
    tmp.close()
    return Path(tmp.name)


def _observed(ts, verdict, detected, supported):
    return {
        "ts": ts,
        "brief": "brief.md",
        "profile": "brief-light",
        "shadow_status": "observed",
        "verdict": verdict,
        "boundary_verdict": "PASS",
        "boundary_violations": 0,
        "claims_detected": detected,
        "claims_supported": supported,
        "context_items": 3,
    }


class TestMissingAndEmpty(unittest.TestCase):
    def test_missing_log_is_not_an_error(self):
        m = aggregate_shadow_log(Path(tempfile.gettempdir()) / "does-not-exist-xyz.log")
        self.assertIsInstance(m, ShadowMetrics)
        self.assertEqual(m.observed, 0)
        self.assertEqual(m.total_lines, 0)
        self.assertIsNone(m.unsupported_rate)
        self.assertEqual(m.trend, "insufficient_data")
        self.assertIsNone(m.window_start)

    def test_empty_log_file(self):
        p = _write_log([])
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.observed, 0)
            self.assertEqual(m.trend, "insufficient_data")
        finally:
            p.unlink()

    def test_blank_lines_skipped(self):
        p = _write_log(["", "   ", ""])
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.observed, 0)
            self.assertEqual(m.malformed_lines, 0)
            self.assertEqual(m.total_lines, 0)
        finally:
            p.unlink()


class TestVerdictAndRate(unittest.TestCase):
    def test_verdict_distribution_and_rate(self):
        rows = [
            _observed("2026-06-01T07:00:00Z", "PASS", 10, 9),
            _observed("2026-06-02T07:00:00Z", "PASS", 10, 8),
            _observed("2026-06-03T07:00:00Z", "HOLD", 10, 5),
        ]
        p = _write_log(rows)
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.observed, 3)
            self.assertEqual(m.verdict_distribution, {"PASS": 2, "HOLD": 1})
            # detected 30, supported 22, unsupported 8 -> 8/30
            self.assertEqual(m.claims_detected_total, 30)
            self.assertEqual(m.claims_supported_total, 22)
            self.assertAlmostEqual(m.unsupported_rate, round(8 / 30, 4))
            self.assertEqual(m.window_start, "2026-06-01T07:00:00Z")
            self.assertEqual(m.window_end, "2026-06-03T07:00:00Z")
        finally:
            p.unlink()

    def test_non_observed_excluded_from_rate(self):
        rows = [
            _observed("2026-06-01T07:00:00Z", "PASS", 10, 9),
            {"ts": "2026-06-02T07:00:00Z", "shadow_status": "no_brief_found"},
            {
                "ts": "2026-06-03T07:00:00Z",
                "shadow_status": "observer_error",
                "error": "boom",
            },
        ]
        p = _write_log(rows)
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.observed, 1)
            self.assertEqual(m.non_observed, 2)
            self.assertEqual(
                m.non_observed_by_status,
                {"no_brief_found": 1, "observer_error": 1},
            )
            # only the single observed row contributes
            self.assertEqual(m.claims_detected_total, 10)
            self.assertAlmostEqual(m.unsupported_rate, round(1 / 10, 4))
        finally:
            p.unlink()

    def test_malformed_lines_counted_not_guessed(self):
        p = _write_log([
            _observed("2026-06-01T07:00:00Z", "PASS", 10, 9),
            "{not valid json",
            "[1, 2, 3]",   # valid JSON but not an object -> malformed row
            "42",          # valid JSON scalar -> malformed row
        ])
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.observed, 1)
            self.assertEqual(m.malformed_lines, 3)
            self.assertEqual(m.total_lines, 4)
        finally:
            p.unlink()

    def test_bad_claim_counts_excluded(self):
        rows = [
            # supported > detected: invalid, excluded
            _observed("2026-06-01T07:00:00Z", "PASS", 5, 9),
            # negative: invalid, excluded
            _observed("2026-06-02T07:00:00Z", "PASS", -1, 0),
            # missing counts: excluded from denominator but still observed
            {
                "ts": "2026-06-03T07:00:00Z",
                "shadow_status": "observed",
                "verdict": "PASS",
            },
            # valid
            _observed("2026-06-04T07:00:00Z", "PASS", 10, 7),
        ]
        p = _write_log(rows)
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.observed, 4)
            # only the last row has a valid denominator
            self.assertEqual(m.claims_detected_total, 10)
            self.assertEqual(m.claims_supported_total, 7)
            self.assertAlmostEqual(m.unsupported_rate, round(3 / 10, 4))
            # one claim-bearing row -> trend insufficient
            self.assertEqual(m.trend, "insufficient_data")
        finally:
            p.unlink()


class TestTrend(unittest.TestCase):
    def test_improving_trend(self):
        # earlier half has high unsupported rate, later half low
        rows = [
            _observed("2026-06-01T07:00:00Z", "HOLD", 10, 2),  # 0.8 unsupported
            _observed("2026-06-02T07:00:00Z", "HOLD", 10, 3),  # 0.7
            _observed("2026-06-03T07:00:00Z", "PASS", 10, 9),  # 0.1
            _observed("2026-06-04T07:00:00Z", "PASS", 10, 10),  # 0.0
        ]
        p = _write_log(rows)
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.trend, "improving")
            self.assertGreater(
                m.unsupported_rate_earlier, m.unsupported_rate_later
            )
        finally:
            p.unlink()

    def test_worsening_trend(self):
        rows = [
            _observed("2026-06-01T07:00:00Z", "PASS", 10, 10),  # 0.0
            _observed("2026-06-02T07:00:00Z", "PASS", 10, 9),   # 0.1
            _observed("2026-06-03T07:00:00Z", "HOLD", 10, 3),   # 0.7
            _observed("2026-06-04T07:00:00Z", "HOLD", 10, 2),   # 0.8
        ]
        p = _write_log(rows)
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.trend, "worsening")
        finally:
            p.unlink()

    def test_stable_trend(self):
        rows = [
            _observed("2026-06-01T07:00:00Z", "PASS", 10, 8),
            _observed("2026-06-02T07:00:00Z", "PASS", 10, 8),
            _observed("2026-06-03T07:00:00Z", "PASS", 10, 8),
            _observed("2026-06-04T07:00:00Z", "PASS", 10, 8),
        ]
        p = _write_log(rows)
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.trend, "stable")
        finally:
            p.unlink()

    def test_unsorted_timestamps_are_ordered(self):
        # rows written out of order; trend must reflect chronological order
        rows = [
            _observed("2026-06-04T07:00:00Z", "PASS", 10, 10),
            _observed("2026-06-01T07:00:00Z", "HOLD", 10, 2),
            _observed("2026-06-03T07:00:00Z", "PASS", 10, 9),
            _observed("2026-06-02T07:00:00Z", "HOLD", 10, 3),
        ]
        p = _write_log(rows)
        try:
            m = aggregate_shadow_log(p)
            self.assertEqual(m.window_start, "2026-06-01T07:00:00Z")
            self.assertEqual(m.window_end, "2026-06-04T07:00:00Z")
            self.assertEqual(m.trend, "improving")
        finally:
            p.unlink()


class TestWriteMetrics(unittest.TestCase):
    def test_write_metrics_json(self):
        rows = [_observed("2026-06-01T07:00:00Z", "PASS", 10, 9)]
        p = _write_log(rows)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "sub" / "metrics.json"
            try:
                m = aggregate_shadow_log(p)
                written = write_metrics_json(m, out)
                self.assertTrue(written.is_file())
                loaded = json.loads(written.read_text(encoding="utf-8"))
                self.assertEqual(loaded["observed"], 1)
                self.assertEqual(loaded["verdict_distribution"], {"PASS": 1})
                self.assertIn("note", loaded)
            finally:
                p.unlink()


class TestCalibrationLink(unittest.TestCase):
    def test_calibration_supplement_shape(self):
        rows = [
            _observed("2026-06-01T07:00:00Z", "PASS", 10, 8),
            _observed("2026-06-02T07:00:00Z", "PASS", 10, 8),
            _observed("2026-06-03T07:00:00Z", "PASS", 10, 8),
            _observed("2026-06-04T07:00:00Z", "PASS", 10, 8),
        ]
        p = _write_log(rows)
        try:
            m = aggregate_shadow_log(p)
            supp = calibration_supplement(m)
            self.assertEqual(supp["source"], "shadow_log")
            self.assertAlmostEqual(supp["observed_unsupported_rate"], 0.2)
            self.assertEqual(supp["unsupported_rate_trend"], "stable")
            self.assertEqual(supp["observed_rows"], 4)
            # honesty: must disclaim it is not a corpus calibration
            self.assertIn("NOT a corpus calibration", supp["note"])
        finally:
            p.unlink()

    def test_calibration_with_monitoring_keeps_surfaces_separate(self):
        rows = [_observed("2026-06-01T07:00:00Z", "PASS", 10, 9)]
        p = _write_log(rows)
        try:
            # live verdict rows for check_calibration (no confidence ->
            # coverage 0); shadow log supplies the monitoring block.
            verdicts = [{"verdict": "verified"}, {"verdict": "verified"}]
            out = gates.calibration_with_monitoring(
                verdicts, shadow_log_path=p
            )
            self.assertIn("calibration", out)
            self.assertIn("monitoring", out)
            # calibration is the corpus/Brier surface
            self.assertEqual(out["calibration"]["total"], 2)
            # monitoring is the shadow-log surface
            self.assertEqual(out["monitoring"]["source"], "shadow_log")
            self.assertAlmostEqual(
                out["monitoring"]["observed_unsupported_rate"], 0.1
            )
        finally:
            p.unlink()

    def test_calibration_with_monitoring_no_shadow(self):
        out = gates.calibration_with_monitoring(
            [{"verdict": "verified"}], shadow_log_path=None
        )
        self.assertIsNone(out["monitoring"])
        self.assertEqual(out["calibration"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
