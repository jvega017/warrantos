#!/usr/bin/env python3
"""End-to-end integration tests for cli/warrantos_cli.py (Path X3 Day 5).

Validates the upstream leg of the coupling thesis:

- Layer 1 classification (with SPEC-L1-S005 source_agent gating)
- Layer 7 G1 prose-boundary scan
- Layer 7 G2 claim detection (offline; verifier optional)
- CBOM v0.2 assembly with actor_identity and override_ledger_refs
- Four-state consolidated verdict including NOT_ASSESSABLE (Codex C1)
- Reader-facing override footer (SPEC-L8-S005) when overrides exist
- CI exit codes
- Error contract: detector or verifier failure does not crash the run

Honest scope: the offline heuristic verifier cannot emit `contradicted`
by construction (documented in grade.py and MEMORY.md). The BLOCK-on-
contradicted branch therefore has no offline test; only the
BLOCK-on-boundary-violation branch is exercised here.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from provenance.overrides import record_override


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_PATH = _REPO_ROOT / "cli" / "warrantos_cli.py"


_FINAL_ACTOR = {
    "context_classifier": "agent:auto",
    "insight_compiler": "human:juan.vega",
    "source_curator": "human:juan.vega",
    "clean_room_writer": "model:claude-opus-4-7",
    "reviewer_qa": "agent:policy-red-team",
    "auditor": "human:director.so",
}


class _Harness:
    """Shared scaffolding for the CLI integration tests."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "overrides.db"
        self.out_dir = self.tmp / "runs"

    def write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def write_json(self, name: str, obj) -> Path:
        return self.write(name, json.dumps(obj))

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def run(self, *args: str) -> subprocess.CompletedProcess:
        cmd = [
            sys.executable, str(_CLI_PATH),
            "check",
        ] + list(args) + [
            "--db", str(self.db),
            "--out-dir", str(self.out_dir),
            "--json",
        ]
        return subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )


class TestPassPath(unittest.TestCase):
    """A clean final-prose draft with actor_identity supplied yields PASS."""

    def setUp(self):
        self.h = _Harness()
        self.draft = self.h.write(
            "draft.md",
            "# Open data policy\n\n"
            "The framework underpins administrative decisions.\n"
            "Implementation follows the published guidance.\n",
        )
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_pass_with_actor_identity(self):
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "PASS")
        self.assertEqual(data["boundary_verdict"], "pass")
        self.assertEqual(data["reasons"], [])


class TestNotAssessable(unittest.TestCase):
    """Codex C1: final-prose without actor_identity is NOT_ASSESSABLE."""

    def setUp(self):
        self.h = _Harness()
        self.draft = self.h.write(
            "draft.md",
            "# A clean note\n\nA neutral paragraph.\n",
        )

    def tearDown(self):
        self.h.cleanup()

    def test_final_prose_without_actor_is_not_assessable(self):
        proc = self.h.run(str(self.draft), "--profile", "final-prose")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "NOT_ASSESSABLE")
        self.assertTrue(any("actor_identity" in r for r in data["reasons"]))

    def test_non_final_prose_profile_does_not_trigger_not_assessable(self):
        """Audit and methodology profiles do not carry the final-prose
        reputational commitment; PASS is permitted without actor identity."""
        proc = self.h.run(str(self.draft), "--profile", "audit")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "PASS")


class TestBlockOnBoundaryViolation(unittest.TestCase):
    """A draft with 'based on your feedback' triggers BLOCK in final-prose."""

    def setUp(self):
        self.h = _Harness()
        self.draft = self.h.write(
            "draft.md",
            "# Revised note\n\nBased on your feedback this version is clearer.\n",
        )
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_block_on_boundary_violation_with_ci_exits_one(self):
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--ci",
        )
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "BLOCK")
        self.assertGreater(data["boundary_violations"], 0)

    def test_block_without_ci_still_exits_zero(self):
        """Without --ci the BLOCK verdict is informational only."""
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "BLOCK")


class TestHoldPaths(unittest.TestCase):
    """HOLD fires on unsupported load-bearing claims or unverifiable
    load-bearing claims. The salience threshold is provenance.salience.
    LOAD_BEARING_THRESHOLD = 0.5; Codex Cx6 fix: this constant is the
    HOLD line, not an inline magic number."""

    def setUp(self):
        self.h = _Harness()
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_unsupported_load_bearing_claim_holds(self):
        """A claim sentence with statute reference triggers
        salience >= 0.5 (statute alone contributes 0.55). With no
        citation in the sentence, the consolidated verdict is HOLD."""
        draft = self.h.write(
            "draft.md",
            "# Brief\n\n"
            "The agency must comply with section 23 of the Privacy Act 1988.\n"
            "Implementation will proceed as planned.\n",
        )
        proc = self.h.run(
            str(draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "HOLD")
        self.assertTrue(any("unsupported load-bearing" in r for r in data["reasons"]))

    def test_supported_load_bearing_claim_does_not_hold(self):
        """The same statute claim with a URL citation in the sentence is
        treated as supported and does not trigger HOLD."""
        draft = self.h.write(
            "draft.md",
            "# Brief\n\n"
            "The agency must comply with section 23 of the Privacy Act 1988 "
            "(https://www.legislation.gov.au/Details/C2014C00076).\n",
        )
        proc = self.h.run(
            str(draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        # PASS because the only claim is supported and boundary is pass.
        self.assertEqual(data["verdict"], "PASS")


class TestReviewRoleGatingThroughCli(unittest.TestCase):
    """The SPEC-L1-S005 A1-attack closure (Day 3) flows through the CLI:
    context items with source_agent in REVIEW_ROLE_REGISTRY classify as
    review_finding regardless of text content."""

    def setUp(self):
        self.h = _Harness()
        self.draft = self.h.write("draft.md", "# A neutral note\n")
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_policy_red_team_context_stays_review_finding(self):
        ctx = self.h.write_json(
            "ctx.json",
            [
                {
                    "id": "ctx_a1",
                    "text": (
                        "Severity: P0\n# Findings\n"
                        "A1: chain of thought attack vector identified."
                    ),
                    "source_agent": "policy-red-team",
                },
            ],
        )
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--context", str(ctx),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertGreaterEqual(
            data["by_context_type"].get("review_finding", 0),
            1,
        )
        # The A1 closure: not private_reasoning.
        self.assertEqual(data["by_context_type"].get("private_reasoning", 0), 0)


class TestOverrideFooterEmission(unittest.TestCase):
    """When the override ledger contains rows for this run, the CLI
    writes the SPEC-L8-S005 reader-facing footer to disk."""

    def setUp(self):
        self.h = _Harness()
        self.draft = self.h.write("draft.md", "# Override-demo note\n")
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_override_footer_written_when_overrides_exist(self):
        # Record an override against the run id that the CLI will see.
        run_id = "run_overridedemo"
        record_override(
            self.h.db,
            run_id=run_id,
            reviewer="human:director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Demo rationale.",
            compensating_control="Demo compensating control.",
        )
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--run-id", run_id,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        # Footer file written to the per-run output directory.
        footer_path = self.h.out_dir / "footer.md"
        self.assertTrue(footer_path.is_file(), msg="footer.md should be written")
        body = footer_path.read_text(encoding="utf-8")
        self.assertIn("## Overrides applied", body)
        self.assertIn("Demo rationale", body)


class TestCbomArtefactWritten(unittest.TestCase):
    """The CBOM v0.2 artefact lands on disk with the canonical schema name
    and the new actor_identity and override_ledger_refs fields populated
    from the CLI inputs."""

    def setUp(self):
        self.h = _Harness()
        self.draft = self.h.write("draft.md", "# Plain note\n")
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_cbom_v02_fields_present(self):
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        report = json.loads(proc.stdout)
        cbom_path = Path(report["out_dir"]) / "cbom.json"
        self.assertTrue(cbom_path.is_file(), msg="cbom.json should be written")
        cbom = json.loads(cbom_path.read_text(encoding="utf-8"))
        self.assertEqual(cbom["schema"], "warrantos-cbom/v1")
        self.assertIn("actor_identity", cbom)
        self.assertEqual(cbom["actor_identity"], _FINAL_ACTOR)
        self.assertIn("classification_overrides", cbom)
        self.assertIn("override_ledger_refs", cbom)


class TestErrorContract(unittest.TestCase):
    """Errors in inputs return controlled exit codes; internal exceptions
    in optional stages are captured and the run continues."""

    def setUp(self):
        self.h = _Harness()

    def tearDown(self):
        self.h.cleanup()

    def test_missing_draft_returns_two(self):
        cmd = [
            sys.executable, str(_CLI_PATH),
            "check", str(self.h.tmp / "absent.md"),
            "--db", str(self.h.db),
            "--out-dir", str(self.h.out_dir),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("draft file not found", proc.stderr)

    def test_invalid_context_json_returns_two(self):
        draft = self.h.write("draft.md", "x")
        bad_ctx = self.h.write("ctx.json", "{not json at all")
        cmd = [
            sys.executable, str(_CLI_PATH),
            "check", str(draft),
            "--context", str(bad_ctx),
            "--db", str(self.h.db),
            "--out-dir", str(self.h.out_dir),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("context file invalid", proc.stderr)

    def test_invalid_actor_identity_returns_two(self):
        draft = self.h.write("draft.md", "x")
        bad_actor = self.h.write_json("actor.json", ["not", "a", "dict"])
        cmd = [
            sys.executable, str(_CLI_PATH),
            "check", str(draft),
            "--actor-identity", str(bad_actor),
            "--db", str(self.h.db),
            "--out-dir", str(self.h.out_dir),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("actor identity file invalid", proc.stderr)


class TestG3WiringThroughCli(unittest.TestCase):
    """SPEC-L7-N003 SHALL FLAG (not SHALL BLOCK). G3 is exposed via
    --writer-model and --verifier-model; the result lands in the
    report's g3_self_grounding field and in the reasons list when
    the verdict is not 'ok', but does NOT promote the verdict to
    HOLD/BLOCK."""

    def setUp(self):
        self.h = _Harness()
        self.draft = self.h.write(
            "draft.md",
            "# Note\n\nA clean paragraph.\n",
        )
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_same_model_flags_requires_external_grounding_but_does_not_block(self):
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--writer-model", "claude-opus-4-7",
            "--verifier-model", "claude-opus-4-7",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        # Verdict stays PASS; G3 is informational only.
        self.assertEqual(data["verdict"], "PASS")
        self.assertIsNotNone(data["g3_self_grounding"])
        self.assertEqual(
            data["g3_self_grounding"]["verdict"], "requires_external_grounding"
        )
        # Reason recorded as a FLAG annotation, not a BLOCK or HOLD.
        self.assertTrue(any("FLAG (G3 informational)" in r for r in data["reasons"]))

    def test_family_match_records_in_g3_field(self):
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--writer-model", "claude-opus-4-7",
            "--verifier-model", "claude-haiku-4-5",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["g3_self_grounding"]["verdict"], "family_match")

    def test_cross_family_is_ok_no_flag_in_reasons(self):
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--writer-model", "claude-opus-4-7",
            "--verifier-model", "gpt-5.4",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["g3_self_grounding"]["verdict"], "ok")
        # No FLAG line when verdict is ok.
        self.assertFalse(any("FLAG (G3 informational)" in r for r in data["reasons"]))

    def test_g3_omitted_when_writer_model_not_supplied(self):
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIsNone(data["g3_self_grounding"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
