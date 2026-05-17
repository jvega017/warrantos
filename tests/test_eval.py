#!/usr/bin/env python3
"""tests/test_eval.py: invariant tests for the eval harness and seed corpus.

Does NOT assert specific accuracy numbers -- those are corpus-dependent and
will change as the corpus grows. Instead, asserts:

  1. eval/run_eval.py runs on the seed corpus and exits 0.
  2. Every reported metric is within [0, 1].
  3. The corpus parses as JSONL and every axis-1/axis-2 value is from the
     allowed set.
  4. The v0 false-negative item (c10) is labelled unsupported, confirming
     that the closed bleeding-citation bug remains closed in the corpus.

All tests are offline and deterministic. No sleeps. No network. Standard
library only.

Run from the repo root:
    python -m unittest tests.test_eval -v
"""

import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVAL_SCRIPT = _REPO_ROOT / "eval" / "run_eval.py"
_CORPUS = _REPO_ROOT / "eval" / "corpus" / "seed.jsonl"

# Allowed values for corpus gold labels.
_VALID_AXIS1 = {"supported", "unsupported", "tagged"}
_VALID_AXIS2 = {"verified", "unverifiable", "skipped", "na"}

# The item id for the v0 false-negative regression case.
# In seed.jsonl, c10 has a source three sentences after the claim, which must
# NOT rescue the claim. The gold label for that claim must be "unsupported".
_V0_FN_ITEM_ID = "c10"


# ---------------------------------------------------------------------------
# Helper: load run_eval as a module via importlib so we can call its functions
# directly for fine-grained assertions.
# ---------------------------------------------------------------------------

def _load_run_eval():
    spec = importlib.util.spec_from_file_location("run_eval", str(_EVAL_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Test 1: the eval script runs on the seed corpus and exits 0.
# ---------------------------------------------------------------------------

class TestRunEvalExitsZero(unittest.TestCase):
    """eval/run_eval.py must exit 0 when run against the seed corpus."""

    def test_exits_zero_on_seed_corpus(self):
        result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            "run_eval.py exited %d.\nstdout:\n%s\nstderr:\n%s"
            % (result.returncode, result.stdout, result.stderr),
        )

    def test_stdout_contains_metrics_table(self):
        """The script must print a non-empty metrics table to stdout."""
        result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT)],
            capture_output=True,
            text=True,
        )
        self.assertIn("evaluation report", result.stdout)
        self.assertIn("precision", result.stdout)
        self.assertIn("recall", result.stdout)
        self.assertIn("F1", result.stdout)

    def test_exits_one_on_missing_corpus(self):
        """When the corpus file does not exist, run_eval must exit 1."""
        result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT), "--corpus", "/does/not/exist.jsonl"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR", result.stderr)


# ---------------------------------------------------------------------------
# Test 2: every reported metric is within [0, 1].
# ---------------------------------------------------------------------------

class TestMetricsInRange(unittest.TestCase):
    """All reported float metrics must be in [0, 1]."""

    def _get_metrics(self):
        """Run the harness and return the computed axis-1 metrics dict."""
        run_eval = _load_run_eval()
        items = run_eval.load_corpus(str(_CORPUS))

        # Re-create the evaluation pipeline from run_eval internals.
        hook_mod = run_eval._load_hook()

        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from provenance.verify import verify_text
        from provenance.grade import HeuristicGrader

        grader = HeuristicGrader()
        all_axis1 = []
        all_axis2 = []
        for item in items:
            result = run_eval._evaluate_item(item, hook_mod, verify_text, grader)
            all_axis1.extend(result["axis1_results"])
            all_axis2.extend(result["axis2_results"])

        return run_eval._compute_axis1_metrics(all_axis1)

    def test_precision_in_range(self):
        m = self._get_metrics()
        self.assertGreaterEqual(m["precision"], 0.0)
        self.assertLessEqual(m["precision"], 1.0)

    def test_recall_in_range(self):
        m = self._get_metrics()
        self.assertGreaterEqual(m["recall"], 0.0)
        self.assertLessEqual(m["recall"], 1.0)

    def test_f1_in_range(self):
        m = self._get_metrics()
        self.assertGreaterEqual(m["f1"], 0.0)
        self.assertLessEqual(m["f1"], 1.0)


# ---------------------------------------------------------------------------
# Test 3: corpus parses as JSONL and all label values are from the allowed set.
# ---------------------------------------------------------------------------

class TestCorpusValidity(unittest.TestCase):
    """Structural validity of eval/corpus/seed.jsonl."""

    def _load(self):
        items = []
        for lineno, raw in enumerate(
            _CORPUS.read_text(encoding="utf-8").splitlines(), 1
        ):
            raw = raw.strip()
            if not raw:
                continue
            try:
                items.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                self.fail("Line %d is not valid JSON: %s" % (lineno, exc))
        return items

    def test_corpus_is_non_empty(self):
        items = self._load()
        self.assertGreater(len(items), 0, "corpus must contain at least one item")

    def test_required_fields_present(self):
        items = self._load()
        for item in items:
            for field in ("id", "text", "gold"):
                self.assertIn(
                    field,
                    item,
                    "item %r missing required field %r" % (item.get("id", "?"), field),
                )

    def test_axis1_values_are_valid(self):
        items = self._load()
        for item in items:
            for g in item["gold"]:
                self.assertIn(
                    g.get("axis1"),
                    _VALID_AXIS1,
                    "item %r has invalid axis1 value %r" % (item["id"], g.get("axis1")),
                )

    def test_axis2_values_are_valid(self):
        items = self._load()
        for item in items:
            for g in item["gold"]:
                self.assertIn(
                    g.get("axis2"),
                    _VALID_AXIS2,
                    "item %r has invalid axis2 value %r" % (item["id"], g.get("axis2")),
                )

    def test_ids_are_unique(self):
        items = self._load()
        ids = [item["id"] for item in items]
        self.assertEqual(len(ids), len(set(ids)), "corpus contains duplicate ids")

    def test_gold_is_list(self):
        items = self._load()
        for item in items:
            self.assertIsInstance(
                item["gold"],
                list,
                "item %r: 'gold' must be a list" % item["id"],
            )


# ---------------------------------------------------------------------------
# Test 4: the v0 false-negative item is labelled unsupported.
# ---------------------------------------------------------------------------

class TestV0FalseNegativeLabelled(unittest.TestCase):
    """The v0 false-negative regression item must be labelled unsupported.

    Item c10 has a source URL three sentences after the claim. The v0 heuristic
    only looks one sentence ahead (citation-lead). The gold label must remain
    'unsupported' to confirm the bleeding-citation bug stays closed in the
    corpus and that the harness correctly exercises it.
    """

    def test_v0_fn_item_exists(self):
        items = [
            json.loads(l)
            for l in _CORPUS.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        ids = [item["id"] for item in items]
        self.assertIn(
            _V0_FN_ITEM_ID,
            ids,
            "Expected v0 false-negative item %r in corpus" % _V0_FN_ITEM_ID,
        )

    def test_v0_fn_claim_is_unsupported(self):
        items = [
            json.loads(l)
            for l in _CORPUS.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        item = next((i for i in items if i["id"] == _V0_FN_ITEM_ID), None)
        self.assertIsNotNone(item, "Item %r not found" % _V0_FN_ITEM_ID)
        # At least one gold entry must have axis1 == "unsupported".
        unsupported_entries = [g for g in item["gold"] if g["axis1"] == "unsupported"]
        self.assertGreater(
            len(unsupported_entries),
            0,
            "Item %r must have at least one gold entry with axis1='unsupported'; "
            "got: %r" % (_V0_FN_ITEM_ID, [g["axis1"] for g in item["gold"]]),
        )

    def test_v0_fn_heuristic_predicts_unsupported(self):
        """The v0 heuristic itself must predict unsupported for item c10.

        This confirms the test corpus entry is exercising the heuristic
        in the expected direction, not just asserting a vacuous label.
        """
        spec = importlib.util.spec_from_file_location(
            "_hook", str(_REPO_ROOT / "hooks" / "provenance_check.py")
        )
        hook_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_mod)

        items = [
            json.loads(l)
            for l in _CORPUS.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        item = next((i for i in items if i["id"] == _V0_FN_ITEM_ID), None)
        self.assertIsNotNone(item)

        rows, _totals = hook_mod.analyse(item["text"])
        # There must be at least one predicted row, and it must be unsupported
        # (the heuristic must not have mistakenly treated the distant source
        # as an adjacent citation-lead).
        statuses = [r[0] for r in rows]
        self.assertIn(
            "unsupported",
            statuses,
            "v0 heuristic should predict 'unsupported' for item %r "
            "(source is two sentences away); got: %r" % (_V0_FN_ITEM_ID, statuses),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
