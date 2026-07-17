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
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

try:
    from conftest import get_clean_env
except ImportError:  # running as tests.test_* from the repo root
    from tests.conftest import get_clean_env


def _cli_env():
    """Hermetic CLI environment: scrubbed, with the grader pinned.

    PROVENANCE_GRADER=heuristic prevents get_grader() auto-selecting an
    ambient `claude` binary on PATH (or the CI booby-trap shim) when a
    test runs `warrantos check --verify` as a subprocess.
    """
    env = get_clean_env()
    env["PROVENANCE_GRADER"] = "heuristic"
    return env


from warrantos.provenance.overrides import record_override


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_PATH = _REPO_ROOT / "warrantos" / "cli" / "warrantos_cli.py"


_FINAL_ACTOR = {
    "context_classifier": "agent:auto",
    "insight_compiler": "human:juan.vega",
    "source_curator": "human:juan.vega",
    "clean_room_writer": "model:claude-opus-4-7",
    "reviewer_qa": "agent:policy-red-team",
    "auditor": "human:director.so",
}


class _Harness:
    """Shared scaffolding for the CLI integration tests.

    Input files (drafts, contexts, actor-identity) live in a temp dir.
    Output files (--db, --out-dir) live under .warrant/ within _REPO_ROOT
    so they are inside the working directory when the subprocess runs with
    cwd=_REPO_ROOT (path containment requirement, B5 defence in depth).
    """

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Unique per-harness subdirectory to avoid cross-test collisions.
        uid = uuid.uuid4().hex[:8]
        self._warrant_sub = _REPO_ROOT / ".warrant" / ("cli_test_" + uid)
        self._warrant_sub.mkdir(parents=True, exist_ok=True)
        self.db = self._warrant_sub / "overrides.db"
        self.out_dir = self._warrant_sub / "runs"

    def write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def write_json(self, name: str, obj) -> Path:
        return self.write(name, json.dumps(obj))

    def cleanup(self) -> None:
        self._tmp.cleanup()
        shutil.rmtree(str(self._warrant_sub), ignore_errors=True)

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
            env=_cli_env(),
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

    def test_single_actor_override_downgrades_final_prose_verdict(self):
        # P0.1: a same-actor (single-actor) review on a final-prose artefact is a
        # separation-of-duties failure and must downgrade the verdict via the
        # verdict path, not merely surface as a footer marker. The clean draft
        # would otherwise PASS; the single-actor override forces HOLD.
        run_id = "run_singleactor"
        record_override(
            self.h.db,
            run_id=run_id,
            reviewer="human:director.so",
            gate_id="G1",
            failure_class="boundary",
            risk_accepted="Same-actor review, recorded to exercise SoD.",
            compensating_control="None; this case demonstrates SoD enforcement.",
            single_actor=True,
        )
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--run-id", run_id,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn(data["verdict"], ("HOLD", "BLOCK"))
        self.assertTrue(
            any("separation of duties" in r.lower() for r in data["reasons"]),
            msg="verdict reasons should cite separation of duties: %r" % data["reasons"],
        )


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
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT),
            env=_cli_env(),
        )
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
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT),
            env=_cli_env(),
        )
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
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT),
            env=_cli_env(),
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("actor identity file invalid", proc.stderr)


class TestCostControlFlags(unittest.TestCase):
    """--salience-min and --max-verify-claims control verifier spend
    by filtering and capping the claim set sent to the grader.
    docs/COST.md."""

    def setUp(self):
        self.h = _Harness()
        # Three claims of varying salience: one statute (~1.0), one
        # magnitude (~0.55), one mild attribution (~-0.05 -> 0.0).
        self.draft = self.h.write(
            "draft.md",
            "# Demo\n\n"
            "The agency must comply with section 23 of the Privacy Act 1988.\n"
            "The forecast cost is AUD 250 million.\n"
            "Some commentators reported that the rollout was orderly.\n",
        )
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_salience_min_filters_low_salience_claims(self):
        """--salience-min 0.5 keeps load-bearing claims and drops
        descriptive ones. The skipped count is reported."""
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--verify",
            "--no-fetch",
            "--salience-min", "0.5",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        skipped = data["verifier_skipped"]
        self.assertGreater(skipped["count"], 0)
        self.assertIn("salience_min", skipped["reason"])

    def test_max_verify_claims_caps_at_one(self):
        """--max-verify-claims 1 verifies exactly one claim regardless
        of how many were detected."""
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--verify",
            "--no-fetch",
            "--max-verify-claims", "1",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertLessEqual(data["verifier_total"], 1)
        self.assertIn("max_verify_claims", data["verifier_skipped"]["reason"])

    def test_no_verify_records_verifier_not_invoked(self):
        """Without --verify, the skipped summary records the
        non-invocation."""
        proc = self.h.run(
            str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verifier_skipped"]["reason"], "verifier_not_invoked")
        self.assertEqual(data["verifier_total"], 0)


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


class TestProfileUnsupportedThreshold(unittest.TestCase):
    """Phase 1 item 3: per-profile unsupported-claim fraction thresholds.

    When the unsupported fraction exceeds the profile threshold the verdict
    is raised to HOLD even when no single claim is load-bearing, and the
    fired rule is surfaced in the run report JSON.
    """

    def setUp(self):
        self.h = _Harness()
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_audit_profile_holds_on_unsupported_year_claims(self):
        """Two uncited year-only claims (neither load-bearing) under the
        audit profile (threshold 0.0) HOLD on the fraction rule alone."""
        draft = self.h.write(
            "draft.md",
            "# Run log\n\n"
            "The portal launched in 2019.\n"
            "A refresh shipped in 2021.\n",
        )
        proc = self.h.run(str(draft), "--profile", "audit")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "HOLD")
        self.assertIsNotNone(data["verdict_rule_fired"])
        self.assertEqual(
            data["verdict_rule_fired"]["rule"], "profile_unsupported_fraction"
        )
        self.assertEqual(data["verdict_rule_fired"]["profile"], "audit")
        self.assertTrue(
            any("unsupported fraction" in r for r in data["reasons"]),
            msg=data["reasons"],
        )

    def test_changelog_profile_never_holds_on_fraction(self):
        """The changelog profile threshold is 1.0, so an all-unsupported
        set of non-load-bearing claims does not HOLD on fraction."""
        draft = self.h.write(
            "draft.md",
            "# Changelog\n\n"
            "The portal launched in 2019.\n"
            "A refresh shipped in 2021.\n",
        )
        proc = self.h.run(str(draft), "--profile", "changelog")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "PASS")
        self.assertIsNone(data["verdict_rule_fired"])

    def test_fired_rule_absent_when_all_claims_supported(self):
        """A fully-cited claim set does not trip the fraction rule."""
        draft = self.h.write(
            "draft.md",
            "# Run log\n\n"
            "The portal launched in 2019 (https://www.qld.gov.au/portal).\n",
        )
        proc = self.h.run(str(draft), "--profile", "audit")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "PASS")
        self.assertIsNone(data["verdict_rule_fired"])


class TestDecisionTriggerDetected(unittest.TestCase):
    """Phase 1 item 1: the decision trigger now fires so must/shall/require
    sentences are detected as claims (previously silently PASSed)."""

    def setUp(self):
        self.h = _Harness()
        self.actor = self.h.write_json("actor.json", _FINAL_ACTOR)

    def tearDown(self):
        self.h.cleanup()

    def test_must_comply_sentence_detected_and_holds(self):
        draft = self.h.write(
            "draft.md",
            "# Brief\n\n"
            "All agencies must comply with the data-sharing protocol.\n",
        )
        proc = self.h.run(
            str(draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertGreaterEqual(data["claims_detected"], 1)
        # final-prose threshold is 0.0, so an uncited claim HOLDs.
        self.assertEqual(data["verdict"], "HOLD")


class TestExplainProfile(unittest.TestCase):
    """Phase 1 item 2: --explain-profile prints suppression per profile
    without running the pipeline (no draft required)."""

    def setUp(self):
        self.h = _Harness()

    def tearDown(self):
        self.h.cleanup()

    def test_explain_profile_prints_table_without_draft(self):
        cmd = [
            sys.executable, str(_CLI_PATH),
            "check", "--explain-profile",
        ]
        proc = subprocess.run(
            cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=60,
            env=_cli_env(),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("boundary gate", proc.stdout)
        self.assertIn("audit", proc.stdout)
        self.assertIn("SUPPRESSED", proc.stdout)


class TestSensitivityCheckFlag(unittest.TestCase):
    """F-classification gate wired into `warrantos check --sensitivity-check`."""

    def setUp(self):
        self.h = _Harness()

    def tearDown(self):
        self.h.cleanup()

    def test_sensitive_draft_is_refused_with_exit_3(self):
        draft = self.h.write(
            "sensitive.md",
            "This Cabinet submission recommends a $250M allocation.\n",
        )
        proc = self.h.run(
            str(draft), "--profile", "brief-light", "--sensitivity-check",
        )
        self.assertEqual(proc.returncode, 3, msg=proc.stdout + proc.stderr)
        self.assertIn("Sensitivity gate BLOCKED", proc.stderr)

    def test_clean_draft_proceeds_normally(self):
        draft = self.h.write(
            "clean.md",
            "Open data improves transparency per https://example.gov.\n",
        )
        proc = self.h.run(
            str(draft), "--profile", "brief-light", "--sensitivity-check",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIn(data["verdict"], {"PASS", "HOLD"})

    def test_flag_off_by_default_does_not_block_sensitive_draft(self):
        """Without --sensitivity-check the gate never runs."""
        draft = self.h.write(
            "sensitive.md",
            "This Cabinet submission recommends a $250M allocation.\n",
        )
        proc = self.h.run(str(draft), "--profile", "brief-light")
        # No sensitivity refusal: the run proceeds and emits a JSON report.
        self.assertNotEqual(proc.returncode, 3)
        data = json.loads(proc.stdout)
        self.assertIn("verdict", data)


class TestCalibrateSubcommand(unittest.TestCase):
    """G5: `warrantos calibrate` runs the eval corpus and writes
    .warrant/calibration.json."""

    def setUp(self):
        uid = uuid.uuid4().hex[:8]
        self.out = _REPO_ROOT / ".warrant" / ("calib_test_" + uid + ".json")

    def tearDown(self):
        try:
            self.out.unlink()
        except OSError:
            pass

    def _run(self, *args):
        cmd = [sys.executable, str(_CLI_PATH), "calibrate"] + list(args)
        return subprocess.run(
            cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=120,
            env=_cli_env(),
        )

    def test_calibrate_writes_calibration_json(self):
        proc = self._run("--out", str(self.out), "--json")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertTrue(self.out.is_file())
        summary = json.loads(self.out.read_text(encoding="utf-8"))
        for key in (
            "grader", "corpus_size", "per_class_recall", "coverage_estimate",
        ):
            self.assertIn(key, summary)
        self.assertGreater(summary["corpus_size"], 0)

    def test_stored_calibration_loads_back_into_check_calibration(self):
        proc = self._run("--out", str(self.out))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        from warrantos.provenance.gates import check_calibration
        summary = json.loads(self.out.read_text(encoding="utf-8"))
        result = check_calibration(summary)
        self.assertEqual(result.total, summary["corpus_size"])
        self.assertAlmostEqual(result.coverage, summary["coverage_estimate"])


class TestWarrantosDbEnvVar(unittest.TestCase):
    """WARRANTOS_DB is honoured as the default --db path.

    The README Configuration table documents WARRANTOS_DB as the
    warrantos ledger path; this asserts the doc is true by exercising
    the resolved --db default through the argument parser. The default
    is read from the environment at parser-build time, so setting the
    env var and rebuilding the parser is the unit under test. Legacy
    PROVENANCE_DB behaviour (the v0.3 hook) is unaffected and not
    touched here.
    """

    def setUp(self):
        self._saved = os.environ.get("WARRANTOS_DB")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("WARRANTOS_DB", None)
        else:
            os.environ["WARRANTOS_DB"] = self._saved

    def _check_db_default(self):
        # Import lazily so the module-level os import in the CLI is used.
        from warrantos.cli.warrantos_cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["check", "draft.md"])
        return args.db

    def test_env_var_sets_check_db_default(self):
        os.environ["WARRANTOS_DB"] = "/tmp/custom-warrant-ledger.db"
        self.assertEqual(self._check_db_default(), "/tmp/custom-warrant-ledger.db")

    def test_default_db_when_env_var_absent(self):
        os.environ.pop("WARRANTOS_DB", None)
        expected = str(Path(".warrant") / "provenance.db")
        self.assertEqual(self._check_db_default(), expected)

    def test_env_var_sets_retention_db_default(self):
        os.environ["WARRANTOS_DB"] = "/tmp/custom-retention-ledger.db"
        from warrantos.cli.warrantos_cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["retention", "list"])
        self.assertEqual(args.db, "/tmp/custom-retention-ledger.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
