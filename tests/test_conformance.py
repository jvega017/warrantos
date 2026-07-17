#!/usr/bin/env python3
"""Tests for the per-layer execution probes (Issue 4, Phase 2 P1).

Covers:

- the full probe inventory (L1-L7, G1-G5, I1-I5) reports ENFORCED on a
  healthy install, both with the embedded default fixtures and with the
  file fixtures under tests/fixtures/conformance/;
- ``status.probe_results()`` exposes the same per-layer statuses;
- the meta-test: disconnecting a layer's pipeline call (monkeypatching
  the module attribute to a stub - the runtime equivalent of commenting
  the call out) flips that layer's badge from ENFORCED to AVAILABLE,
  and deleting the symbol flips it to NOT_BUILT. This is the property
  that makes the badge trustworthy: presence alone can never show
  ENFORCED.
"""

import json
import unittest
from pathlib import Path

from warrantos.provenance import conformance
from warrantos.provenance.conformance import (
    AVAILABLE,
    DEFAULT_FIXTURES,
    ENFORCED,
    NOT_BUILT,
    ProbeCase,
    ProbeResult,
    build_probes,
    run_probes,
    summarize,
)
from warrantos.provenance.status import probe_results

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "conformance"

_ALL_PROBE_IDS = [
    "L1", "L2", "L3", "L4", "L5", "L6", "L7",
    "G1", "G2", "G3", "G4", "G5",
    "I1", "I2", "I3", "I4", "I5",
]


def _file_fixtures():
    return {
        "private_reasoning": (_FIXTURE_DIR / "private_reasoning.txt").read_text(
            encoding="utf-8"
        ),
        "feedback": (_FIXTURE_DIR / "feedback.txt").read_text(encoding="utf-8"),
        "residue": (_FIXTURE_DIR / "residue.md").read_text(encoding="utf-8"),
        "claims": (_FIXTURE_DIR / "claims.md").read_text(encoding="utf-8"),
        "contamination": (_FIXTURE_DIR / "contamination.md").read_text(
            encoding="utf-8"
        ),
        "ledger_entries": json.loads(
            (_FIXTURE_DIR / "ledger_entries.json").read_text(encoding="utf-8")
        ),
    }


class TestProbeInventory(unittest.TestCase):
    """The probe set is complete and well-formed."""

    def test_all_seventeen_probes_present_in_order(self):
        probes = build_probes()
        self.assertEqual([p.probe_id for p in probes], _ALL_PROBE_IDS)

    def test_probe_ids_unique(self):
        ids = [p.probe_id for p in build_probes()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_results_serialise(self):
        for result in run_probes():
            d = result.to_dict()
            self.assertEqual(
                sorted(d), ["detail", "layer_id", "name", "probe_id", "status"]
            )


class TestHealthyInstallIsEnforced(unittest.TestCase):
    """Every probe observes enforcement on this checkout."""

    def test_default_fixtures_all_enforced(self):
        for result in run_probes():
            with self.subTest(probe=result.probe_id):
                self.assertEqual(
                    result.status, ENFORCED,
                    "%s: %s" % (result.probe_id, result.detail),
                )

    def test_file_fixtures_all_enforced(self):
        for result in run_probes(_file_fixtures()):
            with self.subTest(probe=result.probe_id):
                self.assertEqual(
                    result.status, ENFORCED,
                    "%s: %s" % (result.probe_id, result.detail),
                )

    def test_fixture_files_mirror_embedded_defaults(self):
        fx = _file_fixtures()
        for key, value in fx.items():
            with self.subTest(fixture=key):
                if isinstance(value, str):
                    self.assertEqual(value.strip(), str(DEFAULT_FIXTURES[key]).strip())
                else:
                    self.assertEqual(value, DEFAULT_FIXTURES[key])

    def test_summarize_counts_all_enforced(self):
        counts = summarize()
        self.assertEqual(counts, {ENFORCED: len(_ALL_PROBE_IDS)})

    def test_clean_fixture_raises_no_flags(self):
        """Sanity: the clean fixture is not flagged by G1 or G4."""
        from warrantos.provenance.context_admissibility import scan_prose_boundary
        from warrantos.provenance.gates import check_contamination

        clean = (_FIXTURE_DIR / "clean.md").read_text(encoding="utf-8")
        self.assertEqual(
            scan_prose_boundary(clean, artefact_role="final-prose").verdict,
            "pass",
        )
        self.assertEqual(check_contamination(clean).matches, [])


class TestStatusProbeResults(unittest.TestCase):
    """status.probe_results() surfaces the per-layer statuses."""

    def test_returns_every_probe_id(self):
        results = probe_results()
        self.assertEqual(sorted(results), sorted(_ALL_PROBE_IDS))

    def test_all_values_are_valid_statuses(self):
        for probe_id, status in probe_results().items():
            with self.subTest(probe=probe_id):
                self.assertIn(status, (ENFORCED, AVAILABLE, NOT_BUILT))

    def test_healthy_install_reports_enforced_everywhere(self):
        self.assertEqual(
            set(probe_results().values()), {ENFORCED},
        )


class TestBadgeFlipsWhenPipelineDisconnected(unittest.TestCase):
    """Meta-test: a disconnected layer can no longer show ENFORCED.

    Monkeypatching the layer's module attribute to a stub is the
    runtime equivalent of commenting out the pipeline call: the symbol
    still exists (so presence checks stay green) but the enforcement
    behaviour is gone. The probe must notice.
    """

    def _status_of(self, probe_id, results=None):
        results = results if results is not None else run_probes()
        return {r.probe_id: r for r in results}[probe_id]

    def test_g4_flips_to_available_when_gate_stubbed(self):
        from warrantos.provenance import gates

        original = gates.check_contamination

        def disconnected_gate(text):
            # The pipeline "forgot" to scan the real text: scan a blank
            # instead, so no matches can ever be produced.
            return original("")

        gates.check_contamination = disconnected_gate
        try:
            result = self._status_of("G4")
            self.assertEqual(result.status, AVAILABLE, result.detail)
        finally:
            gates.check_contamination = original
        self.assertEqual(self._status_of("G4").status, ENFORCED)

    def test_g1_flips_to_available_when_boundary_stubbed(self):
        from warrantos.provenance import context_admissibility as ctx

        original = ctx.scan_prose_boundary

        def disconnected_boundary(text, artefact_role="final"):
            return original("", artefact_role=artefact_role)

        ctx.scan_prose_boundary = disconnected_boundary
        try:
            result = self._status_of("G1")
            self.assertEqual(result.status, AVAILABLE, result.detail)
        finally:
            ctx.scan_prose_boundary = original
        self.assertEqual(self._status_of("G1").status, ENFORCED)

    def test_l7_flips_to_available_when_consolidation_stubbed(self):
        from warrantos.cli import warrantos_cli as cli

        original = cli.consolidate_verdict

        def disconnected_consolidation(*args, **kwargs):
            # A consolidation that waves everything through.
            return "PASS", [], None

        cli.consolidate_verdict = disconnected_consolidation
        try:
            result = self._status_of("L7")
            self.assertEqual(result.status, AVAILABLE, result.detail)
        finally:
            cli.consolidate_verdict = original
        self.assertEqual(self._status_of("L7").status, ENFORCED)

    def test_g4_flips_to_not_built_when_symbol_removed(self):
        from warrantos.provenance import gates

        original = gates.check_contamination
        del gates.check_contamination
        try:
            result = self._status_of("G4")
            self.assertEqual(result.status, NOT_BUILT, result.detail)
        finally:
            gates.check_contamination = original
        self.assertEqual(self._status_of("G4").status, ENFORCED)

    def test_probe_results_reflects_the_flip(self):
        from warrantos.provenance import gates

        original = gates.check_contamination

        def disconnected_gate(text):
            return original("")

        gates.check_contamination = disconnected_gate
        try:
            self.assertEqual(probe_results()["G4"], AVAILABLE)
        finally:
            gates.check_contamination = original
        self.assertEqual(probe_results()["G4"], ENFORCED)

    def test_crashing_layer_degrades_to_available_not_error(self):
        from warrantos.provenance import gates

        original = gates.check_contamination

        def broken_gate(text):
            raise RuntimeError("layer wiring broken")

        gates.check_contamination = broken_gate
        try:
            result = self._status_of("G4")
            self.assertEqual(result.status, AVAILABLE)
            self.assertIn("probe raised", result.detail)
        finally:
            gates.check_contamination = original


class TestProbeCaseContract(unittest.TestCase):
    """ProbeCase itself behaves per its three-state contract."""

    def test_missing_module_reports_not_built(self):
        case = ProbeCase(
            "X1", "X", "missing module",
            (("warrantos.provenance.does_not_exist", "nope"),),
            lambda: True,
        )
        self.assertEqual(case.run().status, NOT_BUILT)

    def test_missing_symbol_reports_not_built(self):
        case = ProbeCase(
            "X2", "X", "missing symbol",
            (("warrantos.provenance.gates", "no_such_function"),),
            lambda: True,
        )
        self.assertEqual(case.run().status, NOT_BUILT)

    def test_false_check_reports_available(self):
        case = ProbeCase(
            "X3", "X", "unenforced",
            (("warrantos.provenance.gates", "check_contamination"),),
            lambda: False,
        )
        self.assertEqual(case.run().status, AVAILABLE)

    def test_true_check_reports_enforced(self):
        case = ProbeCase(
            "X4", "X", "enforced",
            (("warrantos.provenance.gates", "check_contamination"),),
            lambda: True,
        )
        result = case.run()
        self.assertEqual(result.status, ENFORCED)
        self.assertIsInstance(result, ProbeResult)


if __name__ == "__main__":
    unittest.main(verbosity=2)
