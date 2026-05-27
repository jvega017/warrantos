#!/usr/bin/env python3
"""Tests for hooks/claude_code_verify_hook.py — the no-API-key
in-session verification hook."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _REPO_ROOT / "hooks" / "claude_code_verify_hook.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location(
        "claude_code_verify_hook", _HOOK
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_run(run_dir: Path, *, verdict: str, claims) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "verdict.json").write_text(
        json.dumps({"run_id": run_dir.name, "verdict": verdict, "reasons": []}),
        encoding="utf-8",
    )
    (run_dir / "claims.json").write_text(
        json.dumps(claims), encoding="utf-8",
    )


class _HookHarness(unittest.TestCase):
    """Common scaffolding: a temp .warrant/runs and an isolated
    sentinel-file path so tests do not pollute one another."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.runs = self.tmp / ".warrant" / "runs"
        self.runs.mkdir(parents=True, exist_ok=True)

        # Reload the hook module for each test so the sentinel-path
        # module global resets cleanly when we chdir.
        self._saved_cwd = os.getcwd()
        os.chdir(str(self.tmp))
        self.hook = _load_hook_module()

    def tearDown(self):
        os.chdir(self._saved_cwd)
        self._tmp.cleanup()


class TestPassThrough(_HookHarness):
    """No runs, or no HOLDs, means the hook passes through (exit 0)."""

    def test_no_runs_directory_passes(self):
        # Remove the runs dir entirely.
        for p in sorted(self.runs.glob("*")):
            p.unlink()
        self.runs.rmdir()
        rc = self.hook.main([])
        self.assertEqual(rc, 0)

    def test_no_runs_passes(self):
        # Directory exists but is empty.
        rc = self.hook.main([])
        self.assertEqual(rc, 0)

    def test_verdict_pass_does_not_block(self):
        _seed_run(
            self.runs / "run_pass",
            verdict="PASS",
            claims=[{"sentence": "An ordinary claim.", "load_bearing": False}],
        )
        rc = self.hook.main([])
        self.assertEqual(rc, 0)


class TestBlockOnHold(_HookHarness):
    """When the latest run's verdict is HOLD and load-bearing
    unsupported claims exist, the hook exits 2 and writes a hand-back
    message to stderr."""

    def test_hold_with_load_bearing_claim_exits_two(self):
        _seed_run(
            self.runs / "run_hold",
            verdict="HOLD",
            claims=[
                {
                    "sentence": "The Act will save AUD 250 million.",
                    "load_bearing": True,
                    "salience": 1.0,
                    "citation": None,
                },
                {
                    "sentence": "Some lower-salience claim.",
                    "load_bearing": False,
                    "salience": 0.1,
                    "citation": None,
                },
            ],
        )
        from io import StringIO
        import sys as _sys
        saved = _sys.stderr
        _sys.stderr = buf = StringIO()
        try:
            rc = self.hook.main([])
        finally:
            _sys.stderr = saved
        self.assertEqual(rc, 2)
        msg = buf.getvalue()
        self.assertIn("WARRANTOS", msg)
        self.assertIn("AUD 250 million", msg)
        # The non-load-bearing claim is NOT in the hand-back.
        self.assertNotIn("lower-salience", msg)

    def test_citation_present_is_not_handed_back(self):
        """A load-bearing claim that DOES carry a citation token is
        not a HOLD trigger; the hook does not nag about it."""
        _seed_run(
            self.runs / "run_supported",
            verdict="HOLD",
            claims=[
                {
                    "sentence": "Section 23 of the Privacy Act 1988 (https://example.invalid/x).",
                    "load_bearing": True,
                    "salience": 1.0,
                    "citation": "https://example.invalid/x",
                },
            ],
        )
        rc = self.hook.main([])
        # Verdict is HOLD but the load-bearing claim carries an inline
        # citation; the hand-back is empty so no block.
        self.assertEqual(rc, 0)


class TestLoopSafety(_HookHarness):
    """If the same hand-back has just been delivered, the hook does
    not re-block the same turn."""

    def test_second_invocation_passes_through(self):
        _seed_run(
            self.runs / "run_loop",
            verdict="HOLD",
            claims=[{
                "sentence": "The Act will save AUD 250 million.",
                "load_bearing": True,
                "salience": 1.0,
                "citation": None,
            }],
        )
        rc1 = self.hook.main([])
        rc2 = self.hook.main([])
        self.assertEqual(rc1, 2)
        # Second invocation against the same run with the same
        # hold-count silently passes.
        self.assertEqual(rc2, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
