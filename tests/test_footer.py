#!/usr/bin/env python3
"""Tests for provenance.footer (SPEC-L8-S005) and the warrantos CLI scaffold."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from conftest import get_clean_env
except ImportError:  # running as tests.test_* from the repo root
    from tests.conftest import get_clean_env

from warrantos.provenance.footer import render_override_footer
from warrantos.provenance.overrides import HumanOverride, record_override


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_PATH = _REPO_ROOT / "warrantos" / "cli" / "warrantos_cli.py"


def _make_override(
    *,
    override_id: int = 1,
    ts: str = "2026-05-27T10:00:00Z",
    run_id: str = "run_demo",
    reviewer: str = "human:director.so",
    gate_id: str = "G1",
    failure_class: str = "boundary",
    risk_accepted: str = "Demo risk rationale.",
    compensating_control: str = "Demo compensating control.",
    escalation_path_taken: str = "Demo escalation.",
    single_actor: bool = False,
) -> HumanOverride:
    return HumanOverride(
        id=override_id,
        ts=ts,
        run_id=run_id,
        reviewer=reviewer,
        gate_id=gate_id,
        failure_class=failure_class,
        risk_accepted=risk_accepted,
        compensating_control=compensating_control,
        escalation_path_taken=escalation_path_taken,
        single_actor=single_actor,
    )


class TestOverrideFooter(unittest.TestCase):
    """SPEC-L8-S005: a final-prose artefact shipped on override SHALL
    carry its override list in a reader-facing footer."""

    def test_empty_list_returns_empty_string(self):
        """No overrides means no footer; SPEC-L8-S005 applies only when
        an override exists."""
        self.assertEqual(render_override_footer([]), "")

    def test_single_override_renders_visible_block(self):
        """One override produces a Markdown block with the heading,
        override id, gate, failure class, risk accepted, compensating
        control, escalation path, reviewer, and timestamp."""
        row = _make_override(
            override_id=42,
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Lexical false positive in a quoted source string.",
            compensating_control="Second-coder review of the quoted source.",
            reviewer="human:director.so",
            ts="2026-05-27T11:30:00Z",
        )
        footer = render_override_footer([row])

        self.assertIn("## Overrides applied", footer)
        self.assertIn("ovr_42", footer)
        self.assertIn("**G1**", footer)
        self.assertIn("boundary", footer)
        self.assertIn("Lexical false positive in a quoted source string.", footer)
        self.assertIn("Second-coder review of the quoted source.", footer)
        self.assertIn("human:director.so", footer)
        self.assertIn("2026-05-27T11:30:00Z", footer)

    def test_single_actor_carries_visible_marker(self):
        """SPEC-L8-S003 + S005: a single-actor override is visible as
        such in the reader-facing footer, so the operator's reputational
        commitment includes the role downgrade."""
        row = _make_override(single_actor=True)
        footer = render_override_footer([row])

        self.assertIn("single-actor", footer)
        self.assertIn("artefact role downgraded", footer)

    def test_multi_line_rationale_is_squashed_to_single_line(self):
        """The footer is a Markdown list. Multi-line rationale text is
        joined to a single line so the list structure is not broken."""
        row = _make_override(
            risk_accepted="Risk:\n  - Item one.\n  - Item two.\n",
            compensating_control="Control:\nAlso multi-line.",
        )
        footer = render_override_footer([row])

        for line in footer.splitlines():
            # The risk/control values are emitted on a single Markdown
            # sub-bullet line. Their text must not start a new bullet.
            if "Risk:" in line:
                self.assertIn("Item one", line)
                self.assertIn("Item two", line)

    def test_custom_heading(self):
        row = _make_override(override_id=7)
        footer = render_override_footer([row], heading="Decision overrides")
        self.assertIn("## Decision overrides", footer)


class TestFooterIntegrationWithLedger(unittest.TestCase):
    """End-to-end: record_override + list + render_override_footer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "overrides.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_recorded_overrides_render_to_footer(self):
        """Round-trip: write two override rows, list them, render the
        footer. Both overrides appear in the output in insertion order."""
        first = record_override(
            self.db_path,
            run_id="run_e2e",
            reviewer="human:juan.vega",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="One.",
            compensating_control="A.",
        )
        second = record_override(
            self.db_path,
            run_id="run_e2e",
            reviewer="human:director.so",
            gate_id="G2",
            failure_class="unsupported",
            risk_accepted="Two.",
            compensating_control="B.",
        )

        from warrantos.provenance.overrides import list_overrides_for_run
        footer = render_override_footer(list_overrides_for_run(self.db_path, "run_e2e"))

        self.assertIn("ovr_%d" % first.id, footer)
        self.assertIn("ovr_%d" % second.id, footer)
        # Insertion order is preserved in the footer text.
        first_pos = footer.index("ovr_%d" % first.id)
        second_pos = footer.index("ovr_%d" % second.id)
        self.assertLess(first_pos, second_pos)


class TestWarrantosCliScaffold(unittest.TestCase):
    """Day-4 CLI scaffold: help renders, missing-draft handled, simple
    text and JSON output paths produce parsable summaries."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.draft_path = Path(self._tmp.name) / "draft.md"
        self.draft_path.write_text(
            "# Sample draft\n\nThis programme delivered measurable outcomes.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra_args: str) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(_CLI_PATH)] + list(extra_args)
        return subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            env=get_clean_env(),
        )

    def test_help_renders(self):
        """`--help` exits cleanly and mentions the integration scope."""
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("WarrantOS", proc.stdout)
        self.assertIn("check", proc.stdout)

    def test_check_missing_draft_returns_two(self):
        """A missing draft path exits 2 with a stderr message."""
        proc = self._run("check", str(Path(self._tmp.name) / "missing.md"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("draft file not found", proc.stderr)

    def test_check_text_output_summary(self):
        """The text summary block names the run id, draft chars, and the
        consolidated verdict. Default profile is final-prose without an
        actor identity, so the verdict is NOT_ASSESSABLE per Codex C1."""
        proc = self._run("check", str(self.draft_path))
        # NOT_ASSESSABLE with no --ci returns 0; with --ci returns 1.
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("warrantos check", proc.stdout)
        self.assertIn("run id:", proc.stdout)
        self.assertIn("draft chars:", proc.stdout)
        self.assertIn("VERDICT:", proc.stdout)
        # Without --actor-identity, final-prose default triggers NOT_ASSESSABLE.
        self.assertIn("NOT_ASSESSABLE", proc.stdout)

    def test_check_json_output_parses(self):
        """`--json` emits a parsable JSON object with the documented keys."""
        proc = self._run("check", str(self.draft_path), "--json")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn("run_id", data)
        self.assertIn("draft_chars", data)
        self.assertIn("by_context_type", data)
        self.assertIn("verdict", data)
        self.assertIn("reasons", data)
        self.assertIn("cbom_schema", data)
        self.assertEqual(data["cbom_schema"], "warrantos-cbom/v1")

    def test_check_with_context_classifies_review_role(self):
        """A context item with source_agent=policy-red-team is classified
        as review_finding, demonstrating the Day-3 SPEC-L1-S005 wiring
        through the CLI."""
        ctx_path = Path(self._tmp.name) / "context.json"
        ctx_path.write_text(
            json.dumps(
                [
                    {
                        "id": "ctx_001",
                        "text": (
                            "Severity: P0\n# Findings\n"
                            "A1 chain of thought attack vector."
                        ),
                        "source_agent": "policy-red-team",
                    },
                    {
                        "id": "ctx_002",
                        "text": "An ordinary policy claim with a source citation.",
                    },
                ]
            ),
            encoding="utf-8",
        )
        proc = self._run(
            "check", str(self.draft_path),
            "--context", str(ctx_path),
            "--json",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["context_items"], 2)
        # ctx_001 should be review_finding (not private_reasoning) because
        # source_agent is set; this is the SPEC-L1-S005 A1 closure flowing
        # through the CLI.
        self.assertGreaterEqual(data["by_context_type"].get("review_finding", 0), 1)
        # ctx_002 should be empirical_evidence (text mentions "citation").
        self.assertGreaterEqual(
            data["by_context_type"].get("empirical_evidence", 0),
            1,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
