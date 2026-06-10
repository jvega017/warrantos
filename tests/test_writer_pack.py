#!/usr/bin/env python3
"""Tests for provenance.writer_pack (Layer 5).

Validates the SPEC-L4-S001 enforcement at the writer entry point and
the SPEC §6.2 required pack contents.
"""

import unittest

from warrantos.provenance.context_admissibility import classify_context
from warrantos.provenance.writer_pack import (
    WriterPack,
    _admissible_to_writer,
    compile_writer_pack,
)


class TestAdmissibleToWriter(unittest.TestCase):
    """SPEC-L4-S001: clean_room_writer can read this item, or it
    cannot reach Layer 5."""

    def test_admits_when_clean_room_writer_in_can_be_seen_by(self):
        item = classify_context("ctx_src", "Source: report.pdf, 2026.")
        # empirical_evidence has clean_room_writer in can_be_seen_by.
        self.assertTrue(_admissible_to_writer(item))

    def test_excludes_private_reasoning(self):
        item = classify_context(
            "ctx_pr", "My private reasoning is that X."
        )
        self.assertFalse(_admissible_to_writer(item))

    def test_excludes_when_cannot_be_seen_by_lists_writer(self):
        item = classify_context(
            "ctx_fb", "This is not commercial enough."
        )
        # user_feedback sets cannot_be_seen_by=("clean_room_writer",).
        self.assertFalse(_admissible_to_writer(item))


class TestCompileWriterPack(unittest.TestCase):
    """Pack contents match SPEC §6.2; excluded count is reported."""

    def test_empty_input_returns_default_acceptance_tests(self):
        pack = compile_writer_pack([], run_id="run_empty")
        self.assertIsInstance(pack, WriterPack)
        self.assertEqual(pack.clean_brief, [])
        self.assertEqual(pack.approved_sources, [])
        self.assertEqual(pack.style_rules, [])
        # Default acceptance tests cover Layer 7 G1, G2, G3.
        self.assertGreaterEqual(len(pack.acceptance_tests), 3)
        # Banned residue includes the base list.
        self.assertIn("based on your feedback", pack.banned_residue)

    def test_empirical_evidence_becomes_approved_source(self):
        item = classify_context(
            "ctx_src", "Source: Treasury Bulletin, 2026, page 12."
        )
        pack = compile_writer_pack([item], run_id="run_src")
        self.assertEqual(len(pack.approved_sources), 1)
        self.assertEqual(pack.approved_sources[0]["context_id"], "ctx_src")
        self.assertEqual(pack.excluded_count, 0)

    def test_user_feedback_is_excluded_not_admitted_verbatim(self):
        item = classify_context(
            "ctx_fb", "This is not commercial enough."
        )
        pack = compile_writer_pack([item], run_id="run_fb")
        self.assertEqual(pack.excluded_count, 1)
        # No empirical sources, no clean brief content (feedback not
        # passed through to the writer as verbatim text).
        self.assertEqual(pack.approved_sources, [])
        # Critically: the raw feedback text MUST NOT appear in the brief.
        for line in pack.clean_brief:
            self.assertNotIn("not commercial enough", line)

    def test_private_reasoning_excluded_from_pack(self):
        item = classify_context(
            "ctx_pr", "My private reasoning chain says X."
        )
        pack = compile_writer_pack([item], run_id="run_pr")
        self.assertEqual(pack.excluded_count, 1)
        self.assertEqual(pack.clean_brief, [])

    def test_style_signal_becomes_style_rule(self):
        item = classify_context(
            "ctx_style", "Use Australian English and a short tone."
        )
        pack = compile_writer_pack([item], run_id="run_style")
        self.assertEqual(len(pack.style_rules), 1)

    def test_to_dict_serialises_with_schema_name(self):
        pack = compile_writer_pack([], run_id="run_schema")
        d = pack.to_dict()
        self.assertEqual(d["schema"], "warrantos-writer-pack/v1")
        self.assertEqual(d["run_id"], "run_schema")
        for key in (
            "clean_brief",
            "approved_sources",
            "style_rules",
            "acceptance_tests",
            "banned_residue",
            "excluded_count",
        ):
            self.assertIn(key, d)

    def test_extra_banned_residue_appends_to_default_list(self):
        pack = compile_writer_pack(
            [], run_id="run_extra",
            extra_banned_residue=["this is the agreed final version"],
        )
        self.assertIn("based on your feedback", pack.banned_residue)
        self.assertIn("this is the agreed final version", pack.banned_residue)

    def test_extra_acceptance_tests_appends(self):
        pack = compile_writer_pack(
            [], run_id="run_extra2",
            extra_acceptance_tests=["Custom test: passes the smoke test."],
        )
        self.assertIn(
            "Custom test: passes the smoke test.",
            pack.acceptance_tests,
        )


class TestSpecConformance(unittest.TestCase):
    """SPEC §6.5 reproducibility, content, and exclusion tests."""

    def test_reproducibility_same_inputs_same_pack(self):
        """SPEC §6.5 item 1: identical inputs produce identical packs."""
        items = [
            classify_context("ctx_s1", "Source: Treasury Bulletin, 2026."),
            classify_context("ctx_s2", "Use formal tone."),
            classify_context("ctx_s3", "This is not commercial enough."),
        ]
        a = compile_writer_pack(items, run_id="run_repro").to_dict()
        b = compile_writer_pack(items, run_id="run_repro").to_dict()
        self.assertEqual(a, b)

    def test_content_at_least_one_admitted_when_evidence_present(self):
        """SPEC §6.5 item 2: pack contains the admitted material."""
        items = [classify_context("ctx_src", "Source: report.pdf, 2026.")]
        pack = compile_writer_pack(items, run_id="run_content")
        self.assertEqual(len(pack.approved_sources), 1)

    def test_exclusion_process_classes_never_become_verbatim_brief(self):
        """SPEC §6.5 item 3: process classes are transformed or
        excluded, never threaded into the brief as verbatim text."""
        items = [
            classify_context(
                "ctx_fb", "Make it more commercial; the previous version was weak."
            ),
            classify_context(
                "ctx_proc", "As discussed, the deadline is tight."
            ),
            classify_context(
                "ctx_pr", "My private reasoning suggests X."
            ),
        ]
        pack = compile_writer_pack(items, run_id="run_exclude")
        joined = " ".join(pack.clean_brief)
        self.assertNotIn("Make it more commercial", joined)
        self.assertNotIn("As discussed", joined)
        self.assertNotIn("private reasoning", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
