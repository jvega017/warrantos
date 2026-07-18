#!/usr/bin/env python3
"""Tests for eval/run_classifier_corpus.py (SPEC-L1-S006)."""

import importlib.util
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

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RUNNER = _REPO_ROOT / "eval" / "run_classifier_corpus.py"
_SEED_CORPUS = _REPO_ROOT / "eval" / "classifier-corpus" / "seeds.jsonl"


def _load_runner_module():
    """Load the runner as a plain module without going through subprocess."""
    spec = importlib.util.spec_from_file_location(
        "run_classifier_corpus", _RUNNER
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSeedCorpusPasses(unittest.TestCase):
    """The shipped seed corpus is a smoke test: every example
    classifies as expected, so a regression in the classifier surfaces
    immediately."""

    def test_seed_corpus_passes_when_invoked_as_subprocess(self):
        proc = subprocess.run(
            [sys.executable, str(_RUNNER), "--json"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            env=get_clean_env(),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["mismatches"], [])
        self.assertEqual(report["overall_precision"], 1.0)

    def test_seed_corpus_covers_all_eleven_classes(self):
        runner = _load_runner_module()
        report = runner.run(_SEED_CORPUS)
        # SPEC §2.2 enumerates eleven canonical classes.
        self.assertGreaterEqual(len(report["per_class_total"]), 11)


class TestRunnerOnSyntheticCorpus(unittest.TestCase):
    """The runner reports mismatches as exit code 1 and lists them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.corpus = self.tmp / "broken.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_mismatch_exits_one(self):
        self.corpus.write_text(
            '{"id": "wrong_001", "text": "Source: report.pdf", '
            '"expected_context_type": "private_reasoning"}\n',
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(_RUNNER), "--corpus", str(self.corpus), "--json"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            env=get_clean_env(),
        )
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(len(report["mismatches"]), 1)
        self.assertEqual(report["mismatches"][0]["expected"], "private_reasoning")
        self.assertEqual(report["mismatches"][0]["actual"], "empirical_evidence")

    def test_missing_corpus_exits_two(self):
        proc = subprocess.run(
            [sys.executable, str(_RUNNER), "--corpus", str(self.tmp / "absent.jsonl")],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            env=get_clean_env(),
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("corpus not found", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
