"""End-to-end tests for the attest / verify-external CLI subcommands."""

import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from cli import warrantos_cli


_ACTOR = {"writer": "human:juan", "reviewer": "human:reviewer"}
_DRAFT = "# Brief\n\nThe agency must comply with section 23 of the Privacy Act 1988.\n"

# Repo root so that .warrant/ paths are within the working directory when
# warrantos_cli.main() is called in-process (cwd = repo root).
_REPO_ROOT = Path(__file__).resolve().parent.parent


class TestAttestVerifyCli(unittest.TestCase):
    def setUp(self):
        # Sign attested bundles so the round-trip verifies under the fail-closed
        # default (an unsigned bundle is overall INVALID without --allow-unsigned).
        from provenance import attestation
        self._old_key = os.environ.pop("WARRANTOS_SIGNING_KEY", None)
        try:
            priv, _pub = attestation.generate_keypair()
            os.environ["WARRANTOS_SIGNING_KEY"] = priv
            self._signed = True
        except attestation.AttestationUnavailable:
            self._signed = False

        # Input files (draft, actor) stay in a temp dir; they are read-only inputs.
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.draft = self.dir / "draft.md"
        self.draft.write_text(_DRAFT, encoding="utf-8")
        self.actor = self.dir / "actor.json"
        self.actor.write_text(json.dumps(_ACTOR), encoding="utf-8")

        # Output artefacts (run_dir, warrant bundle) must be within .warrant/ so
        # that the path containment guard (B5 defence in depth) accepts them.
        uid = uuid.uuid4().hex[:8]
        self._warrant_sub = _REPO_ROOT / ".warrant" / ("attest_test_" + uid)
        self._warrant_sub.mkdir(parents=True, exist_ok=True)
        self.run_dir = self._warrant_sub / "run"

        # Produce a real run directory with a cbom.json.
        rc = warrantos_cli.main([
            "check", str(self.draft),
            "--profile", "final-prose",
            "--actor-identity", str(self.actor),
            "--run-id", "run_attest",
            "--out-dir", str(self.run_dir),
        ])
        self.assertEqual(rc, 0)
        self.assertTrue((self.run_dir / "cbom.json").is_file())

    def tearDown(self):
        self._tmp.cleanup()
        shutil.rmtree(str(self._warrant_sub), ignore_errors=True)
        os.environ.pop("WARRANTOS_SIGNING_KEY", None)
        if self._old_key is not None:
            os.environ["WARRANTOS_SIGNING_KEY"] = self._old_key

    def test_attest_then_verify_is_valid(self):
        warrant = self._warrant_sub / "draft.warrant"
        rc = warrantos_cli.main([
            "attest", str(self.draft), "--run-dir", str(self.run_dir), "--out", str(warrant),
        ])
        self.assertEqual(rc, 0)
        self.assertTrue(warrant.is_file())
        bundle = json.loads(warrant.read_text(encoding="utf-8"))
        self.assertEqual(bundle["version"], "warrant-bundle-v1")

        argv = ["verify-external", str(warrant), "--prose", str(self.draft)]
        if not self._signed:
            argv.append("--allow-unsigned")  # no attestation extra: integrity only
        self.assertEqual(warrantos_cli.main(argv), 0)  # VALID exits 0

    def test_unsigned_bundle_fails_closed_without_flag(self):
        # Strip the signing key so attest produces an unsigned bundle.
        os.environ.pop("WARRANTOS_SIGNING_KEY", None)
        warrant = self._warrant_sub / "unsigned.warrant"
        warrantos_cli.main(["attest", str(self.draft), "--run-dir", str(self.run_dir), "--out", str(warrant)])
        # Default: unsigned is overall INVALID -> exit 1.
        self.assertEqual(warrantos_cli.main(["verify-external", str(warrant), "--prose", str(self.draft)]), 1)
        # With the explicit opt-in: integrity-only acceptance -> exit 0.
        self.assertEqual(warrantos_cli.main(["verify-external", str(warrant), "--prose", str(self.draft), "--allow-unsigned"]), 0)

    def test_verify_detects_tampered_prose(self):
        warrant = self._warrant_sub / "draft.warrant"
        warrantos_cli.main(["attest", str(self.draft), "--run-dir", str(self.run_dir), "--out", str(warrant)])
        bad = self.dir / "bad.md"
        bad.write_text("# Brief\n\nDifferent content entirely.\n", encoding="utf-8")
        rc = warrantos_cli.main(["verify-external", str(warrant), "--prose", str(bad)])
        self.assertEqual(rc, 1)  # INVALID exits 1

    def test_verify_detects_tampered_bundle(self):
        warrant = self._warrant_sub / "draft.warrant"
        warrantos_cli.main(["attest", str(self.draft), "--run-dir", str(self.run_dir), "--out", str(warrant)])
        bundle = json.loads(warrant.read_text(encoding="utf-8"))
        # Inject a forged ledger entry; the recomputed root will no longer match.
        bundle["ledger_entries"].append({"id": 999, "kind": "forged"})
        warrant.write_text(json.dumps(bundle), encoding="utf-8")
        rc = warrantos_cli.main(["verify-external", str(warrant)])
        self.assertEqual(rc, 1)

    def test_attest_missing_run_dir_returns_two(self):
        rc = warrantos_cli.main([
            "attest", str(self.draft), "--run-dir", str(self.dir / "nope"),
            "--out", str(self._warrant_sub / "x.warrant"),
        ])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
