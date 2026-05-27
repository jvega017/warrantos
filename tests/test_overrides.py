#!/usr/bin/env python3
"""Tests for provenance.overrides (SPEC-L8-S002/S003/S004)."""

import tempfile
import unittest
from pathlib import Path

from provenance.overrides import (
    HumanOverride,
    enforce_single_actor_rule,
    get_override_by_id,
    list_overrides_for_run,
    record_override,
)


class TestOverrideValidation(unittest.TestCase):
    """SPEC-L8-S004: empty risk_accepted or compensating_control SHALL
    block the override at the write path."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_overrides.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_risk_accepted_rejected(self):
        """Empty string and whitespace-only values both raise."""
        for bad in ("", "   ", "\t\n"):
            with self.subTest(risk=repr(bad)):
                with self.assertRaises(ValueError) as ctx:
                    record_override(
                        self.db_path,
                        run_id="run_001",
                        reviewer="human:juan.vega",
                        gate_id="G1",
                        failure_class="boundary",
                        risk_accepted=bad,
                        compensating_control="Second-coder review will be re-run.",
                    )
                self.assertIn("SPEC-L8-S004", str(ctx.exception))
                self.assertIn("risk_accepted", str(ctx.exception))

        # No row should have been written.
        self.assertEqual(list_overrides_for_run(self.db_path, "run_001"), [])

    def test_empty_compensating_control_rejected(self):
        """Empty string and whitespace-only values both raise."""
        for bad in ("", "  ", "\n"):
            with self.subTest(control=repr(bad)):
                with self.assertRaises(ValueError) as ctx:
                    record_override(
                        self.db_path,
                        run_id="run_002",
                        reviewer="human:juan.vega",
                        gate_id="G2",
                        failure_class="unsupported",
                        risk_accepted="Single load-bearing claim with no source.",
                        compensating_control=bad,
                    )
                self.assertIn("SPEC-L8-S004", str(ctx.exception))
                self.assertIn("compensating_control", str(ctx.exception))

        self.assertEqual(list_overrides_for_run(self.db_path, "run_002"), [])

    def test_valid_override_writes_and_reads_back(self):
        """Round-trip: a valid override is persisted and retrievable."""
        override = record_override(
            self.db_path,
            run_id="run_003",
            reviewer="human:juan.vega",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Operator phrase 'as discussed' appeared in a quoted source string; not actual narration.",
            compensating_control="Reviewer re-checked the quoted source; quote bracketing is correct.",
            escalation_path_taken="Director SO informed by email 2026-05-27.",
            single_actor=False,
        )

        self.assertIsInstance(override, HumanOverride)
        self.assertGreater(override.id, 0)
        self.assertEqual(override.run_id, "run_003")
        self.assertEqual(override.gate_id, "G1")
        self.assertFalse(override.single_actor)

        retrieved = get_override_by_id(self.db_path, override.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.to_dict(), override.to_dict())

        all_for_run = list_overrides_for_run(self.db_path, "run_003")
        self.assertEqual(len(all_for_run), 1)
        self.assertEqual(all_for_run[0].id, override.id)


class TestSingleActorRule(unittest.TestCase):
    """SPEC-L8-S003: reviewer SHALL be distinct from compose_writer_pack
    actor for the same run_id, OR single_actor=True and artefact
    downgraded out of final-prose."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_overrides.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_same_actor_override_flags_single_actor_and_downgrades_final_prose(self):
        """When reviewer == writer-pack actor and the requested role is
        final-prose, the rule returns (True, 'draft')."""
        single_actor, effective_role = enforce_single_actor_rule(
            reviewer_identity="human:juan.vega",
            writer_pack_actor="human:juan.vega",
            artefact_role="final-prose",
        )
        self.assertTrue(single_actor)
        self.assertEqual(effective_role, "draft")

        # The downgrade flag is then carried into the override row.
        override = record_override(
            self.db_path,
            run_id="run_solo",
            reviewer="human:juan.vega",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Operator approved despite boundary warning.",
            compensating_control="Artefact downgraded from final-prose to draft per SPEC-L8-S003.",
            single_actor=single_actor,
        )
        self.assertTrue(override.single_actor)

    def test_different_actor_override_keeps_single_actor_false(self):
        """When reviewer != writer-pack actor, single_actor is False and
        the artefact role is unchanged."""
        single_actor, effective_role = enforce_single_actor_rule(
            reviewer_identity="human:director.so",
            writer_pack_actor="model:claude-opus-4-7",
            artefact_role="final-prose",
        )
        self.assertFalse(single_actor)
        self.assertEqual(effective_role, "final-prose")

        override = record_override(
            self.db_path,
            run_id="run_separated",
            reviewer="human:director.so",
            gate_id="G2",
            failure_class="unsupported",
            risk_accepted="One unsupported descriptive claim, not load-bearing.",
            compensating_control="Marked [CITE NEEDED] and referenced in evidence matrix.",
            single_actor=single_actor,
        )
        self.assertFalse(override.single_actor)

    def test_same_actor_non_final_prose_role_is_not_downgraded(self):
        """Single-actor in a non-final-prose role does not trigger
        downgrade. Methodology/draft/consultation_report do not carry
        the final-prose reputational commitment SPEC-L8-S005 requires."""
        for role in ("draft", "methodology", "consultation_report"):
            with self.subTest(role=role):
                single_actor, effective_role = enforce_single_actor_rule(
                    reviewer_identity="human:juan.vega",
                    writer_pack_actor="human:juan.vega",
                    artefact_role=role,
                )
                self.assertTrue(single_actor)
                self.assertEqual(effective_role, role)


class TestOverrideLedgerListing(unittest.TestCase):
    """list_overrides_for_run returns rows in insertion order; missing
    db files return empty list rather than raising."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "ledger.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_db_returns_empty_list(self):
        """Listing a run on a database that does not exist returns
        [] rather than raising."""
        missing = Path(self._tmp.name) / "absent.db"
        self.assertEqual(list_overrides_for_run(missing, "any_run"), [])
        self.assertIsNone(get_override_by_id(missing, 1))

    def test_overrides_listed_in_insertion_order(self):
        """Multiple overrides for the same run are listed in id order."""
        first = record_override(
            self.db_path,
            run_id="run_multi",
            reviewer="human:juan.vega",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="First override rationale.",
            compensating_control="First compensating control.",
        )
        second = record_override(
            self.db_path,
            run_id="run_multi",
            reviewer="human:director.so",
            gate_id="G2",
            failure_class="unsupported",
            risk_accepted="Second override rationale.",
            compensating_control="Second compensating control.",
        )

        rows = list_overrides_for_run(self.db_path, "run_multi")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].id, first.id)
        self.assertEqual(rows[1].id, second.id)
        self.assertLess(rows[0].id, rows[1].id)


class TestEscalationTaxonomy(unittest.TestCase):
    """v0.9 SPEC-L8 carry-forward: documented escalation paths are
    accepted verbatim; anything outside the canonical set is prefixed
    `custom:` so it is visibly outside the taxonomy."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "escalation.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _record(self, *, escalation):
        return record_override(
            self.db_path,
            run_id="run_esc",
            reviewer="human:director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Test risk.",
            compensating_control="Test control.",
            escalation_path_taken=escalation,
        )

    def test_canonical_path_recorded_verbatim(self):
        for canonical in (
            "peer_review",
            "director_signoff",
            "legal_review",
            "second_coder_review",
        ):
            with self.subTest(path=canonical):
                row = self._record(escalation=canonical)
                self.assertEqual(row.escalation_path_taken, canonical)

    def test_non_canonical_path_gets_custom_prefix(self):
        row = self._record(escalation="some bespoke path")
        self.assertTrue(row.escalation_path_taken.startswith("custom:"))
        self.assertIn("bespoke", row.escalation_path_taken)

    def test_already_custom_prefixed_path_is_not_double_prefixed(self):
        row = self._record(escalation="custom:already-tagged")
        # Must not become "custom:custom:already-tagged"
        self.assertEqual(
            row.escalation_path_taken.count("custom:"), 1
        )

    def test_none_recorded_canonical_default(self):
        row = self._record(escalation="")
        self.assertEqual(row.escalation_path_taken, "none recorded")

    def test_taxonomy_listing_includes_documented_paths(self):
        from provenance.overrides import list_canonical_escalation_paths
        paths = list_canonical_escalation_paths()
        for p in (
            "none recorded",
            "peer_review",
            "director_signoff",
            "cabinet_office",
            "legal_review",
        ):
            self.assertIn(p, paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
